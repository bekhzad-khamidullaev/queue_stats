from __future__ import annotations

import mimetypes
import os
import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List

import requests
from django.conf import settings as django_settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import connections
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from accounts.models import UserRoles
from settings.models import AgentDisplayMapping, GeneralSettings, OperatorPayoutRate, QueueDisplayMapping
from .ami_manager import AMIManager
from .i18n_map import tr as i18n_tr
from .views import _fetch_queuelog_rows, _normalize_list, _parse_datetime

_AGENT_EXT_RE = re.compile(r"\b([0-9]{3,6})\b")


def _user_allowed(request: HttpRequest) -> bool:
    return request.user.is_authenticated and request.user.role in {
        UserRoles.ADMIN,
        UserRoles.SUPERVISOR,
        UserRoles.ANALYST,
        UserRoles.AGENT,
    }


def _admin_allowed(request: HttpRequest) -> bool:
    return request.user.is_authenticated and request.user.role == UserRoles.ADMIN


def _interval_from_request(request: HttpRequest) -> tuple[datetime, datetime]:
    start = _parse_datetime(request.GET.get("start"))
    end = _parse_datetime(request.GET.get("end"))
    if not end:
        end = datetime.now().replace(hour=23, minute=59, second=59)
    if not start:
        start = end.replace(hour=0, minute=0, second=0)
    return start, end


def _get_param_list(request: HttpRequest, key: str) -> List[str]:
    raw_items = request.GET.getlist(key)
    parsed: List[str] = []
    if raw_items:
        for item in raw_items:
            parsed.extend(_normalize_list(item))
    else:
        parsed.extend(_normalize_list(request.GET.get(key)))

    unique: List[str] = []
    for item in parsed:
        if item not in unique:
            unique.append(item)
    return unique


def _queue_map() -> Dict[str, str]:
    return {item.queue_system_name: item.queue_display_name for item in QueueDisplayMapping.objects.all()}


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
    amap: Dict[str, str] = {}
    for item in AgentDisplayMapping.objects.all():
        display = item.agent_display_name
        for key in _agent_aliases(item.agent_system_name):
            amap.setdefault(key, display)
    return amap


def _is_valid_agent_value(value: str) -> bool:
    v = (value or "").strip()
    if len(v) < 2:
        return False
    return any(ch.isdigit() for ch in v) or any(ch.isalpha() for ch in v)


def _display_queue(value: str, qmap: Dict[str, str]) -> str:
    return qmap.get(value, value)


def _display_agent(value: str, amap: Dict[str, str]) -> str:
    for key in _agent_aliases(value):
        if key in amap:
            return amap[key]
    aliases = _agent_aliases(value)
    return aliases[-1] if aliases else value


def _human_party(value: str, amap: Dict[str, str]) -> str:
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


def _get_available_queues() -> List[str]:
    queues: List[str] = []
    with connections["default"].cursor() as cursor:
        try:
            cursor.execute("SELECT DISTINCT queuename FROM queues_new WHERE queuename IS NOT NULL AND queuename <> '' ORDER BY queuename")
            queues.extend([str(row[0]).strip() for row in cursor.fetchall()])
        except Exception:
            pass
        if not _unique_non_empty(queues):
            try:
                cursor.execute("SELECT DISTINCT queuename FROM queuelog WHERE queuename IS NOT NULL AND queuename <> '' ORDER BY queuename")
                queues.extend([str(row[0]).strip() for row in cursor.fetchall()])
            except Exception:
                pass

    queues.extend(list(QueueDisplayMapping.objects.values_list("queue_system_name", flat=True)))
    return _unique_non_empty(queues)


def _get_available_agents() -> List[Dict[str, str]]:
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
        except Exception:
            pass

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
            except Exception:
                pass

    for system_name in AgentDisplayMapping.objects.values_list("agent_system_name", flat=True):
        _add_agent(str(system_name), "")
    return out


def _caller_map_by_callids(callids: List[str]) -> Dict[str, str]:
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


def _base_context(request: HttpRequest) -> Dict[str, Any]:
    now = datetime.now()
    selected_queues_list = _get_param_list(request, "queues")
    selected_agents_list = _get_param_list(request, "agents")
    return {
        "queues": _get_available_queues(),
        "agents": _get_available_agents(),
        "default_start": request.GET.get("start") or now.replace(hour=0, minute=0, second=0).strftime("%Y-%m-%d %H:%M:%S"),
        "default_end": request.GET.get("end") or now.replace(hour=23, minute=59, second=59).strftime("%Y-%m-%d %H:%M:%S"),
        "selected_queues": ",".join(selected_queues_list),
        "selected_agents": ",".join(selected_agents_list),
        "selected_queues_list": selected_queues_list,
        "selected_agents_list": selected_agents_list,
        "selected_src": request.GET.get("src", ""),
        "selected_dst": request.GET.get("dst", ""),
        "selected_disposition": request.GET.get("disposition", ""),
        "selected_channel": request.GET.get("channel", ""),
        "selected_caller": request.GET.get("caller", ""),
        "selected_query": request.GET.get("q", ""),
    }


def _get_general_settings() -> GeneralSettings:
    obj = GeneralSettings.objects.first()
    if obj:
        return obj
    return GeneralSettings.objects.create()


def _answered_dataset(request: HttpRequest) -> Dict[str, Any]:
    start, end = _interval_from_request(request)
    queues = _get_param_list(request, "queues")
    agents = _get_param_list(request, "agents")
    qmap = _queue_map()
    amap = _agent_map()

    rows = _fetch_queuelog_rows(start, end, queues, agents, ["COMPLETECALLER", "COMPLETEAGENT"])
    caller_map = _caller_map_by_callids([str(r.get("callid") or "") for r in rows])
    flat_rows: List[Dict[str, Any]] = []
    for row in rows:
        callid = str(row.get("callid") or "")
        queue = str(row.get("queuename") or "")
        agent = str(row.get("agent") or "")
        flat_rows.append(
            {
                "time": row.get("time"),
                "caller": caller_map.get(callid, ""),
                "queue": queue,
                "queue_display": _display_queue(queue, qmap),
                "agent": agent,
                "agent_display": _display_agent(agent, amap),
                "hold": int(row.get("data1") or 0),
                "talk": int(row.get("data2") or 0),
            }
        )

    total = len(flat_rows)
    avg_hold = round(sum(r["hold"] for r in flat_rows) / total, 2) if total else 0
    avg_talk = round(sum(r["talk"] for r in flat_rows) / total, 2) if total else 0
    return {
        "start": start,
        "end": end,
        "rows": flat_rows[:1000],
        "total": total,
        "avg_hold": avg_hold,
        "avg_talk": avg_talk,
    }


def _unanswered_dataset(request: HttpRequest) -> Dict[str, Any]:
    start, end = _interval_from_request(request)
    queues = _get_param_list(request, "queues")
    qmap = _queue_map()
    rows = _fetch_queuelog_rows(start, end, queues, None, ["ABANDON", "EXITWITHTIMEOUT"])
    caller_map = _caller_map_by_callids([str(r.get("callid") or "") for r in rows])

    flat_rows: List[Dict[str, Any]] = []
    for row in rows:
        callid = str(row.get("callid") or "")
        queue = str(row.get("queuename") or "")
        flat_rows.append(
            {
                "time": row.get("time"),
                "caller": caller_map.get(callid, ""),
                "queue": queue,
                "queue_display": _display_queue(queue, qmap),
                "event": row.get("event"),
                "start_pos": int(row.get("data2") or 0),
                "end_pos": int(row.get("data1") or 0),
                "wait_sec": int(row.get("data3") or 0),
            }
        )

    total = len(flat_rows)
    avg_wait = round(sum(r["wait_sec"] for r in flat_rows) / total, 2) if total else 0
    return {
        "start": start,
        "end": end,
        "rows": flat_rows[:1000],
        "total": total,
        "avg_wait": avg_wait,
    }


def _cdr_dataset(request: HttpRequest) -> Dict[str, Any]:
    start, end = _interval_from_request(request)
    agents = _get_param_list(request, "agents")
    src_filter = (request.GET.get("src") or "").strip()
    dst_filter = (request.GET.get("dst") or "").strip()
    disposition_filter = (request.GET.get("disposition") or "").strip()

    amap = _agent_map()
    qmap = _queue_map()
    sql = """
        SELECT
            c.uniqueid,
            c.calldate,
            c.src,
            c.dst,
            c.dcontext,
            c.dstchannel,
            c.lastapp,
            c.lastdata,
            c.cnum,
            c.cnam,
            c.duration,
            c.billsec,
            c.disposition,
            c.recordingfile,
            ql.agent AS queue_agent
        FROM cdr c
        LEFT JOIN (
            SELECT
                callid,
                SUBSTRING_INDEX(GROUP_CONCAT(agent ORDER BY time DESC SEPARATOR ','), ',', 1) AS agent
            FROM queuelog
            WHERE event IN ('CONNECT', 'COMPLETECALLER', 'COMPLETEAGENT')
              AND agent IS NOT NULL AND agent <> ''
            GROUP BY callid
        ) ql ON ql.callid = c.uniqueid
        WHERE calldate >= %s AND calldate <= %s
    """
    params: List[Any] = [start, end]

    if agents:
        sql += f" AND (cnam IN ({','.join(['%s'] * len(agents))}) OR cnum IN ({','.join(['%s'] * len(agents))}))"
        params.extend(agents)
        params.extend(agents)
    if src_filter:
        sql += " AND c.src LIKE %s"
        params.append(f"%{src_filter}%")
    if dst_filter:
        sql += " AND (c.dst LIKE %s OR c.dcontext LIKE %s OR c.lastdata LIKE %s)"
        params.append(f"%{dst_filter}%")
        params.append(f"%{dst_filter}%")
        params.append(f"%{dst_filter}%")
    if disposition_filter:
        sql += " AND c.disposition = %s"
        params.append(disposition_filter)

    sql += " ORDER BY c.calldate DESC LIMIT 5000"

    with connections["default"].cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description]
    data = [dict(zip(columns, row)) for row in rows]

    agent_filter_set = set()
    for raw in agents:
        for key in _agent_aliases(raw):
            agent_filter_set.add(key)

    for row in data:
        operator_system = str(row.get("queue_agent") or "")
        if not operator_system:
            operator_system = str(row.get("dstchannel") or "")
        row["operator_display"] = _display_agent(operator_system, amap)

        dst = str(row.get("dst") or "")
        if dst in {"", "s", "S"}:
            if str(row.get("lastapp") or "").lower() == "queue":
                queue_raw = str(row.get("lastdata") or "").split(",", 1)[0].strip()
                dst = _display_queue(queue_raw, qmap) if queue_raw else ""
            elif row.get("dcontext"):
                dst = _display_queue(str(row.get("dcontext") or ""), qmap)
        row["dst_display"] = dst or "-"

        row["has_recording"] = bool(row.get("recordingfile"))

    if agent_filter_set:
        filtered: List[Dict[str, Any]] = []
        for row in data:
            op = str(row.get("queue_agent") or row.get("dstchannel") or "")
            op_aliases = set(_agent_aliases(op))
            if op_aliases & agent_filter_set:
                filtered.append(row)
        data = filtered

    return {"start": start, "end": end, "rows": data[:1000], "total": len(data)}


def _summary_dataset(request: HttpRequest) -> Dict[str, Any]:
    start, end = _interval_from_request(request)
    queues = _get_param_list(request, "queues")
    agents = _get_param_list(request, "agents")
    qmap = _queue_map()

    rows = _fetch_queuelog_rows(
        start,
        end,
        queues,
        agents,
        ["COMPLETECALLER", "COMPLETEAGENT", "ABANDON", "EXITWITHTIMEOUT"],
    )

    answered = 0
    abandoned = 0
    timeout = 0
    wait_total = 0
    talk_total = 0
    by_queue: Dict[str, Dict[str, int]] = {}

    for row in rows:
        queue = str(row.get("queuename") or "UNKNOWN")
        by_queue.setdefault(queue, {"answered": 0, "unanswered": 0, "total": 0})
        event = str(row.get("event") or "")
        if event in {"COMPLETECALLER", "COMPLETEAGENT"}:
            answered += 1
            by_queue[queue]["answered"] += 1
            wait_total += int(row.get("data1") or 0)
            talk_total += int(row.get("data2") or 0)
        elif event == "ABANDON":
            abandoned += 1
            by_queue[queue]["unanswered"] += 1
        elif event == "EXITWITHTIMEOUT":
            timeout += 1
            by_queue[queue]["unanswered"] += 1
        by_queue[queue]["total"] += 1

    total = answered + abandoned + timeout
    per_queue = []
    for system_name, values in sorted(by_queue.items(), key=lambda item: item[0]):
        per_queue.append({"queue": system_name, "queue_display": _display_queue(system_name, qmap), **values})

    return {
        "start": start,
        "end": end,
        "total": total,
        "answered": answered,
        "abandoned": abandoned,
        "timeout": timeout,
        "service_level": round(answered * 100 / total, 2) if total else 0,
        "avg_wait": round(wait_total / answered, 2) if answered else 0,
        "avg_talk": round(talk_total / answered, 2) if answered else 0,
        "per_queue": per_queue,
    }


def _analytics_dataset(request: HttpRequest) -> Dict[str, Any]:
    start, end = _interval_from_request(request)
    queues = _get_param_list(request, "queues")
    agents = _get_param_list(request, "agents")
    qmap = _queue_map()
    amap = _agent_map()
    queue_clause = ""
    agent_clause = ""
    if queues:
        queue_clause = f" AND queuename IN ({','.join(['%s'] * len(queues))})"
    if agents:
        agent_clause = f" AND agent IN ({','.join(['%s'] * len(agents))})"

    queue_params: List[Any] = [start, end, *queues]
    queue_agent_params: List[Any] = [start, end, *queues, *agents]

    sql_daily = f"""
        SELECT DATE(time) AS day,
               SUM(CASE WHEN event IN ('COMPLETECALLER','COMPLETEAGENT') THEN 1 ELSE 0 END) AS answered,
               SUM(CASE WHEN event = 'ABANDON' THEN 1 ELSE 0 END) AS abandoned,
               SUM(CASE WHEN event = 'EXITWITHTIMEOUT' THEN 1 ELSE 0 END) AS timeout,
               SUM(CASE WHEN event IN ('ABANDON','EXITWITHTIMEOUT') THEN 1 ELSE 0 END) AS unanswered
        FROM queuelog
        WHERE time >= %s AND time <= %s {queue_clause}
        GROUP BY day
        ORDER BY day
    """

    sql_hourly = f"""
        SELECT HOUR(time) AS hour,
               SUM(CASE WHEN event IN ('COMPLETECALLER','COMPLETEAGENT') THEN 1 ELSE 0 END) AS answered,
               SUM(CASE WHEN event IN ('ABANDON','EXITWITHTIMEOUT') THEN 1 ELSE 0 END) AS unanswered
        FROM queuelog
        WHERE time >= %s AND time <= %s {queue_clause}
        GROUP BY hour
        ORDER BY hour
    """

    sql_queue = f"""
        SELECT queuename,
               SUM(CASE WHEN event IN ('COMPLETECALLER','COMPLETEAGENT') THEN 1 ELSE 0 END) AS answered,
               SUM(CASE WHEN event = 'ABANDON' THEN 1 ELSE 0 END) AS abandoned,
               SUM(CASE WHEN event = 'EXITWITHTIMEOUT' THEN 1 ELSE 0 END) AS timeout,
               SUM(CASE WHEN event IN ('COMPLETECALLER','COMPLETEAGENT') THEN CAST(data1 AS UNSIGNED) ELSE 0 END) AS hold_sec,
               SUM(CASE WHEN event IN ('COMPLETECALLER','COMPLETEAGENT') THEN CAST(data2 AS UNSIGNED) ELSE 0 END) AS talk_sec,
               SUM(CASE WHEN event IN ('ABANDON','EXITWITHTIMEOUT') THEN 1 ELSE 0 END) AS unanswered
        FROM queuelog
        WHERE time >= %s AND time <= %s {queue_clause}
        GROUP BY queuename
        ORDER BY answered DESC
        LIMIT 200
    """

    sql_agents = f"""
        SELECT agent,
               COUNT(*) AS answered,
               COUNT(DISTINCT queuename) AS queues_count,
               SUM(CAST(data1 AS UNSIGNED)) AS hold_sec,
               SUM(CAST(data2 AS UNSIGNED)) AS talk_sec
        FROM queuelog
        WHERE time >= %s AND time <= %s {queue_clause}
          AND event IN ('COMPLETECALLER','COMPLETEAGENT') {agent_clause}
          AND agent IS NOT NULL AND agent <> ''
        GROUP BY agent
        ORDER BY answered DESC
        LIMIT 200
    """

    with connections["default"].cursor() as cursor:
        cursor.execute(sql_daily, queue_params)
        daily = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]

        cursor.execute(sql_hourly, queue_params)
        hourly = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]

        cursor.execute(sql_queue, queue_params)
        per_queue = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]

        cursor.execute(sql_agents, queue_agent_params)
        top_agents = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]

    total_answered = sum(int(x.get("answered") or 0) for x in daily)
    total_abandoned = sum(int(x.get("abandoned") or 0) for x in daily)
    total_timeout = sum(int(x.get("timeout") or 0) for x in daily)
    total_unanswered = total_abandoned + total_timeout
    total_calls = total_answered + total_unanswered

    sum_hold_answered = sum(int(x.get("hold_sec") or 0) for x in per_queue)
    sum_talk_answered = sum(int(x.get("talk_sec") or 0) for x in per_queue)

    for row in per_queue:
        answered = int(row.get("answered") or 0)
        abandoned = int(row.get("abandoned") or 0)
        timeout = int(row.get("timeout") or 0)
        unanswered = int(row.get("unanswered") or 0)
        total = answered + unanswered
        hold_sec = int(row.get("hold_sec") or 0)
        talk_sec = int(row.get("talk_sec") or 0)

        row["queue_display"] = _display_queue(str(row.get("queuename") or ""), qmap)
        row["total_calls"] = total
        row["sla"] = round(answered * 100 / total, 2) if total else 0
        row["abandon_rate"] = round(abandoned * 100 / total, 2) if total else 0
        row["timeout_rate"] = round(timeout * 100 / total, 2) if total else 0
        row["avg_hold"] = round(hold_sec / answered, 2) if answered else 0
        row["avg_talk"] = round(talk_sec / answered, 2) if answered else 0
        row["aht"] = round((hold_sec + talk_sec) / answered, 2) if answered else 0

    for row in top_agents:
        agent = str(row.get("agent") or "")
        calls = int(row.get("answered") or 0)
        hold = int(row.get("hold_sec") or 0)
        talk = int(row.get("talk_sec") or 0)
        row["agent_display"] = _display_agent(agent, amap)
        row["avg_hold"] = round(hold / calls, 2) if calls else 0
        row["avg_talk"] = round(talk / calls, 2) if calls else 0
        row["aht"] = round((hold + talk) / calls, 2) if calls else 0
        row["talk_min"] = round(talk / 60, 2)
        row["share_answered"] = round(calls * 100 / total_answered, 2) if total_answered else 0

    daily_chart_input: List[Dict[str, Any]] = []
    for row in daily:
        daily_chart_input.append(
            {
                "day": row.get("day"),
                "total": int(row.get("answered") or 0) + int(row.get("unanswered") or 0),
            }
        )
    hourly_chart_input: List[Dict[str, Any]] = []
    for row in hourly:
        hourly_chart_input.append(
            {
                "hour": row.get("hour"),
                "total": int(row.get("answered") or 0) + int(row.get("unanswered") or 0),
            }
        )

    return {
        "start": start,
        "end": end,
        "kpi_total": total_calls,
        "kpi_answered": total_answered,
        "kpi_abandoned": total_abandoned,
        "kpi_timeout": total_timeout,
        "kpi_unanswered": total_unanswered,
        "kpi_sla": round(total_answered * 100 / total_calls, 2) if total_calls else 0,
        "kpi_abandon_rate": round(total_abandoned * 100 / total_calls, 2) if total_calls else 0,
        "kpi_timeout_rate": round(total_timeout * 100 / total_calls, 2) if total_calls else 0,
        "kpi_avg_hold": round(sum_hold_answered / total_answered, 2) if total_answered else 0,
        "kpi_avg_talk": round(sum_talk_answered / total_answered, 2) if total_answered else 0,
        "kpi_aht": round((sum_hold_answered + sum_talk_answered) / total_answered, 2) if total_answered else 0,
        "kpi_total_talk_min": round(sum_talk_answered / 60, 2),
        "kpi_active_queues": len([x for x in per_queue if int(x.get("total_calls") or 0) > 0]),
        "kpi_active_agents": len([x for x in top_agents if int(x.get("answered") or 0) > 0]),
        "daily": daily,
        "hourly": hourly,
        "per_queue": per_queue,
        "top_agents": top_agents,
        "daily_line_chart": _line_chart(daily_chart_input, "day", "total", max_items=31),
        "hourly_bar_chart": _bar_chart(hourly_chart_input, "hour", "total", max_items=24),
        "queue_calls_chart": _bar_chart(per_queue, "queue_display", "total_calls", max_items=16),
        "agent_answered_chart": _bar_chart(top_agents, "agent_display", "answered", max_items=16),
    }


def _payout_dataset(request: HttpRequest) -> Dict[str, Any]:
    start, end = _interval_from_request(request)
    queues = _get_param_list(request, "queues")
    agents = _get_param_list(request, "agents")
    qmap = _queue_map()
    amap = _agent_map()
    rate_map = _payout_rate_map()
    general = _get_general_settings()
    default_rate = Decimal(general.default_payout_rate_per_minute)
    currency_code = general.currency_code

    rows = _fetch_queuelog_rows(start, end, queues, agents, ["COMPLETECALLER", "COMPLETEAGENT"])

    by_agent: Dict[str, Dict[str, Any]] = {}
    by_queue: Dict[str, Dict[str, Any]] = {}
    total_talk_sec = 0
    total_payout = Decimal("0.00")

    for row in rows:
        agent_raw = str(row.get("agent") or "")
        queue_raw = str(row.get("queuename") or "")
        talk_sec = int(row.get("data2") or 0)
        if not agent_raw or talk_sec <= 0:
            continue

        aliases = _agent_aliases(agent_raw)
        agent_key = aliases[-1] if aliases else agent_raw
        rate = default_rate
        for key in aliases:
            if key in rate_map:
                rate = rate_map[key]
                break
        payout = ((Decimal(talk_sec) / Decimal("60")) * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        by_agent.setdefault(
            agent_key,
            {
                "agent": agent_key,
                "agent_display": _display_agent(agent_raw, amap),
                "calls": 0,
                "talk_sec": 0,
                "talk_min": Decimal("0.00"),
                "rate_per_minute": rate,
                "payout_total": Decimal("0.00"),
            },
        )
        by_agent[agent_key]["calls"] += 1
        by_agent[agent_key]["talk_sec"] += talk_sec
        by_agent[agent_key]["talk_min"] = (Decimal(by_agent[agent_key]["talk_sec"]) / Decimal("60")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        by_agent[agent_key]["rate_per_minute"] = rate
        by_agent[agent_key]["payout_total"] = (by_agent[agent_key]["payout_total"] + payout).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        queue_key = f"{queue_raw}::{agent_key}"
        by_queue.setdefault(
            queue_key,
            {
                "queue": queue_raw,
                "queue_display": _display_queue(queue_raw, qmap),
                "agent": agent_key,
                "agent_display": _display_agent(agent_raw, amap),
                "calls": 0,
                "talk_sec": 0,
                "talk_min": Decimal("0.00"),
                "rate_per_minute": rate,
                "payout_total": Decimal("0.00"),
            },
        )
        by_queue[queue_key]["calls"] += 1
        by_queue[queue_key]["talk_sec"] += talk_sec
        by_queue[queue_key]["talk_min"] = (Decimal(by_queue[queue_key]["talk_sec"]) / Decimal("60")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        by_queue[queue_key]["rate_per_minute"] = rate
        by_queue[queue_key]["payout_total"] = (by_queue[queue_key]["payout_total"] + payout).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        total_talk_sec += talk_sec
        total_payout += payout

    by_agent_rows = sorted(by_agent.values(), key=lambda x: x["payout_total"], reverse=True)
    by_queue_rows = sorted(by_queue.values(), key=lambda x: x["payout_total"], reverse=True)
    with_rate = len([x for x in by_agent_rows if x["rate_per_minute"] > 0])

    return {
        "start": start,
        "end": end,
        "rows_agent": by_agent_rows,
        "rows_queue": by_queue_rows,
        "total_calls": sum(int(x["calls"]) for x in by_agent_rows),
        "total_talk_min": (Decimal(total_talk_sec) / Decimal("60")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        "total_payout": total_payout.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        "agents_with_rate": with_rate,
        "agents_without_rate": max(0, len(by_agent_rows) - with_rate),
        "currency_code": currency_code,
        "default_payout_rate_per_minute": default_rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
    }


def _add_progress(rows: List[Dict[str, Any]], field: str, target: str = "bar_pct") -> List[Dict[str, Any]]:
    max_value = max([float(r.get(field) or 0) for r in rows], default=0.0)
    if max_value <= 0:
        for row in rows:
            row[target] = 0
        return rows
    for row in rows:
        row[target] = round((float(row.get(field) or 0) * 100.0) / max_value, 2)
    return rows


def _bar_chart(items: List[Dict[str, Any]], label_key: str, value_key: str, max_items: int = 16) -> Dict[str, Any]:
    src = items[:max_items]
    values = [float(x.get(value_key) or 0) for x in src]
    max_value = max(values, default=0.0) or 1.0
    count = max(1, len(src))
    width = 640
    height = 240
    pad = 28
    inner_w = width - (pad * 2)
    inner_h = height - (pad * 2)
    slot = inner_w / count
    bar_w = max(8, slot * 0.72)
    bars: List[Dict[str, Any]] = []
    for idx, item in enumerate(src):
        value = float(item.get(value_key) or 0)
        ratio = value / max_value
        h = ratio * inner_h
        x = pad + (idx * slot) + ((slot - bar_w) / 2)
        y = pad + inner_h - h
        bars.append(
            {
                "x": round(x, 2),
                "y": round(y, 2),
                "w": round(bar_w, 2),
                "h": round(h, 2),
                "label": str(item.get(label_key) or ""),
                "value": item.get(value_key) or 0,
            }
        )
    return {"w": width, "h": height, "bars": bars, "max_value": round(max_value, 2)}


def _line_chart(items: List[Dict[str, Any]], label_key: str, value_key: str, max_items: int = 30) -> Dict[str, Any]:
    src = items[:max_items]
    values = [float(x.get(value_key) or 0) for x in src]
    max_value = max(values, default=0.0) or 1.0
    count = max(2, len(src))
    width = 640
    height = 240
    pad = 28
    inner_w = width - (pad * 2)
    inner_h = height - (pad * 2)
    step = inner_w / max(1, count - 1)
    points: List[Dict[str, Any]] = []
    poly_parts: List[str] = []
    for idx, item in enumerate(src):
        value = float(item.get(value_key) or 0)
        ratio = value / max_value
        x = pad + (idx * step)
        y = pad + inner_h - (ratio * inner_h)
        points.append(
            {
                "x": round(x, 2),
                "y": round(y, 2),
                "label": str(item.get(label_key) or ""),
                "value": item.get(value_key) or 0,
            }
        )
        poly_parts.append(f"{round(x,2)},{round(y,2)}")
    return {
        "w": width,
        "h": height,
        "points": points,
        "polyline": " ".join(poly_parts),
        "max_value": round(max_value, 2),
    }


def _dashboard_traffic_dataset(request: HttpRequest) -> Dict[str, Any]:
    data = _analytics_dataset(request)
    daily = data.get("daily", [])
    hourly = data.get("hourly", [])
    for row in daily:
        row["total"] = int(row.get("answered") or 0) + int(row.get("unanswered") or 0)
    for row in hourly:
        row["total"] = int(row.get("answered") or 0) + int(row.get("unanswered") or 0)
    data["daily_line_chart"] = _line_chart(daily, "day", "total", max_items=31)
    data["hourly_bar_chart"] = _bar_chart(hourly, "hour", "total", max_items=24)
    data["daily"] = daily
    data["hourly"] = hourly
    return data


def _dashboard_queues_dataset(request: HttpRequest) -> Dict[str, Any]:
    data = _analytics_dataset(request)
    rows = data.get("per_queue", [])
    data["queues_calls_chart"] = _bar_chart(rows, "queue_display", "total_calls")
    data["queues_sla_chart"] = _bar_chart(rows, "queue_display", "sla")
    data["per_queue"] = rows
    return data


def _dashboard_operators_dataset(request: HttpRequest) -> Dict[str, Any]:
    analytics = _analytics_dataset(request)
    payouts = _payout_dataset(request)
    payout_map: Dict[str, Dict[str, Any]] = {str(r.get("agent")): r for r in payouts.get("rows_agent", [])}

    rows: List[Dict[str, Any]] = []
    for row in analytics.get("top_agents", []):
        aliases = _agent_aliases(str(row.get("agent") or ""))
        agent_key = aliases[-1] if aliases else str(row.get("agent") or "")
        pay = payout_map.get(agent_key, {})
        rows.append(
            {
                "agent": agent_key,
                "agent_display": row.get("agent_display"),
                "answered": int(row.get("answered") or 0),
                "talk_min": row.get("talk_min", 0),
                "avg_talk": row.get("avg_talk", 0),
                "aht": row.get("aht", 0),
                "share_answered": row.get("share_answered", 0),
                "rate_per_minute": pay.get("rate_per_minute", Decimal("0.00")),
                "payout_total": pay.get("payout_total", Decimal("0.00")),
            }
        )
    analytics["operators_talk_chart"] = _bar_chart(rows, "agent_display", "talk_min")
    analytics["operators_payout_chart"] = _bar_chart(rows, "agent_display", "payout_total")
    analytics["rows_operators"] = rows
    analytics["total_payout"] = payouts.get("total_payout", Decimal("0.00"))
    analytics["currency_code"] = payouts.get("currency_code", "UZS")
    return analytics


def _build_ami_snapshot(request: HttpRequest | None = None, filters: Dict[str, str] | None = None) -> Dict[str, Any]:
    def _filter_value(key: str) -> str:
        if request is not None:
            return request.GET.get(key, "")
        if filters is not None:
            return filters.get(key, "")
        return ""

    qmap = _queue_map()
    amap = _agent_map()
    if request is not None:
        queues_filter = set(_get_param_list(request, "queues"))
    else:
        queues_filter = set(_normalize_list(_filter_value("queues")))
    channel_filter = (_filter_value("channel") or "").strip().lower()
    caller_filter = (_filter_value("caller") or "").strip().lower()

    settings = GeneralSettings.objects.first()
    if not settings or not settings.ami_host:
        return {
            "queue_summary": [],
            "active_calls": [],
            "active_calls_count": 0,
            "waiting_calls_count": 0,
            "active_operators_count": 0,
            "ami_error": i18n_tr("AMI не настроен"),
        }

    manager = AMIManager(
        host=settings.ami_host,
        port=settings.ami_port,
        username=settings.ami_user,
        secret=settings.ami_password,
    )

    if not manager.connect():
        return {
            "queue_summary": [],
            "active_calls": [],
            "active_calls_count": 0,
            "waiting_calls_count": 0,
            "active_operators_count": 0,
            "ami_error": i18n_tr("Нет соединения с AMI"),
        }

    try:
        summary_raw = manager.queue_summary().get("summary", [])
        channels_raw = manager.core_show_channels().get("channels", [])
    finally:
        manager.disconnect()

    queue_summary: List[Dict[str, Any]] = []
    for row in summary_raw:
        if str(row.get("Event", "")) != "QueueSummary":
            continue
        queue_system = str(row.get("Queue", ""))
        if queues_filter and queue_system not in queues_filter:
            continue
        queue_summary.append(
            {
                "queue": queue_system,
                "queue_display": _display_queue(queue_system, qmap),
                "logged_in": row.get("LoggedIn", "0"),
                "available": row.get("Available", "0"),
                "callers": row.get("Callers", "0"),
                "hold_time": row.get("HoldTime", "0"),
                "longest_hold": row.get("LongestHoldTime", "0"),
            }
        )

    deduped_channels: Dict[str, Dict[str, Any]] = {}
    fallback_idx = 0
    for row in channels_raw:
        if str(row.get("Event", "")) != "CoreShowChannel":
            continue
        channel = str(row.get("Channel", ""))
        if channel.startswith("Message/"):
            continue
        linkedid = str(row.get("Linkedid") or row.get("LinkedId") or "").strip()
        bridge_id = str(row.get("BridgeId") or row.get("BridgeID") or row.get("BridgeUniqueid") or "").strip()
        dedupe_key = linkedid or bridge_id
        if not dedupe_key:
            fallback_idx += 1
            dedupe_key = f"row:{fallback_idx}:{channel}"

        current = deduped_channels.get(dedupe_key)
        if current is None or _channel_row_rank(row) > _channel_row_rank(current):
            deduped_channels[dedupe_key] = row

    active_calls: List[Dict[str, Any]] = []
    active_operator_ids = set()
    for row in deduped_channels.values():
        channel = str(row.get("Channel", ""))
        caller = str(row.get("CallerIDNum", ""))
        connected = str(row.get("ConnectedLineNum", ""))
        if channel_filter and channel_filter not in channel.lower():
            continue
        caller_human = _human_party(caller, amap)
        connected_human = _human_party(connected, amap)
        haystack = " ".join([caller, connected, caller_human, connected_human]).lower()
        if caller_filter and caller_filter not in haystack:
            continue
        active_calls.append(
            {
                "channel": _human_channel(channel, amap),
                "caller": caller_human,
                "connected": connected_human,
                "duration": row.get("Duration", ""),
                "application": row.get("Application", ""),
            }
        )
        for candidate in (channel, caller, connected):
            ext = _extract_operator_ext(candidate)
            if ext:
                active_operator_ids.add(ext)

    waiting_calls_total = 0
    for row in queue_summary:
        try:
            waiting_calls_total += int(row.get("callers") or 0)
        except (TypeError, ValueError):
            continue

    return {
        "queue_summary": queue_summary,
        "active_calls": active_calls,
        "active_calls_count": len(active_calls),
        "waiting_calls_count": waiting_calls_total,
        "active_operators_count": len(active_operator_ids),
        "ami_error": "",
    }


def _draw_table_pdf(title: str, headers: List[str], rows: List[List[Any]]) -> bytes:
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=landscape(A4))
    page_width, page_height = landscape(A4)

    pdf.setFillColor(colors.HexColor("#111827"))
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(12 * mm, page_height - 12 * mm, title)

    y = page_height - 24 * mm
    x = 10 * mm
    col_width = (page_width - 20 * mm) / max(1, len(headers))

    pdf.setFillColor(colors.HexColor("#1F2937"))
    pdf.rect(x, y, page_width - 20 * mm, 8 * mm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 8)
    for i, header in enumerate(headers):
        pdf.drawString(x + (i * col_width) + 1.5 * mm, y + 2.5 * mm, str(header)[:30])

    y -= 7 * mm
    pdf.setFont("Helvetica", 7)
    pdf.setFillColor(colors.black)
    for row in rows[:180]:
        if y < 12 * mm:
            pdf.showPage()
            y = page_height - 14 * mm
            pdf.setFont("Helvetica", 7)
        for i, value in enumerate(row):
            pdf.drawString(x + (i * col_width) + 1.5 * mm, y, str(value)[:30])
        y -= 5 * mm

    pdf.save()
    output.seek(0)
    return output.read()


def _draw_bar_plot_on_canvas(pdf, title: str, x: float, y: float, w: float, h: float, labels: List[str], values: List[float]) -> None:
    pdf.setStrokeColor(colors.HexColor("#334155"))
    pdf.setFillColor(colors.HexColor("#0B1220"))
    pdf.rect(x, y, w, h, fill=1, stroke=1)
    pdf.setFillColor(colors.HexColor("#CBD5E1"))
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(x + 4, y + h - 11, title[:80])

    if not values:
        pdf.setFont("Helvetica", 8)
        pdf.drawString(x + 4, y + 6, "No data")
        return

    pad = 8
    inner_x = x + pad
    inner_y = y + 18
    inner_w = w - (pad * 2)
    inner_h = h - 28
    max_val = max(values) if max(values) > 0 else 1
    count = max(1, len(values))
    slot = inner_w / count
    bar_w = max(3, slot * 0.68)

    pdf.setFillColor(colors.HexColor("#60A5FA"))
    for idx, value in enumerate(values):
        bar_h = (value / max_val) * inner_h
        bx = inner_x + (idx * slot) + ((slot - bar_w) / 2)
        by = inner_y
        pdf.rect(bx, by, bar_w, bar_h, fill=1, stroke=0)

    pdf.setFillColor(colors.HexColor("#94A3B8"))
    pdf.setFont("Helvetica", 6)
    max_labels = min(len(labels), 10)
    step = max(1, len(labels) // max_labels)
    for idx in range(0, len(labels), step):
        lx = inner_x + (idx * slot)
        pdf.drawString(lx, y + 4, str(labels[idx])[:8])


def _draw_line_plot_on_canvas(pdf, title: str, x: float, y: float, w: float, h: float, labels: List[str], values: List[float]) -> None:
    pdf.setStrokeColor(colors.HexColor("#334155"))
    pdf.setFillColor(colors.HexColor("#0B1220"))
    pdf.rect(x, y, w, h, fill=1, stroke=1)
    pdf.setFillColor(colors.HexColor("#CBD5E1"))
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(x + 4, y + h - 11, title[:80])

    if not values:
        pdf.setFont("Helvetica", 8)
        pdf.drawString(x + 4, y + 6, "No data")
        return

    pad = 10
    inner_x = x + pad
    inner_y = y + 18
    inner_w = w - (pad * 2)
    inner_h = h - 28
    max_val = max(values) if max(values) > 0 else 1
    count = max(2, len(values))
    step_x = inner_w / max(1, count - 1)
    points = []
    for idx, value in enumerate(values):
        px = inner_x + (idx * step_x)
        py = inner_y + ((value / max_val) * inner_h)
        points.append((px, py))

    pdf.setStrokeColor(colors.HexColor("#22D3EE"))
    pdf.setLineWidth(1.5)
    for idx in range(len(points) - 1):
        x1, y1 = points[idx]
        x2, y2 = points[idx + 1]
        pdf.line(x1, y1, x2, y2)
    pdf.setFillColor(colors.HexColor("#38BDF8"))
    for px, py in points:
        pdf.circle(px, py, 1.7, fill=1, stroke=0)

    pdf.setFillColor(colors.HexColor("#94A3B8"))
    pdf.setFont("Helvetica", 6)
    max_labels = min(len(labels), 10)
    step = max(1, len(labels) // max_labels)
    for idx in range(0, len(labels), step):
        lx = inner_x + (idx * step_x)
        pdf.drawString(lx, y + 4, str(labels[idx])[:8])


def _draw_plots_pdf(title: str, plots: List[Dict[str, Any]]) -> bytes:
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=landscape(A4))
    page_w, page_h = landscape(A4)
    pdf.setFillColor(colors.HexColor("#111827"))
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(12 * mm, page_h - 12 * mm, title[:120])

    margin = 10 * mm
    gap = 6 * mm
    plot_w = (page_w - (margin * 2) - gap) / 2
    plot_h = (page_h - (margin * 2) - 18 * mm - gap) / 2
    base_y = margin
    top_y = base_y + plot_h + gap

    positions = [
        (margin, top_y),
        (margin + plot_w + gap, top_y),
        (margin, base_y),
        (margin + plot_w + gap, base_y),
    ]

    for idx, plot in enumerate(plots[:4]):
        x, y = positions[idx]
        labels = [str(x) for x in plot.get("labels", [])]
        values = [float(x or 0) for x in plot.get("values", [])]
        if plot.get("type") == "line":
            _draw_line_plot_on_canvas(pdf, plot.get("title", "Plot"), x, y, plot_w, plot_h, labels, values)
        else:
            _draw_bar_plot_on_canvas(pdf, plot.get("title", "Plot"), x, y, plot_w, plot_h, labels, values)

    pdf.save()
    output.seek(0)
    return output.read()


def _recording_file_by_uniqueid(uniqueid: str) -> str:
    with connections["default"].cursor() as cursor:
        cursor.execute("SELECT recordingfile FROM cdr WHERE uniqueid = %s", [uniqueid])
        row = cursor.fetchone()
    if not row or not row[0]:
        raise Http404("Recording not found")
    return str(row[0])


def _resolve_recording_local_path(recording_path: str) -> Path | None:
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
        except Exception:
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
    context.update(_summary_dataset(request))
    return render(request, "stats/reports/summary_page.html", context)


@login_required
def report_answered_page(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    context = _base_context(request)
    context.update(_answered_dataset(request))
    return render(request, "stats/reports/answered_page.html", context)


@login_required
def report_unanswered_page(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    context = _base_context(request)
    context.update(_unanswered_dataset(request))
    return render(request, "stats/reports/unanswered_page.html", context)


@login_required
def report_cdr_page(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    context = _base_context(request)
    context.update(_cdr_dataset(request))
    return render(request, "stats/reports/cdr_page.html", context)


@login_required
def realtime_page(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    context = _base_context(request)
    context.update(_build_ami_snapshot(request))
    return render(request, "stats/realtime_page.html", context)


@login_required
def analytics_page(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    context = _base_context(request)
    context.update(_analytics_dataset(request))
    return render(request, "stats/analytics_page.html", context)


@login_required
def payouts_page(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    context = _base_context(request)
    context.update(_payout_dataset(request))
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
    context.update(_dashboard_traffic_dataset(request))
    return render(request, "stats/dashboards/traffic_page.html", context)


@login_required
def dashboard_queues_page(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    context = _base_context(request)
    context.update(_dashboard_queues_dataset(request))
    return render(request, "stats/dashboards/queues_page.html", context)


@login_required
def dashboard_operators_page(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    context = _base_context(request)
    context.update(_dashboard_operators_dataset(request))
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

    context = _base_context(request)
    context.update(
        {
            "notice": notice,
            "settings_obj": settings_obj,
            "language_choices": [("uz", "uz"), ("ru", "ru"), ("en", "en")],
            "currency_choices": ["UZS", "USD", "RUB", "EUR"],
            "queue_mappings": queue_qs,
            "agent_mappings": agent_qs,
            "payout_rates": payout_qs,
        }
    )
    return render(request, "stats/settings_page.html", context)


@login_required
def mappings_page(request: HttpRequest) -> HttpResponse:
    return redirect("settings-page")


@login_required
def recording_stream(request: HttpRequest, uniqueid: str) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)

    if not uniqueid or not all(c.isalnum() or c in ".-" for c in uniqueid):
        raise Http404("Invalid uniqueid")

    recording_path = _recording_file_by_uniqueid(uniqueid)
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
    if conf and conf.download_url:
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


@login_required
def export_answered_excel(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)

    data = _answered_dataset(request)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Answered"
    sheet.append(["time", "caller", "queue", "agent", "hold_sec", "talk_sec"])
    for row in data["rows"]:
        sheet.append([row["time"], row.get("caller", ""), row["queue_display"], row["agent_display"], row["hold"], row["talk"]])

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    response = HttpResponse(output.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="answered_report.xlsx"'
    return response


@login_required
def export_unanswered_excel(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)

    data = _unanswered_dataset(request)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Unanswered"
    sheet.append(["time", "caller", "queue", "event", "start_pos", "end_pos", "wait_sec"])
    for row in data["rows"]:
        sheet.append(
            [
                row["time"],
                row.get("caller", ""),
                row["queue_display"],
                row["event"],
                row["start_pos"],
                row["end_pos"],
                row["wait_sec"],
            ]
        )

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    response = HttpResponse(output.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="unanswered_report.xlsx"'
    return response


@login_required
def export_cdr_excel(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)

    data = _cdr_dataset(request)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "CDR"
    sheet.append(["uniqueid", "calldate", "operator", "src", "dst", "duration", "billsec", "disposition", "recordingfile"])
    for row in data["rows"]:
        sheet.append(
            [
                row.get("uniqueid"),
                row.get("calldate"),
                row.get("operator_display"),
                row.get("src"),
                row.get("dst_display"),
                row.get("duration"),
                row.get("billsec"),
                row.get("disposition"),
                row.get("recordingfile"),
            ]
        )

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    response = HttpResponse(output.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="cdr_report.xlsx"'
    return response


@login_required
def export_answered_pdf(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)

    data = _answered_dataset(request)
    pdf_data = _draw_table_pdf(
        "Answered Report",
        ["time", "caller", "queue", "agent", "hold_sec", "talk_sec"],
        [[r["time"], r.get("caller", ""), r["queue_display"], r["agent_display"], r["hold"], r["talk"]] for r in data["rows"]],
    )
    response = HttpResponse(pdf_data, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="answered_report.pdf"'
    return response


@login_required
def export_unanswered_pdf(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)

    data = _unanswered_dataset(request)
    pdf_data = _draw_table_pdf(
        "Unanswered Report",
        ["time", "caller", "queue", "event", "start_pos", "end_pos", "wait_sec"],
        [[r["time"], r.get("caller", ""), r["queue_display"], r["event"], r["start_pos"], r["end_pos"], r["wait_sec"]] for r in data["rows"]],
    )
    response = HttpResponse(pdf_data, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="unanswered_report.pdf"'
    return response


@login_required
def export_cdr_pdf(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)

    data = _cdr_dataset(request)
    pdf_data = _draw_table_pdf(
        "CDR Report",
        ["uniqueid", "calldate", "operator", "src", "dst", "duration", "billsec", "disp"],
        [
            [
                r.get("uniqueid"),
                r.get("calldate"),
                r.get("operator_display"),
                r.get("src"),
                r.get("dst_display"),
                r.get("duration"),
                r.get("billsec"),
                r.get("disposition"),
            ]
            for r in data["rows"]
        ],
    )
    response = HttpResponse(pdf_data, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="cdr_report.pdf"'
    return response


@login_required
def export_dashboard_traffic_excel(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    data = _dashboard_traffic_dataset(request)
    workbook = Workbook()
    daily = workbook.active
    daily.title = "Daily"
    daily.append(["day", "answered", "unanswered", "total"])
    for row in data["daily"]:
        daily.append([row.get("day"), row.get("answered"), row.get("unanswered"), row.get("total")])

    hourly = workbook.create_sheet("Hourly")
    hourly.append(["hour", "answered", "unanswered", "total"])
    for row in data["hourly"]:
        hourly.append([row.get("hour"), row.get("answered"), row.get("unanswered"), row.get("total")])

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    response = HttpResponse(output.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="dashboard_traffic.xlsx"'
    return response


@login_required
def export_dashboard_queues_excel(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    data = _dashboard_queues_dataset(request)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Queues KPI"
    sheet.append(["queue", "total", "answered", "unanswered", "sla", "abandon_rate", "timeout_rate", "avg_hold", "avg_talk", "aht"])
    for row in data["per_queue"]:
        sheet.append(
            [
                row.get("queue_display"),
                row.get("total_calls"),
                row.get("answered"),
                row.get("unanswered"),
                row.get("sla"),
                row.get("abandon_rate"),
                row.get("timeout_rate"),
                row.get("avg_hold"),
                row.get("avg_talk"),
                row.get("aht"),
            ]
        )

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    response = HttpResponse(output.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="dashboard_queues.xlsx"'
    return response


@login_required
def export_dashboard_operators_excel(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    data = _dashboard_operators_dataset(request)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Operators KPI"
    sheet.append(["operator", "answered", "talk_min", "avg_talk", "aht", "share_answered", "rate_per_minute", "payout_total"])
    for row in data["rows_operators"]:
        sheet.append(
            [
                row.get("agent_display"),
                row.get("answered"),
                row.get("talk_min"),
                row.get("avg_talk"),
                row.get("aht"),
                row.get("share_answered"),
                row.get("rate_per_minute"),
                row.get("payout_total"),
            ]
        )

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    response = HttpResponse(output.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="dashboard_operators.xlsx"'
    return response


@login_required
def export_dashboard_traffic_pdf(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    data = _dashboard_traffic_dataset(request)
    plots = [
        {
            "type": "line",
            "title": "Daily total",
            "labels": [r.get("day") for r in data["daily"]],
            "values": [r.get("total") for r in data["daily"]],
        },
        {
            "type": "bar",
            "title": "Hourly total",
            "labels": [r.get("hour") for r in data["hourly"]],
            "values": [r.get("total") for r in data["hourly"]],
        },
    ]
    pdf_data = _draw_plots_pdf(
        "Dashboard Traffic Plots",
        plots,
    )
    response = HttpResponse(pdf_data, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="dashboard_traffic.pdf"'
    return response


@login_required
def export_dashboard_queues_pdf(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    data = _dashboard_queues_dataset(request)
    plots = [
        {
            "type": "bar",
            "title": "Calls per queue",
            "labels": [r.get("queue_display") for r in data["per_queue"][:16]],
            "values": [r.get("total_calls") for r in data["per_queue"][:16]],
        },
        {
            "type": "bar",
            "title": "SLA per queue",
            "labels": [r.get("queue_display") for r in data["per_queue"][:16]],
            "values": [r.get("sla") for r in data["per_queue"][:16]],
        },
    ]
    pdf_data = _draw_plots_pdf(
        "Dashboard Queues Plots",
        plots,
    )
    response = HttpResponse(pdf_data, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="dashboard_queues.pdf"'
    return response


@login_required
def export_dashboard_operators_pdf(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    data = _dashboard_operators_dataset(request)
    plots = [
        {
            "type": "bar",
            "title": "Talk minutes per operator",
            "labels": [r.get("agent_display") for r in data["rows_operators"][:16]],
            "values": [r.get("talk_min") for r in data["rows_operators"][:16]],
        },
        {
            "type": "bar",
            "title": "Payout per operator",
            "labels": [r.get("agent_display") for r in data["rows_operators"][:16]],
            "values": [r.get("payout_total") for r in data["rows_operators"][:16]],
        },
    ]
    pdf_data = _draw_plots_pdf(
        "Dashboard Operators Plots",
        plots,
    )
    response = HttpResponse(pdf_data, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="dashboard_operators.pdf"'
    return response


@login_required
def export_analytics_excel(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    data = _analytics_dataset(request)
    workbook = Workbook()
    daily = workbook.active
    daily.title = "Daily"
    daily.append(["day", "answered", "abandoned", "timeout", "unanswered"])
    for row in data["daily"]:
        daily.append([row.get("day"), row.get("answered"), row.get("abandoned"), row.get("timeout"), row.get("unanswered")])

    hourly = workbook.create_sheet("Hourly")
    hourly.append(["hour", "answered", "unanswered"])
    for row in data["hourly"]:
        hourly.append([row.get("hour"), row.get("answered"), row.get("unanswered")])

    queues = workbook.create_sheet("Queues")
    queues.append(["queue", "total", "answered", "unanswered", "sla", "abandon_rate", "timeout_rate", "aht"])
    for row in data["per_queue"]:
        queues.append(
            [
                row.get("queue_display"),
                row.get("total_calls"),
                row.get("answered"),
                row.get("unanswered"),
                row.get("sla"),
                row.get("abandon_rate"),
                row.get("timeout_rate"),
                row.get("aht"),
            ]
        )

    agents = workbook.create_sheet("Agents")
    agents.append(["agent", "answered", "share", "avg_hold", "avg_talk", "aht"])
    for row in data["top_agents"]:
        agents.append(
            [
                row.get("agent_display"),
                row.get("answered"),
                row.get("share_answered"),
                row.get("avg_hold"),
                row.get("avg_talk"),
                row.get("aht"),
            ]
        )

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    response = HttpResponse(output.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="analytics_dashboard.xlsx"'
    return response


@login_required
def export_analytics_pdf(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    data = _analytics_dataset(request)
    plots = [
        {
            "type": "line",
            "title": "Daily total calls",
            "labels": [r.get("day") for r in data["daily"][:31]],
            "values": [int(r.get("answered") or 0) + int(r.get("unanswered") or 0) for r in data["daily"][:31]],
        },
        {
            "type": "bar",
            "title": "Hourly total calls",
            "labels": [r.get("hour") for r in data["hourly"][:24]],
            "values": [int(r.get("answered") or 0) + int(r.get("unanswered") or 0) for r in data["hourly"][:24]],
        },
        {
            "type": "bar",
            "title": "Calls by queue",
            "labels": [r.get("queue_display") for r in data["per_queue"][:16]],
            "values": [r.get("total_calls") for r in data["per_queue"][:16]],
        },
        {
            "type": "bar",
            "title": "Answered by operator",
            "labels": [r.get("agent_display") for r in data["top_agents"][:16]],
            "values": [r.get("answered") for r in data["top_agents"][:16]],
        },
    ]
    pdf_data = _draw_plots_pdf("Analytics Dashboard Plots", plots)
    response = HttpResponse(pdf_data, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="analytics_dashboard.pdf"'
    return response


@login_required
def realtime_oob_partial(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    return render(request, "stats/partials/realtime_oob.html", _build_ami_snapshot(request))
