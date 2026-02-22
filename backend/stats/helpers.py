from __future__ import annotations
import re
import os
import time
import mimetypes
import logging
from typing import Any, Dict, List, Optional, Iterable
from pathlib import Path
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlparse, urlunparse

import requests
from django.http import HttpRequest, Http404
from settings.models import GeneralSettings
from .i18n_map import tr as i18n_tr
from .utils import to_int


logger = logging.getLogger(__name__)


def _normalize_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, Iterable):
        return [str(item).strip() for item in value]
    return []


_AGENT_EXT_RE = re.compile(r"\b([0-9]{3,6})\b")
_FILTER_SESSION_KEY = "ui_saved_filters"
_LIST_FILTER_KEYS = {"queues", "agents"}
_SCALAR_FILTER_KEYS = {"start", "end", "src", "dst", "disposition", "channel", "caller", "q", "page_size"}
_PERSISTED_FILTER_KEYS = _LIST_FILTER_KEYS | _SCALAR_FILTER_KEYS


def _user_allowed(request: HttpRequest) -> bool:
    from accounts.models import UserRoles
    return request.user.is_authenticated and request.user.role in {
        UserRoles.ADMIN,
        UserRoles.SUPERVISOR,
        UserRoles.ANALYST,
        UserRoles.AGENT,
    }


def _admin_allowed(request: HttpRequest) -> bool:
    from accounts.models import UserRoles
    return request.user.is_authenticated and request.user.role == UserRoles.ADMIN


def _saved_filters(request: HttpRequest) -> Dict[str, Any]:
    raw = request.session.get(_FILTER_SESSION_KEY, {})
    return raw if isinstance(raw, dict) else {}


def _parse_param_list(raw_items: List[str], raw_single: str | None = None) -> List[str]:
    parsed: List[str] = []
    if raw_items:
        for item in raw_items:
            parsed.extend(_normalize_list(item))
    else:
        parsed.extend(_normalize_list(raw_single))

    unique: List[str] = []
    for item in parsed:
        if item not in unique:
            unique.append(item)
    return unique


def _persist_filters(request: HttpRequest) -> None:
    if request.method != "GET":
        return
    if not request.GET:
        return

    current = dict(_saved_filters(request))
    updated = False
    for key in _PERSISTED_FILTER_KEYS:
        if key not in request.GET:
            continue
        if key in _LIST_FILTER_KEYS:
            value: Any = _parse_param_list(request.GET.getlist(key), request.GET.get(key))
        else:
            value = (request.GET.get(key) or "").strip()
        if current.get(key) != value:
            current[key] = value
            updated = True
    if updated:
        request.session[_FILTER_SESSION_KEY] = current
        request.session.modified = True


def _filter_value(request: HttpRequest, key: str, default: str = "") -> str:
    if key in request.GET:
        return (request.GET.get(key) or "").strip()
    saved = _saved_filters(request)
    value = saved.get(key, default)
    return str(value).strip() if value is not None else default


def _filter_list(request: HttpRequest, key: str) -> List[str]:
    if key in request.GET:
        return _parse_param_list(request.GET.getlist(key), request.GET.get(key))
    saved = _saved_filters(request)
    saved_value = saved.get(key, [])
    if isinstance(saved_value, list):
        raw_items = [str(item) for item in saved_value]
        return _parse_param_list(raw_items)
    return _parse_param_list([], str(saved_value))


def _get_param_list(request: HttpRequest, key: str) -> List[str]:
    return _filter_list(request, key)


def _interval_from_request(request: HttpRequest) -> tuple[datetime, datetime]:
    from .views import _parse_datetime
    start = _parse_datetime(_filter_value(request, "start"))
    end = _parse_datetime(_filter_value(request, "end"))
    if not end:
        end = datetime.now().replace(hour=23, minute=59, second=59)
    if not start:
        start = end.replace(hour=0, minute=0, second=0)
    return start, end


def _build_queuelog_filter_sql(
    start: datetime,
    end: datetime,
    queues: List[str] | None,
    agents: List[str] | None,
    events: List[str],
) -> tuple[str, List[Any]]:
    where = [
        "time >= %s",
        "time <= %s",
        f"event IN ({','.join(['%s'] * len(events))})",
    ]
    params: List[Any] = [start, end, *events]

    queue_params = list(queues or [])
    if queue_params:
        where.append(f"queuename IN ({','.join(['%s'] * len(queue_params))})")
        params.extend(queue_params)

    agent_params = list(agents or [])
    if agent_params:
        where.append(f"agent IN ({','.join(['%s'] * len(agent_params))})")
        params.extend(agent_params)

    return " AND ".join(where), params


def _fetch_queuelog_page(
    start: datetime,
    end: datetime,
    queues: List[str] | None,
    agents: List[str] | None,
    events: List[str],
    page: int,
    page_size: int,
) -> tuple[List[Dict[str, Any]], int]:
    from django.db import connections
    where_sql, params = _build_queuelog_filter_sql(start, end, queues, agents, events)
    requested_page = max(1, page)
    safe_page_size = max(1, page_size)

    sql = f"""
        SELECT time, callid, queuename, agent, event, data1, data2, data3
        FROM queuelog
        WHERE {where_sql}
        ORDER BY time DESC
        LIMIT %s OFFSET %s
    """
    count_sql = f"SELECT COUNT(*) FROM queuelog WHERE {where_sql}"

    with connections["default"].cursor() as cursor:
        cursor.execute(count_sql, params)
        total = int(cursor.fetchone()[0] or 0)
        total_pages = max(1, (total + safe_page_size - 1) // safe_page_size) if safe_page_size else 1
        safe_page = min(requested_page, total_pages)
        offset = (safe_page - 1) * safe_page_size

        cursor.execute(sql, [*params, safe_page_size, offset])
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    return rows, total


def _queuelog_avg_numeric(
    start: datetime,
    end: datetime,
    queues: List[str] | None,
    agents: List[str] | None,
    events: List[str],
    data_column: str,
) -> float:
    from django.db import connections
    allowed_columns = {"data1", "data2", "data3"}
    if data_column not in allowed_columns:
        return 0.0
    where_sql, params = _build_queuelog_filter_sql(start, end, queues, agents, events)
    sql = f"SELECT COALESCE(AVG(CAST({data_column} AS UNSIGNED)), 0) FROM queuelog WHERE {where_sql}"
    with connections["default"].cursor() as cursor:
        cursor.execute(sql, params)
        avg_value = cursor.fetchone()[0]
    try:
        return round(float(avg_value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _agent_aliases(value: str) -> List[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    aliases: List[str] = [raw]

    current = raw
    if "/" in current:
        current = current.split("/", 1)[1].strip()
        aliases.append(current)
    if "@" in current:
        current = current.split("@", 1)[0].strip()
        aliases.append(current)
    if ";" in current:
        current = current.split(";", 1)[0].strip()
        aliases.append(current)
    if "-" in current and current.rsplit("-", 1)[1].isdigit():
        aliases.append(current.rsplit("-", 1)[0].strip())

    for match in _AGENT_EXT_RE.findall(raw):
        aliases.append(match)

    unique: List[str] = []
    for item in aliases:
        if item and item not in unique:
            unique.append(item)
    return unique


def _agent_map() -> Dict[str, str]:
    from settings.models import AgentDisplayMapping
    amap: Dict[str, str] = {}
    for item in AgentDisplayMapping.objects.all():
        display = item.agent_display_name
        for key in _agent_aliases(item.agent_system_name):
            amap.setdefault(key, display)
    return amap


def _queue_map() -> Dict[str, str]:
    from settings.models import QueueDisplayMapping
    return {item.queue_system_name: item.queue_display_name for item in QueueDisplayMapping.objects.all()}


def _display_queue(value: str, qmap: Dict[str, str]) -> str:
    return qmap.get(value, value)


def _display_agent(value: str, amap: Dict[str, str]) -> str:
    for key in _agent_aliases(value):
        if key in amap:
            return amap[key]
    aliases = _agent_aliases(value)
    return aliases[-1] if aliases else value


def _human_party(value: str, amap: Dict[str, str]) -> str:
    from .i18n_map import tr as i18n_tr
    raw = str(value or "").strip()
    if not raw or raw.lower() in {"<unknown>", "unknown"}:
        return i18n_tr("Неизвестно")
    display = _display_agent(raw, amap)
    aliases = _agent_aliases(raw)
    ext = next((a for a in aliases if a.isdigit() and 2 <= len(a) <= 6), "")
    if ext and display != ext:
        return f"{display} ({ext})"
    return display


def _human_channel(value: str, amap: Dict[str, str]) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    tech = raw.split("/", 1)[0] if "/" in raw else ""
    base = raw
    if "-" in base:
        left, right = base.rsplit("-", 1)
        if right and all(ch in "0123456789abcdefABCDEF" for ch in right):
            base = left
    display = _display_agent(base, amap)
    return f"{display} [{tech}]" if tech and display != base else raw


def _extract_operator_ext(value: str) -> str:
    for alias in _agent_aliases(value):
        if alias.isdigit() and 2 <= len(alias) <= 6:
            return alias
    return ""


def _duration_to_seconds(value: Any) -> int:
    raw = str(value or "").strip()
    if not raw:
        return 0
    if raw.isdigit():
        return int(raw)
    parts = raw.split(":")
    if len(parts) != 3:
        return 0
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
    except (TypeError, ValueError):
        return 0
    return (hours * 3600) + (minutes * 60) + seconds


def _channel_row_rank(row: Dict[str, Any]) -> tuple[int, int, int]:
    app = str(row.get("Application", "")).strip().lower()
    app_priority = {
        "queue": 4,
        "dial": 3,
        "bridge": 3,
        "appqueue": 2,
    }.get(app, 1)
    caller = str(row.get("CallerIDNum", "")).strip()
    connected = str(row.get("ConnectedLineNum", "")).strip()
    known_parties = int(bool(caller and caller.lower() not in {"<unknown>", "unknown"})) + int(
        bool(connected and connected.lower() not in {"<unknown>", "unknown"})
    )
    duration = _duration_to_seconds(row.get("Duration", ""))
    return app_priority, known_parties, duration


def _payout_rate_map() -> Dict[str, float]:
    from settings.models import OperatorPayoutRate
    from decimal import Decimal
    rates: Dict[str, Decimal] = {}
    for item in OperatorPayoutRate.objects.all():
        for key in _agent_aliases(item.agent_system_name):
            rates.setdefault(key, Decimal(item.rate_per_minute))
    return rates


def _unique_non_empty(values: List[str]) -> List[str]:
    seen = set()
    unique: List[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _is_internal_party(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    aliases = _agent_aliases(raw)
    if any(alias.isdigit() and 2 <= len(alias) <= 6 for alias in aliases):
        return True
    lowered = raw.lower()
    return lowered.startswith(("sip/", "pjsip/", "local/", "agent/"))


def _classify_call_direction(src: str, dst: str, dcontext: str, queue_agent: str) -> str:
    src_internal = _is_internal_party(src)
    dst_internal = _is_internal_party(dst)
    dcontext_lower = str(dcontext or "").strip().lower()

    if src_internal and not dst_internal:
        return "outgoing"
    if dst_internal and not src_internal:
        return "incoming"
    if queue_agent:
        return "incoming"
    if "from-internal" in dcontext_lower:
        return "outgoing"
    if any(token in dcontext_lower for token in ("from-trunk", "from-pstn", "from-external")):
        return "incoming"
    return "unknown"


def _get_available_queues() -> List[str]:
    from django.db import connections
    import logging
    logger = logging.getLogger(__name__)
    from settings.models import QueueDisplayMapping

    queues: List[str] = []
    with connections["default"].cursor() as cursor:
        try:
            cursor.execute("SELECT DISTINCT queuename FROM queues_new WHERE queuename IS NOT NULL AND queuename <> '' ORDER BY queuename")
            queues.extend([str(row[0]).strip() for row in cursor.fetchall()])
        except Exception as exc:
            logger.warning("Failed to load queues from queues_new: %s", exc)
        if not _unique_non_empty(queues):
            try:
                cursor.execute("SELECT DISTINCT queuename FROM queuelog WHERE queuename IS NOT NULL AND queuename <> '' ORDER BY queuename")
                queues.extend([str(row[0]).strip() for row in cursor.fetchall()])
            except Exception as exc:
                logger.warning("Failed to load queues from queuelog: %s", exc)

    queues.extend(list(QueueDisplayMapping.objects.values_list("queue_system_name", flat=True)))
    return _unique_non_empty(queues)


def _is_valid_agent_value(value: str) -> bool:
    v = (value or "").strip()
    if len(v) < 2:
        return False
    return any(ch.isdigit() for ch in v) or any(ch.isalpha() for ch in v)


def _get_available_agents() -> List[Dict[str, str]]:
    from django.db import connections
    import logging
    logger = logging.getLogger(__name__)
    from settings.models import AgentDisplayMapping

    out: List[Dict[str, str]] = []
    seen = set()

    def _add_agent(agent_value: str, name_value: str = "") -> None:
        agent = str(agent_value or "").strip()
        if (not agent) or (not _is_valid_agent_value(agent)) or agent in seen:
            return
        seen.add(agent)
        out.append({"agent": agent, "name": str(name_value or "").strip()})

    with connections["default"].cursor() as cursor:
        try:
            cursor.execute(
                """
                SELECT agent, MAX(COALESCE(name, '')) AS name
                FROM agents_new
                WHERE agent IS NOT NULL AND agent <> ''
                GROUP BY agent
                ORDER BY agent
                """
            )
            for row in cursor.fetchall():
                _add_agent(str(row[0]), str(row[1] or ""))
        except Exception as exc:
            logger.warning("Failed to load agents from agents_new: %s", exc)

        if not out:
            try:
                cursor.execute(
                    """
                    SELECT agent, '' AS name
                    FROM queuelog
                    WHERE agent IS NOT NULL AND agent <> ''
                    GROUP BY agent
                    ORDER BY agent
                    """
                )
                for row in cursor.fetchall():
                    _add_agent(str(row[0]), "")
            except Exception as exc:
                logger.warning("Failed to load agents from queuelog: %s", exc)

    for system_name in AgentDisplayMapping.objects.values_list("agent_system_name", flat=True):
        _add_agent(str(system_name), "")
    return out


def _caller_map_by_callids(callids: List[str]) -> Dict[str, str]:
    from django.db import connections
    clean = [c for c in callids if c]
    if not clean:
        return {}
    out: Dict[str, str] = {}
    chunk_size = 500
    with connections["default"].cursor() as cursor:
        for i in range(0, len(clean), chunk_size):
            chunk = clean[i:i + chunk_size]
            placeholders = ",".join(["%s"] * len(chunk))
            cursor.execute(
                f"""
                SELECT callid,
                       SUBSTRING_INDEX(
                         GROUP_CONCAT(NULLIF(data2, '') ORDER BY time DESC SEPARATOR ','),
                         ',',
                         1
                       ) AS caller
                FROM queuelog
                WHERE event = 'ENTERQUEUE' AND callid IN ({placeholders})
                GROUP BY callid
                """,
                chunk,
            )
            for callid, caller in cursor.fetchall():
                out[str(callid)] = str(caller or "")
    return out

def _recording_file_by_uniqueid(uniqueid: str) -> str:
    from django.db import connections
    from django.http import Http404
    with connections["default"].cursor() as cursor:
        cursor.execute("SELECT recordingfile FROM cdr WHERE uniqueid = %s", [uniqueid])
        row = cursor.fetchone()
    if not row or not row[0]:
        raise Http404("Recording not found")
    return str(row[0])


def _resolve_recording_local_path(recording_path: str) -> Path | None:
    from django.conf import settings as django_settings
    import logging
    logger = logging.getLogger(__name__)

    candidates: List[Path] = []
    raw = Path(recording_path)
    if raw.is_absolute():
        candidates.append(raw)
    monitor_base = Path(getattr(django_settings, "ASTERISK_MONITOR_PATH", "/var/spool/asterisk/monitor/"))
    candidates.append(monitor_base / recording_path)
    candidates.append(monitor_base / raw.name)

    for path in candidates:
        try:
            resolved = path.resolve()
            if resolved.is_file():
                return resolved
        except Exception as exc:
            logger.debug("Could not resolve candidate path %s: %s", path, exc)
            continue
    return None


def _parse_range_header(range_header: str, file_size: int) -> tuple[int, int] | None:
    if not range_header or not range_header.startswith("bytes="):
        return None
    value = range_header.replace("bytes=", "", 1).strip()
    if "," in value:
        value = value.split(",", 1)[0].strip()
    if "-" not in value:
        return None
    start_raw, end_raw = value.split("-", 1)
    try:
        if start_raw == "":
            length = int(end_raw)
            if length <= 0:
                return None
            start = max(0, file_size - length)
            end = file_size - 1
            return start, end
        start = int(start_raw)
        end = int(end_raw) if end_raw else file_size - 1
        if start > end or start < 0 or end >= file_size:
            return None
        return start, end
    except ValueError:
        return None


def _stream_file_range(path: Path, start: int, end: int, chunk_size: int = 8192):
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = handle.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _get_general_settings() -> GeneralSettings:
    obj = GeneralSettings.objects.first()
    return obj if obj else GeneralSettings.objects.create()


def _fetch_recording_bytes_for_call(callid: str) -> tuple[str, bytes, str]:
    recording_path = _recording_file_by_uniqueid(callid)
    local_path = _resolve_recording_local_path(recording_path)
    if local_path:
        content_type = mimetypes.guess_type(str(local_path))[0] or "application/octet-stream"
        return local_path.name, local_path.read_bytes(), content_type

    conf = _get_general_settings()
    if not conf.download_url:
        raise Http404("Recording not available")

    params = {"url": recording_path, "token": conf.download_token}
    auth = (conf.download_user, conf.download_password)
    upstream = requests.get(conf.download_url, params=params, auth=auth, timeout=(5, 60))
    upstream.raise_for_status()
    filename = os.path.basename(recording_path) or f"{callid}.wav"
    content_type = upstream.headers.get("Content-Type", "application/octet-stream")
    return filename, upstream.content, content_type


def _transcribe_call(callid: str) -> tuple[bool, str]:
    from .models import CallTranscription
    conf = _get_general_settings()
    api_url = str(conf.transcription_url or "").strip()
    api_key = str(conf.transcription_api_key or "").strip()
    if not api_url or not api_key:
        return False, i18n_tr("Не настроен URL/API ключ сервиса транскрибации")

    transcription, _ = CallTranscription.objects.get_or_create(callid=callid)
    transcription.status = CallTranscription.Status.PROCESSING
    transcription.error_message = ""
    transcription.save(update_fields=["status", "error_message", "updated_at"])

    try:
        filename, file_bytes, content_type = _fetch_recording_bytes_for_call(callid)
        request_headers = {"X-API-KEY": api_key, "Accept": "application/json"}
        request_files = {"file": (filename, file_bytes, content_type)}
        request_timeout = (15, 900)
        request_attempts = 3

        candidate_urls = [api_url]
        parsed = urlparse(api_url)
        if parsed.scheme == "https":
            # Some endpoints are plain HTTP but mistakenly configured as HTTPS.
            candidate_urls.append(urlunparse(parsed._replace(scheme="http")))

        response = None
        last_error: requests.RequestException | None = None
        for target_url in candidate_urls:
            for attempt in range(1, request_attempts + 1):
                try:
                    response = requests.post(
                        target_url,
                        headers=request_headers,
                        files=request_files,
                        timeout=request_timeout,
                    )
                    response.raise_for_status()
                    break
                except (requests.Timeout, requests.ConnectionError) as exc:
                    last_error = exc
                    if attempt < request_attempts:
                        time.sleep(1)
                        continue
                    break
                except requests.RequestException as exc:
                    last_error = exc
                    break
            if response is not None:
                break

        if response is None:
            if last_error is not None:
                raise last_error
            raise requests.RequestException(i18n_tr("Не удалось получить ответ от сервиса транскрибации"))

        response.raise_for_status()
        payload = response.json() if response.content else {}
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError(i18n_tr("Сервис вернул пустой текст"))

        transcription.status = CallTranscription.Status.SUCCESS
        transcription.text = text
        transcription.error_message = ""
        transcription.save(update_fields=["status", "text", "error_message", "updated_at"])
        return True, i18n_tr("Транскрипт успешно получен")
    except Http404:
        error_message = i18n_tr("Аудиозапись для звонка не найдена")
    except requests.RequestException as exc:
        error_message = f"{i18n_tr('Ошибка запроса к сервису транскрибации')}: {exc}"
    except (ValueError, TypeError) as exc:
        error_message = str(exc)
    except Exception as exc:
        error_message = f"{i18n_tr('Ошибка транскрибации')}: {exc}"

    transcription.status = CallTranscription.Status.FAILED
    transcription.error_message = error_message
    transcription.save(update_fields=["status", "error_message", "updated_at"])
    return False, error_message

