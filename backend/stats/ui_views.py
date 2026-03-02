from typing import Any, Dict, List, Optional, Tuple
import os
import mimetypes
from pathlib import Path
import logging
import threading
import json
import re
import sqlite3
import time
from datetime import datetime

import requests
from django.shortcuts import render, redirect
from django.http import HttpRequest, HttpResponse, Http404, StreamingHttpResponse, FileResponse, JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.conf import settings as django_settings
from django.db.models import QuerySet
from django.db import close_old_connections
from django.views.decorators.http import require_http_methods, require_POST

from settings.models import QueueDisplayMapping, AgentDisplayMapping, OperatorPayoutRate, GeneralSettings

from .helpers import (
    _get_general_settings,
    _user_allowed,
    _admin_allowed,
    _display_queue,
    _display_agent,
    _queue_map,
    _agent_map,
    _get_available_queues,
    _get_available_agents,
    _transcribe_call,
    _resolve_recording_local_path,
    _recording_file_by_uniqueid,
    _parse_range_header,
    _stream_file_range,
)
from .datasets import (
    answered_dataset,
    unanswered_dataset,
    cdr_dataset,
    outbound_dataset,
    call_detail_dataset,
    summary_dataset,
    analytics_dataset,
    payout_dataset,
    dashboard_traffic_dataset,
    dashboard_queues_dataset,
    dashboard_operators_dataset,
)
from .i18n_map import tr as i18n_tr
from .ami_integration import _build_ami_snapshot, AMIManager

logger = logging.getLogger(__name__)
ALLOWED_PRODUCT_EVENTS = {"share_clicked", "share_opened"}
_PHONE_RE = re.compile(r"[^0-9*+#]")


def _blacklist_db_path() -> Path:
    configured = str(getattr(django_settings, "ASTERISK_BLACKLIST_SQLITE_PATH", "") or "").strip()
    candidates = [configured] if configured else []
    candidates.extend(
        [
            "/var/lib/asterisk/astdb.sqlite3",
            "/var/lib/asterisk/blacklist.sqlite3",
        ]
    )
    existing = [Path(item) for item in candidates if item]
    for path in existing:
        if path.exists():
            return path
    return existing[0] if existing else Path("/var/lib/asterisk/astdb.sqlite3")


def _normalize_blacklist_number(value: str) -> str:
    cleaned = _PHONE_RE.sub("", str(value or "").strip())
    return cleaned


def _extract_blacklist_number(key: str) -> str:
    raw = str(key or "").strip()
    if "/blacklist/" in raw:
        return raw.split("/blacklist/", 1)[1].strip()
    if raw.startswith("blacklist/"):
        return raw.split("blacklist/", 1)[1].strip()
    return raw.rsplit("/", 1)[-1].strip()


def _detect_blacklist_schema(conn: sqlite3.Connection) -> Tuple[str, str, str, Optional[str]]:
    table_rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    tables = {str(row[0]) for row in table_rows}
    preferred_tables = ("blacklist", "black_list", "blocked_numbers", "blocked", "blacklist_numbers")
    number_columns = ("number", "phone", "callerid", "caller_id", "did", "value")
    reason_columns = ("reason", "comment", "description", "note", "memo")

    for table_name in preferred_tables:
        if table_name not in tables:
            continue
        cols = [str(item[1]) for item in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()]
        number_col = next((col for col in number_columns if col in cols), None)
        if not number_col:
            continue
        reason_col = next((col for col in reason_columns if col in cols), None)
        return "table", table_name, number_col, reason_col

    if "astdb" in tables:
        cols = {str(item[1]) for item in conn.execute('PRAGMA table_info("astdb")').fetchall()}
        if {"key", "value"}.issubset(cols):
            return "astdb", "astdb", "key", "value"

    raise ValueError("Не найдена таблица black list в SQLite базе Asterisk")


def _blacklist_list(search: str = "") -> Dict[str, Any]:
    db_path = _blacklist_db_path()
    if not db_path.exists():
        return {
            "rows": [],
            "db_path": str(db_path),
            "error": f"SQLite база не найдена: {db_path}",
        }

    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            mode, table_name, number_col, reason_col = _detect_blacklist_schema(conn)

            if mode == "astdb":
                sql = """
                    SELECT rowid AS rowid, key, value
                    FROM astdb
                    WHERE (key LIKE '/blacklist/%' OR key LIKE '%/blacklist/%')
                """
                params: List[Any] = []
                if search:
                    sql += " AND key LIKE ?"
                    params.append(f"%{search}%")
                sql += " ORDER BY key"
                db_rows = conn.execute(sql, params).fetchall()
                rows = []
                for item in db_rows:
                    number = _extract_blacklist_number(str(item["key"]))
                    rows.append(
                        {
                            "id": int(item["rowid"]),
                            "number": number,
                            "reason": str(item["value"] or ""),
                            "source_key": str(item["key"]),
                        }
                    )
                return {"rows": rows, "db_path": str(db_path), "error": "", "mode": "astdb"}

            sql = f'SELECT rowid AS rowid, "{number_col}" AS number'
            if reason_col:
                sql += f', "{reason_col}" AS reason'
            else:
                sql += ", '' AS reason"
            sql += f' FROM "{table_name}" WHERE COALESCE("{number_col}", \'\') <> \'\''
            params = []
            if search:
                sql += f' AND "{number_col}" LIKE ?'
                params.append(f"%{search}%")
            sql += f' ORDER BY "{number_col}"'
            db_rows = conn.execute(sql, params).fetchall()
            rows = [{"id": int(item["rowid"]), "number": str(item["number"] or ""), "reason": str(item["reason"] or "")} for item in db_rows]
            return {"rows": rows, "db_path": str(db_path), "error": "", "mode": "table"}
    except sqlite3.Error as exc:
        return {"rows": [], "db_path": str(db_path), "error": f"Ошибка SQLite: {exc}"}
    except ValueError as exc:
        return {"rows": [], "db_path": str(db_path), "error": str(exc)}


def _sqlite_connect_with_timeout(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _sqlite_write_with_retry(action, attempts: int = 5, delay: float = 0.5) -> None:
    for idx in range(attempts):
        try:
            action()
            return
        except sqlite3.OperationalError as exc:
            if "database is locked" not in str(exc).lower() or idx == attempts - 1:
                raise
            time.sleep(delay * (idx + 1))


def _blacklist_create(number: str, reason: str) -> None:
    db_path = _blacklist_db_path()
    if not db_path.exists():
        raise ValueError(f"SQLite база не найдена: {db_path}")
    def _action() -> None:
        with _sqlite_connect_with_timeout(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            mode, table_name, number_col, reason_col = _detect_blacklist_schema(conn)
            if mode == "astdb":
                key = f"/blacklist/{number}"
                existing = conn.execute("SELECT 1 FROM astdb WHERE key = ?", [key]).fetchone()
                if existing:
                    raise ValueError("Номер уже есть в черном списке")
                conn.execute("INSERT INTO astdb (key, value) VALUES (?, ?)", [key, reason or "1"])
                conn.commit()
                return

            existing = conn.execute(f'SELECT 1 FROM "{table_name}" WHERE "{number_col}" = ?', [number]).fetchone()
            if existing:
                raise ValueError("Номер уже есть в черном списке")
            if reason_col:
                conn.execute(
                    f'INSERT INTO "{table_name}" ("{number_col}", "{reason_col}") VALUES (?, ?)',
                    [number, reason],
                )
            else:
                conn.execute(f'INSERT INTO "{table_name}" ("{number_col}") VALUES (?)', [number])
            conn.commit()

    _sqlite_write_with_retry(_action)


def _blacklist_update(entry_id: int, number: str, reason: str) -> None:
    db_path = _blacklist_db_path()
    if not db_path.exists():
        raise ValueError(f"SQLite база не найдена: {db_path}")
    def _action() -> None:
        with _sqlite_connect_with_timeout(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            mode, table_name, number_col, reason_col = _detect_blacklist_schema(conn)
            if mode == "astdb":
                current = conn.execute("SELECT key FROM astdb WHERE rowid = ?", [entry_id]).fetchone()
                if not current:
                    raise ValueError("Запись не найдена")
                new_key = f"/blacklist/{number}"
                duplicate = conn.execute("SELECT 1 FROM astdb WHERE key = ? AND rowid <> ?", [new_key, entry_id]).fetchone()
                if duplicate:
                    raise ValueError("Номер уже есть в черном списке")
                conn.execute("UPDATE astdb SET key = ?, value = ? WHERE rowid = ?", [new_key, reason or "1", entry_id])
                conn.commit()
                return

            duplicate = conn.execute(
                f'SELECT 1 FROM "{table_name}" WHERE "{number_col}" = ? AND rowid <> ?',
                [number, entry_id],
            ).fetchone()
            if duplicate:
                raise ValueError("Номер уже есть в черном списке")
            if reason_col:
                conn.execute(
                    f'UPDATE "{table_name}" SET "{number_col}" = ?, "{reason_col}" = ? WHERE rowid = ?',
                    [number, reason, entry_id],
                )
            else:
                conn.execute(
                    f'UPDATE "{table_name}" SET "{number_col}" = ? WHERE rowid = ?',
                    [number, entry_id],
                )
            conn.commit()

    _sqlite_write_with_retry(_action)


def _blacklist_delete(entry_id: int) -> None:
    db_path = _blacklist_db_path()
    if not db_path.exists():
        raise ValueError(f"SQLite база не найдена: {db_path}")
    def _action() -> None:
        with _sqlite_connect_with_timeout(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            mode, table_name, _, _ = _detect_blacklist_schema(conn)
            if mode == "astdb":
                conn.execute("DELETE FROM astdb WHERE rowid = ?", [entry_id])
            else:
                conn.execute(f'DELETE FROM "{table_name}" WHERE rowid = ?', [entry_id])
            conn.commit()

    _sqlite_write_with_retry(_action)


def _handle_blacklist_post(request: HttpRequest) -> tuple[str, str]:
    action = (request.POST.get("action") or "save").strip().lower()
    raw_number = (request.POST.get("number") or "").strip()
    normalized_number = _normalize_blacklist_number(raw_number)
    reason = (request.POST.get("reason") or "").strip()
    entry_id_raw = (request.POST.get("entry_id") or "").strip()

    try:
        if action == "delete":
            entry_id = int(entry_id_raw or "0")
            if entry_id <= 0:
                raise ValueError("Не передан ID записи для удаления")
            _blacklist_delete(entry_id)
            return i18n_tr("Номер удалён из черного списка"), ""

        if not normalized_number:
            raise ValueError("Введите корректный номер")
        if entry_id_raw:
            entry_id = int(entry_id_raw)
            _blacklist_update(entry_id, normalized_number, reason)
            return i18n_tr("Запись черного списка обновлена"), ""
        _blacklist_create(normalized_number, reason)
        return i18n_tr("Номер добавлен в черный список"), ""
    except (ValueError, sqlite3.Error) as exc:
        return "", str(exc)


def _is_valid_callid(callid: str) -> bool:
    return bool(callid) and all(c.isalnum() or c in ".-_:" for c in callid)


def _transcription_status_payload(callid: str) -> Dict[str, Any]:
    from .models import Cdr, CallTranscription

    normalized_callid = str(callid or "").strip()
    conf = _get_general_settings()
    transcription_configured = bool((conf.transcription_url or "").strip() and (conf.transcription_api_key or "").strip())

    cdr_row = (
        Cdr.objects.filter(uniqueid=normalized_callid)
        .order_by("-calldate")
        .values("recordingfile")
        .first()
    )
    has_recording = bool(cdr_row and cdr_row.get("recordingfile"))

    transcription = CallTranscription.objects.filter(callid=normalized_callid).first()
    if not transcription:
        return {
            "status": CallTranscription.Status.PENDING,
            "text": "",
            "chunks": [],
            "error_message": "",
            "transcription_configured": transcription_configured,
            "has_recording": has_recording,
        }

    text = str(transcription.text or "").strip()
    chunks = [part.strip() for part in text.splitlines() if part.strip()]
    return {
        "status": transcription.status,
        "text": text,
        "chunks": chunks,
        "error_message": str(transcription.error_message or ""),
        "transcription_configured": transcription_configured,
        "has_recording": has_recording,
    }


def _run_transcription_background(callid: str) -> None:
    close_old_connections()
    try:
        _transcribe_call(callid)
    except Exception as exc:
        logger.exception("Async transcription failed for %s: %s", callid, exc)
    finally:
        close_old_connections()


def _base_context(request: HttpRequest) -> Dict[str, Any]:
    conf = _get_general_settings()
    return {
        "title": i18n_tr("Статистика очередей"),
        "settings": conf,
        "is_admin": request.user.is_superuser or request.user.is_staff if request.user.is_authenticated else False,
    }


def web_login(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("home")

    context: Dict[str, Any] = {}
    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        user = authenticate(request, username=username, password=password)
        if user is None:
            context["error"] = i18n_tr("Неверный логин или пароль")
        else:
            login(request, user)
            return redirect("home")

    return render(request, "stats/login.html", context)


@login_required
@require_POST
def web_logout(request: HttpRequest) -> HttpResponse:
    logout(request)
    return redirect("web-login")


@login_required
def home(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    return render(request, "stats/home.html", _base_context(request))


@login_required
def report_summary_page(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    context = _base_context(request)
    context.update(summary_dataset(request))
    return render(request, "stats/reports/summary_page.html", context)


@login_required
def report_answered_page(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    context = _base_context(request)
    context.update(answered_dataset(request))
    return render(request, "stats/reports/answered_page.html", context)


@login_required
def report_unanswered_page(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    context = _base_context(request)
    context.update(unanswered_dataset(request))
    return render(request, "stats/reports/unanswered_page.html", context)


@login_required
def report_cdr_page(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    context = _base_context(request)
    context.update(cdr_dataset(request))
    return render(request, "stats/reports/cdr_page.html", context)


@login_required
def report_outbound_page(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    context = _base_context(request)
    context.update(outbound_dataset(request))
    return render(request, "stats/reports/outbound_page.html", context)


@login_required
def call_detail_page(request: HttpRequest, callid: str) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    if not _is_valid_callid(callid):
        raise Http404("Invalid callid")

    dataset = call_detail_dataset(callid)

    context = _base_context(request)
    context.update(dataset)
    context["notice"] = ""
    context["error"] = ""
    return render(request, "stats/reports/call_detail_page.html", context)


@login_required
@require_http_methods(["POST"])
def call_transcription_start(request: HttpRequest, callid: str) -> JsonResponse:
    from .models import CallTranscription

    if not _user_allowed(request):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)
    if not _is_valid_callid(callid):
        return JsonResponse({"ok": False, "error": "Invalid callid"}, status=400)

    payload = _transcription_status_payload(callid)
    if not payload.get("transcription_configured"):
        return JsonResponse({"ok": False, "error": i18n_tr("Сервис транскрибации не настроен")}, status=400)
    if not payload.get("has_recording"):
        return JsonResponse({"ok": False, "error": i18n_tr("Для этого звонка нет аудиозаписи")}, status=400)
    if payload.get("status") == CallTranscription.Status.PROCESSING:
        return JsonResponse({"ok": True, "status": CallTranscription.Status.PROCESSING, "message": i18n_tr("Распознавание уже выполняется")})

    transcription, _ = CallTranscription.objects.get_or_create(callid=callid)
    transcription.status = CallTranscription.Status.PROCESSING
    transcription.text = ""
    transcription.error_message = ""
    transcription.save(update_fields=["status", "text", "error_message", "updated_at"])

    worker = threading.Thread(target=_run_transcription_background, args=(callid,), daemon=True)
    worker.start()

    return JsonResponse(
        {
            "ok": True,
            "status": CallTranscription.Status.PROCESSING,
            "message": i18n_tr("Транскрипция запущена"),
        }
    )


@login_required
@require_http_methods(["GET"])
def call_transcription_status(request: HttpRequest, callid: str) -> JsonResponse:
    if not _user_allowed(request):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)
    if not _is_valid_callid(callid):
        return JsonResponse({"ok": False, "error": "Invalid callid"}, status=400)

    payload = _transcription_status_payload(callid)
    payload["ok"] = True
    return JsonResponse(payload)


@login_required
def realtime_page(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    context = _base_context(request)
    context.update(_build_ami_snapshot(request))
    return render(request, "stats/realtime_page.html", context)


@login_required
def realtime_oob_partial(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    return render(request, "stats/partials/realtime_oob.html", _build_ami_snapshot(request))


@login_required
def analytics_page(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    context = _base_context(request)
    context.update(analytics_dataset(request))
    return render(request, "stats/analytics_page.html", context)


@login_required
@require_http_methods(["POST"])
def track_product_event(request: HttpRequest) -> JsonResponse:
    from .models import ProductEvent

    if not _user_allowed(request):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)

    event_name = str(payload.get("event") or "").strip().lower()
    if event_name not in ALLOWED_PRODUCT_EVENTS:
        return JsonResponse({"ok": False, "error": "invalid_event"}, status=400)

    raw_meta = payload.get("meta")
    meta = raw_meta if isinstance(raw_meta, dict) else {}
    page = str(meta.get("page") or "").strip()[:64]
    source = str(meta.get("source") or "").strip()[:64]

    ProductEvent.objects.create(
        user=request.user,
        event_name=event_name,
        page=page,
        metadata={
            "source": source,
            "shared_token": str(meta.get("shared_token") or "")[:64],
        },
    )
    return JsonResponse({"ok": True})


@login_required
def payouts_page(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    context = _base_context(request)
    context.update(payout_dataset(request))
    return render(request, "stats/payouts_page.html", context)


@login_required
def dashboards_page(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    return render(request, "stats/dashboards/index_page.html", _base_context(request))


@login_required
def dashboard_traffic_page(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    context = _base_context(request)
    context.update(dashboard_traffic_dataset(request))
    return render(request, "stats/dashboards/traffic_page.html", context)


@login_required
def dashboard_queues_page(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    context = _base_context(request)
    context.update(dashboard_queues_dataset(request))
    return render(request, "stats/dashboards/queues_page.html", context)


@login_required
def dashboard_operators_page(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    context = _base_context(request)
    context.update(dashboard_operators_dataset(request))
    return render(request, "stats/dashboards/operators_page.html", context)


@login_required
def settings_page(request: HttpRequest) -> HttpResponse:
    if not _admin_allowed(request):
        return HttpResponse("forbidden", status=403)

    settings_obj = _get_general_settings()
    notice = ""
    if request.method == "POST":
        action = request.POST.get("action", "save")
        section = request.POST.get("section", "")
        mapping_type = request.POST.get("mapping_type", "")
        system_name = (request.POST.get("system_name") or "").strip()
        display_name = (request.POST.get("display_name") or "").strip()

        if section == "general":
            settings_obj.currency_code = (request.POST.get("currency_code") or settings_obj.currency_code or "UZS").strip().upper()
            settings_obj.ui_language = (request.POST.get("ui_language") or settings_obj.ui_language or "ru").strip().lower()
            settings_obj.default_payout_rate_per_minute = request.POST.get("default_payout_rate_per_minute") or settings_obj.default_payout_rate_per_minute
            settings_obj.sla_target_percent = request.POST.get("sla_target_percent") or settings_obj.sla_target_percent
            settings_obj.sla_target_wait_seconds = request.POST.get("sla_target_wait_seconds") or settings_obj.sla_target_wait_seconds
            settings_obj.transcription_url = (request.POST.get("transcription_url") or settings_obj.transcription_url or "").strip()
            settings_obj.transcription_api_key = (request.POST.get("transcription_api_key") or settings_obj.transcription_api_key or "").strip()

            start_raw = (request.POST.get("business_day_start") or "").strip()
            end_raw = (request.POST.get("business_day_end") or "").strip()
            if start_raw:
                try:
                    settings_obj.business_day_start = datetime.strptime(start_raw, "%H:%M").time()
                except ValueError:
                    pass
            if end_raw:
                try:
                    settings_obj.business_day_end = datetime.strptime(end_raw, "%H:%M").time()
                except ValueError:
                    pass

            settings_obj.save()
            notice = i18n_tr("Общие настройки сохранены")
        elif mapping_type == "queue" and system_name:
            if action == "delete":
                QueueDisplayMapping.objects.filter(queue_system_name=system_name).delete()
                notice = i18n_tr("Маппинг очереди удалён")
            elif display_name:
                QueueDisplayMapping.objects.update_or_create(
                    queue_system_name=system_name,
                    defaults={"queue_display_name": display_name},
                )
                notice = i18n_tr("Маппинг очереди сохранён")
        elif mapping_type == "agent" and system_name:
            if action == "delete":
                AgentDisplayMapping.objects.filter(agent_system_name=system_name).delete()
                notice = i18n_tr("Маппинг оператора удалён")
            elif display_name:
                AgentDisplayMapping.objects.update_or_create(
                    agent_system_name=system_name,
                    defaults={"agent_display_name": display_name},
                )
                notice = i18n_tr("Маппинг оператора сохранён")
        elif mapping_type == "rate" and system_name:
            if action == "delete":
                OperatorPayoutRate.objects.filter(agent_system_name=system_name).delete()
                notice = i18n_tr("Ставка оператора удалена")
            else:
                rate_value = request.POST.get("rate_per_minute", "0").strip()
                try:
                    rate = float(rate_value)
                except ValueError:
                    rate = 0.0
                OperatorPayoutRate.objects.update_or_create(
                    agent_system_name=system_name,
                    defaults={"rate_per_minute": rate},
                )
                notice = i18n_tr("Ставка оператора сохранена")

    query = (request.GET.get("q") or "").strip()
    queue_qs = QueueDisplayMapping.objects.all()
    agent_qs = AgentDisplayMapping.objects.all()
    payout_qs = OperatorPayoutRate.objects.all()
    if query:
        queue_qs = queue_qs.filter(queue_system_name__icontains=query) | queue_qs.filter(queue_display_name__icontains=query)
        agent_qs = agent_qs.filter(agent_system_name__icontains=query) | agent_qs.filter(agent_display_name__icontains=query)
        payout_qs = payout_qs.filter(agent_system_name__icontains=query)

    queues = _get_available_queues()
    agents = _get_available_agents()
    qmap = _queue_map()
    queue_options = [{"value": q, "label": _display_queue(q, qmap)} for q in queues]

    context = _base_context(request)
    payout_rows = []
    amap = _agent_map()
    agent_options = []
    for item in agents:
        agent_system = str(item.get("agent") or "")
        agent_name = str(item.get("name") or "").strip()
        agent_display = _display_agent(agent_system, amap)
        if agent_display != agent_system:
            label = f"{agent_display} ({agent_system})"
        elif agent_name and agent_name != agent_system:
            label = f"{agent_system} ({agent_name})"
        else:
            label = agent_system
        agent_options.append({"value": agent_system, "label": label})

    for row in payout_qs:
        agent_system_name = str(row.agent_system_name or "")
        payout_rows.append(
            {
                "agent_system_name": agent_system_name,
                "agent_display_name": _display_agent(agent_system_name, amap),
                "rate_per_minute": row.rate_per_minute,
            }
        )

    context.update(
        {
            "notice": notice,
            "settings_obj": settings_obj,
            "language_choices": [("uz", "uz"), ("ru", "ru"), ("en", "en")],
            "currency_choices": ["UZS", "USD", "RUB", "EUR"],
            "selected_query": query,
            "queue_options": queue_options,
            "agent_options": agent_options,
            "queue_mappings": queue_qs,
            "agent_mappings": agent_qs,
            "payout_rates": payout_rows,
        }
    )
    return render(request, "stats/settings_page.html", context)


@login_required
def mappings_page(request: HttpRequest) -> HttpResponse:
    return redirect("settings-page")


@login_required
@require_http_methods(["GET", "POST"])
def blacklist_page(request: HttpRequest) -> HttpResponse:
    if not _admin_allowed(request):
        return HttpResponse("forbidden", status=403)

    notice = ""
    error = ""
    if request.method == "POST":
        notice, error = _handle_blacklist_post(request)

    blacklist_query = _normalize_blacklist_number((request.GET.get("bq") or "").strip())
    blacklist_data = _blacklist_list(blacklist_query)
    if blacklist_data.get("error") and not error:
        error = str(blacklist_data.get("error"))

    context = _base_context(request)
    context.update(
        {
            "notice": notice,
            "error": error,
            "blacklist_query": blacklist_query,
            "blacklist_rows": blacklist_data.get("rows", []),
            "blacklist_db_path": blacklist_data.get("db_path", ""),
        }
    )
    return render(request, "stats/blacklist_page.html", context)





@login_required
def recording_stream(request: HttpRequest, uniqueid: str) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)

    if not uniqueid or not all(c.isalnum() or c in ".-" for c in uniqueid):
        raise Http404("Invalid uniqueid")

    has_cdr_recording_path = True
    try:
        recording_path = _recording_file_by_uniqueid(uniqueid)
    except Http404:
        # Some CDR rows may miss recordingfile, but the file can still exist by uniqueid pattern.
        recording_path = uniqueid
        has_cdr_recording_path = False

    local_path = _resolve_recording_local_path(recording_path)
    if local_path:
        file_size = local_path.stat().st_size
        content_type, _ = mimetypes.guess_type(str(local_path))
        content_type = content_type or "audio/wav"
        range_header = request.headers.get("Range") or request.META.get("HTTP_RANGE", "")
        byte_range = _parse_range_header(range_header, file_size)
        if byte_range:
            start, end = byte_range
            response = StreamingHttpResponse(
                _stream_file_range(local_path, start, end),
                status=206,
                content_type=content_type,
            )
            response["Content-Range"] = f"bytes {start}-{end}/{file_size}"
            response["Content-Length"] = str(end - start + 1)
        else:
            response = FileResponse(local_path.open("rb"), content_type=content_type)
            response["Content-Length"] = str(file_size)
        response["Accept-Ranges"] = "bytes"
        response["Content-Disposition"] = f'inline; filename="{os.path.basename(str(local_path))}"'
        response["Cache-Control"] = "no-store"
        return response

    conf = GeneralSettings.objects.first()
    if has_cdr_recording_path and conf and conf.download_url:
        params = {"url": recording_path, "token": conf.download_token}
        auth = (conf.download_user, conf.download_password)
        headers = {}
        if request.headers.get("Range"):
            headers["Range"] = request.headers["Range"]
        try:
            upstream = requests.get(
                conf.download_url,
                params=params,
                auth=auth,
                headers=headers,
                stream=True,
                timeout=(5, 30),
            )
            upstream.raise_for_status()
        except requests.RequestException as exc:
            raise Http404(f"Failed to fetch recording: {exc}")

        response = StreamingHttpResponse(
            upstream.iter_content(chunk_size=8192),
            content_type=upstream.headers.get("Content-Type", "audio/mpeg"),
            status=upstream.status_code,
            reason=upstream.reason,
        )
        for key in ("Content-Length", "Content-Range", "Accept-Ranges"):
            if upstream.headers.get(key):
                response[key] = upstream.headers[key]
        response["Content-Disposition"] = f'inline; filename="{uniqueid}.wav"'
        response["Cache-Control"] = "no-store"
        return response

    raise Http404("Recording not available")
