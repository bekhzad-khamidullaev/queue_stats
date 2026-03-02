from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Dict, List
from decimal import Decimal, ROUND_HALF_UP

from django.http import HttpRequest, Http404
from django.db import connections

from .models import CallTranscription
from .views import _fetch_queuelog_rows
from .utils import ui_pagination_meta as _pagination_meta, ui_pagination_params as _pagination_params, to_int as _to_int
from .helpers import (
    _get_general_settings,
    _queue_map,
    _agent_map,
    _display_queue,
    _display_agent,
    _agent_aliases,
    _is_internal_party,
    _payout_rate_map,
    _interval_from_request,
    _get_param_list,
    _fetch_queuelog_page,
    _caller_map_by_callids,
    _queuelog_avg_numeric,
    _filter_value,
    _classify_call_direction,
    _recording_file_by_uniqueid,
    _resolve_recording_local_path,
)
from .i18n_map import tr as i18n_tr

def answered_dataset(request: HttpRequest) -> Dict[str, Any]:
    start, end = _interval_from_request(request)
    queues = _get_param_list(request, "queues")
    agents = _get_param_list(request, "agents")
    qmap = _queue_map()
    amap = _agent_map()

    page, page_size = _pagination_params(request)
    rows, total = _fetch_queuelog_page(start, end, queues, agents, ["COMPLETECALLER", "COMPLETEAGENT"], page, page_size)
    caller_map = _caller_map_by_callids([str(r.get("callid") or "") for r in rows])
    recording_map: Dict[str, bool] = {}
    callids = [str(r.get("callid") or "") for r in rows if str(r.get("callid") or "")]
    if callids:
        placeholders = ",".join(["%s"] * len(callids))
        with connections["default"].cursor() as cursor:
            cursor.execute(
                f"SELECT uniqueid, recordingfile FROM cdr WHERE uniqueid IN ({placeholders})",
                callids,
            )
            for uniqueid, recordingfile in cursor.fetchall():
                recording_map[str(uniqueid)] = bool(recordingfile)

    flat_rows: List[Dict[str, Any]] = []
    for row in rows:
        callid = str(row.get("callid") or "")
        queue = str(row.get("queuename") or "")
        agent = str(row.get("agent") or "")
        flat_rows.append(
            {
                "callid": callid,
                "time": row.get("time"),
                "caller": caller_map.get(callid, ""),
                "queue": queue,
                "queue_display": _display_queue(queue, qmap),
                "agent": agent,
                "agent_display": _display_agent(agent, amap),
                "hold": int(row.get("data1") or 0),
                "talk": int(row.get("data2") or 0),
                "has_recording": bool(recording_map.get(callid, False)),
            }
        )

    pagination = _pagination_meta(request, page, page_size, total)
    avg_hold = _queuelog_avg_numeric(start, end, queues, agents, ["COMPLETECALLER", "COMPLETEAGENT"], "data1")
    avg_talk = _queuelog_avg_numeric(start, end, queues, agents, ["COMPLETECALLER", "COMPLETEAGENT"], "data2")
    return {
        "start": start,
        "end": end,
        "rows": flat_rows,
        "total": total,
        "avg_hold": avg_hold,
        "avg_talk": avg_talk,
        **pagination,
    }


def unanswered_dataset(request: HttpRequest) -> Dict[str, Any]:
    start, end = _interval_from_request(request)
    queues = _get_param_list(request, "queues")
    qmap = _queue_map()
    page, page_size = _pagination_params(request)
    rows, total = _fetch_queuelog_page(start, end, queues, None, ["ABANDON", "EXITWITHTIMEOUT"], page, page_size)
    caller_map = _caller_map_by_callids([str(r.get("callid") or "") for r in rows])

    flat_rows: List[Dict[str, Any]] = []
    for row in rows:
        callid = str(row.get("callid") or "")
        queue = str(row.get("queuename") or "")
        flat_rows.append(
            {
                "callid": callid,
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

    pagination = _pagination_meta(request, page, page_size, total)
    avg_wait = _queuelog_avg_numeric(start, end, queues, None, ["ABANDON", "EXITWITHTIMEOUT"], "data3")
    return {
        "start": start,
        "end": end,
        "rows": flat_rows,
        "total": total,
        "avg_wait": avg_wait,
        **pagination,
    }


def cdr_dataset(request: HttpRequest) -> Dict[str, Any]:
    start, end = _interval_from_request(request)
    agents = _get_param_list(request, "agents")
    src_filter = _filter_value(request, "src")
    dst_filter = _filter_value(request, "dst")
    disposition_filter = _filter_value(request, "disposition")
    page, page_size = _pagination_params(request)

    amap = _agent_map()
    qmap = _queue_map()

    where: List[str] = ["c.calldate >= %s", "c.calldate <= %s"]
    params: List[Any] = [start, end]

    agent_values: List[str] = []
    if agents:
        for raw in agents:
            for alias in _agent_aliases(raw):
                if alias not in agent_values:
                    agent_values.append(alias)
        if agent_values:
            placeholders = ",".join(["%s"] * len(agent_values))
            where.append(
                "("
                f"c.cnam IN ({placeholders}) OR c.cnum IN ({placeholders}) "
                f"OR ql.agent IN ({placeholders}) OR c.dstchannel IN ({placeholders})"
                ")"
            )
            params.extend(agent_values)
            params.extend(agent_values)
            params.extend(agent_values)
            params.extend(agent_values)

            like_chunks: List[str] = []
            like_params: List[str] = []
            for alias in agent_values:
                like_chunks.append("c.dstchannel LIKE %s")
                like_params.append(f"%/{alias}@%")
                like_chunks.append("c.dstchannel LIKE %s")
                like_params.append(f"%/{alias}-%")
            if like_chunks:
                where.append(f"({' OR '.join(like_chunks)})")
                params.extend(like_params)

    if src_filter:
        where.append("c.src LIKE %s")
        params.append(f"%{src_filter}%")
    if dst_filter:
        where.append("(c.dst LIKE %s OR c.dcontext LIKE %s OR c.lastdata LIKE %s)")
        params.append(f"%{dst_filter}%")
        params.append(f"%{dst_filter}%")
        params.append(f"%{dst_filter}%")
    if disposition_filter:
        where.append("c.disposition = %s")
        params.append(disposition_filter)

    where_sql = " AND ".join(where)
    from_sql = """
        FROM cdr c
        LEFT JOIN (
            SELECT
                callid,
                SUBSTRING_INDEX(GROUP_CONCAT(agent ORDER BY time DESC SEPARATOR ','), ',', 1) AS agent
            FROM queuelog
            WHERE event IN ('CONNECT', 'COMPLETECALLER', 'COMPLETEAGENT')
              AND time >= %s AND time <= %s
              AND agent IS NOT NULL AND agent <> ''
            GROUP BY callid
        ) ql ON ql.callid = c.uniqueid
    """
    count_sql = f"SELECT COUNT(*) {from_sql} WHERE {where_sql}"
    count_params = [start, end, *params]

    with connections["default"].cursor() as cursor:
        cursor.execute(count_sql, count_params)
        total = int(cursor.fetchone()[0] or 0)

    pagination = _pagination_meta(request, page, page_size, total)
    offset = (pagination["page"] - 1) * pagination["page_size"]

    sql = f"""
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
        {from_sql}
        WHERE {where_sql}
        ORDER BY c.calldate DESC
        LIMIT %s OFFSET %s
    """
    data_params = [start, end, *params, pagination["page_size"], offset]

    with connections["default"].cursor() as cursor:
        cursor.execute(sql, data_params)
        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description]
    data = [dict(zip(columns, row)) for row in rows]

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

    return {"start": start, "end": end, "rows": data, "total": total, **pagination}


def outbound_dataset(request: HttpRequest) -> Dict[str, Any]:
    start, end = _interval_from_request(request)
    agents = _get_param_list(request, "agents")
    src_filter = _filter_value(request, "src")
    dst_filter = _filter_value(request, "dst")
    disposition_filter = _filter_value(request, "disposition")
    page, page_size = _pagination_params(request)
    amap = _agent_map()

    where: List[str] = ["calldate >= %s", "calldate <= %s"]
    params: List[Any] = [start, end]

    if agents:
        agent_values = []
        for raw in agents:
            for alias in _agent_aliases(raw):
                if alias not in agent_values:
                    agent_values.append(alias)
        if agent_values:
            placeholders = ",".join(["%s"] * len(agent_values))
            where.append(
                "("
                f"cnam IN ({placeholders}) OR cnum IN ({placeholders}) OR dstchannel IN ({placeholders})"
                ")"
            )
            params.extend(agent_values)
            params.extend(agent_values)
            params.extend(agent_values)

    if src_filter:
        where.append("src LIKE %s")
        params.append(f"%{src_filter}%")
    if dst_filter:
        where.append("(dst LIKE %s OR dcontext LIKE %s OR lastdata LIKE %s)")
        params.append(f"%{dst_filter}%")
        params.append(f"%{dst_filter}%")
        params.append(f"%{dst_filter}%")
    if disposition_filter:
        where.append("disposition = %s")
        params.append(disposition_filter)

    where_sql = " AND ".join(where)

    count_sql = f"SELECT COUNT(*) FROM cdr WHERE {where_sql}"
    with connections["default"].cursor() as cursor:
        cursor.execute(count_sql, params)
        total = int(cursor.fetchone()[0] or 0)

    pagination = _pagination_meta(request, page, page_size, total)
    offset = (pagination["page"] - 1) * pagination["page_size"]

    sql = f"""
        SELECT calldate, uniqueid, billsec, disposition, src, dst, cnum, cnam, recordingfile
        FROM cdr
        WHERE {where_sql}
        ORDER BY calldate DESC
        LIMIT %s OFFSET %s
    """
    
    overview_sql = f"""
        SELECT
            COALESCE(NULLIF(cnum, ''), NULLIF(cnam, ''), 'UNKNOWN') AS agent_key,
            SUM(CASE WHEN disposition = 'ANSWERED' THEN 1 ELSE 0 END) AS answered,
            SUM(CASE WHEN disposition = 'NO ANSWER' THEN 1 ELSE 0 END) AS no_answer,
            SUM(CASE WHEN disposition = 'BUSY' THEN 1 ELSE 0 END) AS busy,
            COUNT(*) AS total_count,
            COALESCE(AVG(CAST(billsec AS UNSIGNED)), 0) AS avg_billsec
        FROM cdr
        WHERE {where_sql}
        GROUP BY agent_key
    """

    with connections["default"].cursor() as cursor:
        cursor.execute(sql, [*params, pagination["page_size"], offset])
        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description]

        cursor.execute(overview_sql, params)
        overview_rows = cursor.fetchall()

    data = [dict(zip(columns, row)) for row in rows]
    for row in data:
        operator_system = str(row.get("cnam") or "")
        row["operator_display"] = _display_agent(operator_system, amap)
        row["has_recording"] = bool(row.get("recordingfile"))

    overview = {"ANSWERED": 0, "NO ANSWER": 0, "BUSY": 0, "TOTAL": 0}
    weighted_billsec_total = 0.0
    for agent_key, answered, no_answer, busy, total_count, avg_billsec in overview_rows:
        overview["ANSWERED"] += int(answered or 0)
        overview["NO ANSWER"] += int(no_answer or 0)
        overview["BUSY"] += int(busy or 0)
        overview["TOTAL"] += int(total_count or 0)
        weighted_billsec_total += float(avg_billsec or 0) * int(total_count or 0)

    avg_billsec = round(weighted_billsec_total / overview["TOTAL"], 2) if overview["TOTAL"] else 0

    return {
        "start": start,
        "end": end,
        "rows": data,
        "total": total,
        "overview": overview,
        "avg_billsec": avg_billsec,
        "selected_src": src_filter,
        "selected_dst": dst_filter,
        "selected_disposition": disposition_filter,
        **pagination,
    }


def call_detail_dataset(callid: str) -> Dict[str, Any]:
    qmap = _queue_map()
    amap = _agent_map()
    normalized_callid = str(callid or "").strip()
    cdr_row: Dict[str, Any] = {}

    with connections["default"].cursor() as cursor:
        cursor.execute(
            """
            SELECT
                uniqueid, calldate, src, dst, dcontext, channel, dstchannel,
                lastapp, lastdata, duration, billsec, disposition, recordingfile
            FROM cdr
            WHERE uniqueid = %s
            ORDER BY calldate DESC
            LIMIT 1
            """,
            [normalized_callid],
        )
        row = cursor.fetchone()
        if row:
            columns = [col[0] for col in cursor.description]
            cdr_row = dict(zip(columns, row))

        cursor.execute(
            """
            SELECT time, callid, queuename, agent, event, data1, data2, data3, data4, data5
            FROM queuelog
            WHERE callid = %s
            ORDER BY time ASC
            LIMIT 1000
            """,
            [normalized_callid],
        )
        qlog_columns = [col[0] for col in cursor.description]
        qlog_events = [dict(zip(qlog_columns, r)) for r in cursor.fetchall()]

    caller = ""
    event_rows: List[Dict[str, Any]] = []
    outcome = "IN_PROGRESS"
    for row in qlog_events:
        queue_raw = str(row.get("queuename") or "")
        agent_raw = str(row.get("agent") or "")
        event_name = str(row.get("event") or "")
        if event_name == "ENTERQUEUE" and not caller:
            caller = str(row.get("data2") or "")
        if event_name in {"COMPLETECALLER", "COMPLETEAGENT"}:
            outcome = "ANSWERED"
        elif event_name == "ABANDON":
            outcome = "ABANDONED"
        elif event_name == "EXITWITHTIMEOUT":
            outcome = "TIMEOUT"
        event_rows.append(
            {
                "time": row.get("time"),
                "event": event_name,
                "queue": queue_raw,
                "queue_display": _display_queue(queue_raw, qmap),
                "agent": agent_raw,
                "agent_display": _display_agent(agent_raw, amap) if agent_raw else "",
                "data1": row.get("data1"),
                "data2": row.get("data2"),
                "data3": row.get("data3"),
                "data4": row.get("data4"),
                "data5": row.get("data5"),
            }
        )

    if cdr_row:
        operator_system = str(cdr_row.get("dstchannel") or "")
        cdr_row["operator_display"] = _display_agent(operator_system, amap) if operator_system else ""
        cdr_row["has_recording"] = bool(cdr_row.get("recordingfile"))

    if not caller and cdr_row:
        caller = str(cdr_row.get("src") or "")

    transcription = CallTranscription.objects.filter(callid=normalized_callid).first()
    conf = _get_general_settings()
    transcription_configured = bool((conf.transcription_url or "").strip() and (conf.transcription_api_key or "").strip())
    transcription_text = str(transcription.text or "").strip() if transcription else ""
    transcription_chunks = [part.strip() for part in re.split(r"(?<=[.!?])\s+", transcription_text) if part.strip()]

    return {
        "callid": normalized_callid,
        "caller": caller,
        "outcome": outcome,
        "cdr": cdr_row,
        "events": event_rows,
        "has_data": bool(cdr_row) or bool(event_rows),
        "transcription": transcription,
        "transcription_text": transcription_text,
        "transcription_chunks": transcription_chunks,
        "transcription_configured": transcription_configured,
    }


def summary_dataset(request: HttpRequest) -> Dict[str, Any]:
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


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _daily_series_with_gaps(
    raw_rows: List[Dict[str, Any]],
    start,
    end,
    max_days: int = 366,
) -> List[Dict[str, Any]]:
    day_map: Dict[str, Dict[str, Any]] = {str(row.get("day")): row for row in raw_rows}
    span_days = (end.date() - start.date()).days + 1
    if span_days <= 0 or span_days > max_days:
        return raw_rows

    rows: List[Dict[str, Any]] = []
    cursor = start.date()
    last_day = end.date()
    while cursor <= last_day:
        day_key = cursor.isoformat()
        source = day_map.get(day_key, {})
        rows.append(
            {
                "day": day_key,
                "answered": _safe_int(source.get("answered")),
                "abandoned": _safe_int(source.get("abandoned")),
                "timeout": _safe_int(source.get("timeout")),
                "unanswered": _safe_int(source.get("unanswered")),
            }
        )
        cursor += timedelta(days=1)
    return rows


def _hourly_series_with_gaps(raw_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_hour = {int(row.get("hour")): row for row in raw_rows if row.get("hour") is not None}
    rows: List[Dict[str, Any]] = []
    for hour in range(24):
        source = by_hour.get(hour, {})
        rows.append(
            {
                "hour": hour,
                "answered": _safe_int(source.get("answered")),
                "unanswered": _safe_int(source.get("unanswered")),
            }
        )
    return rows


def _percent_delta(current: int | float, previous: int | float) -> float:
    if not previous:
        return 0.0
    return round((float(current) - float(previous)) * 100 / float(previous), 2)


def analytics_dataset(request: HttpRequest) -> Dict[str, Any]:
    start, end = _interval_from_request(request)
    queues = _get_param_list(request, "queues")
    agents = _get_param_list(request, "agents")
    qmap = _queue_map()
    amap = _agent_map()
    general = _get_general_settings()
    sla_target_wait_seconds = _safe_int(general.sla_target_wait_seconds) or 20
    sla_target_percent = float(general.sla_target_percent or 80)
    queue_clause = ""
    agent_clause = ""
    agent_filter_values: List[str] = []
    for raw in agents:
        for alias in _agent_aliases(raw):
            if alias and alias not in agent_filter_values:
                agent_filter_values.append(alias)
    agent_callid_clause = ""
    if queues:
        queue_clause = f" AND queuename IN ({','.join(['%s'] * len(queues))})"
    if agent_filter_values:
        placeholders = ",".join(["%s"] * len(agent_filter_values))
        agent_clause = f" AND agent IN ({placeholders})"
        agent_callid_clause = f"""
          AND EXISTS (
              SELECT 1
              FROM queuelog qa
              WHERE qa.callid = queuelog.callid
                AND qa.event IN ('CONNECT','COMPLETECALLER','COMPLETEAGENT')
                AND qa.agent IN ({placeholders})
          )
        """

    queue_params: List[Any] = [start, end, *queues, *agent_filter_values]
    queue_agent_params: List[Any] = [start, end, *queues, *agent_filter_values]

    sql_daily = f"""
        SELECT DATE(time) AS day,
               SUM(CASE WHEN event IN ('COMPLETECALLER','COMPLETEAGENT') THEN 1 ELSE 0 END) AS answered,
               SUM(CASE WHEN event = 'ABANDON' THEN 1 ELSE 0 END) AS abandoned,
               SUM(CASE WHEN event = 'EXITWITHTIMEOUT' THEN 1 ELSE 0 END) AS timeout,
               SUM(CASE WHEN event IN ('ABANDON','EXITWITHTIMEOUT') THEN 1 ELSE 0 END) AS unanswered
        FROM queuelog
        WHERE time >= %s AND time <= %s {queue_clause} {agent_callid_clause}
        GROUP BY day
        ORDER BY day
    """

    sql_hourly = f"""
        SELECT HOUR(time) AS hour,
               SUM(CASE WHEN event IN ('COMPLETECALLER','COMPLETEAGENT') THEN 1 ELSE 0 END) AS answered,
               SUM(CASE WHEN event IN ('ABANDON','EXITWITHTIMEOUT') THEN 1 ELSE 0 END) AS unanswered
        FROM queuelog
        WHERE time >= %s AND time <= %s {queue_clause} {agent_callid_clause}
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
        WHERE time >= %s AND time <= %s {queue_clause} {agent_callid_clause}
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

    sql_sla_current = f"""
        SELECT
            SUM(CASE WHEN event IN ('COMPLETECALLER','COMPLETEAGENT') THEN 1 ELSE 0 END) AS answered_total,
            SUM(
                CASE
                    WHEN event IN ('COMPLETECALLER','COMPLETEAGENT')
                         AND CAST(COALESCE(NULLIF(data1, ''), '0') AS UNSIGNED) <= %s
                    THEN 1
                    ELSE 0
                END
            ) AS answered_in_sla
        FROM queuelog
        WHERE time >= %s AND time <= %s {queue_clause} {agent_callid_clause}
    """

    period_delta = end - start
    prev_end = start - timedelta(seconds=1)
    prev_start = prev_end - period_delta
    prev_params: List[Any] = [prev_start, prev_end, *queues, *agent_filter_values]
    sql_prev_totals = f"""
        SELECT
            SUM(CASE WHEN event IN ('COMPLETECALLER','COMPLETEAGENT') THEN 1 ELSE 0 END) AS answered,
            SUM(CASE WHEN event = 'ABANDON' THEN 1 ELSE 0 END) AS abandoned,
            SUM(CASE WHEN event = 'EXITWITHTIMEOUT' THEN 1 ELSE 0 END) AS timeout,
            SUM(
                CASE
                    WHEN event IN ('COMPLETECALLER','COMPLETEAGENT')
                         AND CAST(COALESCE(NULLIF(data1, ''), '0') AS UNSIGNED) <= %s
                    THEN 1
                    ELSE 0
                END
            ) AS answered_in_sla
        FROM queuelog
        WHERE time >= %s AND time <= %s {queue_clause} {agent_callid_clause}
    """

    queue_clause_q = f" AND q.queuename IN ({','.join(['%s'] * len(queues))})" if queues else ""
    caller_agent_clause = (
        f"""
        AND EXISTS (
            SELECT 1
            FROM queuelog qa
            WHERE qa.callid = q.callid
              AND qa.event IN ('CONNECT','COMPLETECALLER','COMPLETEAGENT')
              AND qa.agent IN ({','.join(['%s'] * len(agent_filter_values))})
        )
        """
        if agent_filter_values
        else ""
    )
    caller_params: List[Any] = [start, end, *queues, *agent_filter_values]
    sql_top_callers = f"""
        SELECT TRIM(q.data2) AS caller, COUNT(DISTINCT q.callid) AS calls
        FROM queuelog q
        WHERE q.time >= %s AND q.time <= %s
          AND q.event = 'ENTERQUEUE'
          {queue_clause_q}
          AND q.data2 IS NOT NULL
          AND TRIM(q.data2) <> ''
          AND LOWER(TRIM(q.data2)) NOT IN ('unknown','<unknown>')
          {caller_agent_clause}
        GROUP BY caller
        ORDER BY calls DESC, caller ASC
        LIMIT 25
    """

    cdr_queue_clause = (
        f"""
        AND EXISTS (
            SELECT 1
            FROM queuelog qf
            WHERE qf.callid = c.uniqueid
              AND qf.queuename IN ({','.join(['%s'] * len(queues))})
        )
        """
        if queues
        else ""
    )
    cdr_agent_clause = (
        f"""
        AND EXISTS (
            SELECT 1
            FROM queuelog qfa
            WHERE qfa.callid = c.uniqueid
              AND qfa.event IN ('CONNECT', 'COMPLETECALLER', 'COMPLETEAGENT')
              AND qfa.agent IN ({','.join(['%s'] * len(agent_filter_values))})
        )
        """
        if agent_filter_values
        else ""
    )
    cdr_params: List[Any] = [start, end, start, end, *queues, *agent_filter_values]
    sql_operator_cdr = f"""
        SELECT
            c.uniqueid,
            c.calldate,
            c.src,
            c.dst,
            c.dcontext,
            c.channel,
            c.dstchannel,
            c.billsec,
            ql.agent AS queue_agent
        FROM cdr c
        LEFT JOIN (
            SELECT
                callid,
                SUBSTRING_INDEX(GROUP_CONCAT(agent ORDER BY time DESC SEPARATOR ','), ',', 1) AS agent
            FROM queuelog
            WHERE event IN ('CONNECT', 'COMPLETECALLER', 'COMPLETEAGENT')
              AND time >= %s AND time <= %s
              AND agent IS NOT NULL AND agent <> ''
            GROUP BY callid
        ) ql ON ql.callid = c.uniqueid
        WHERE c.calldate >= %s AND c.calldate <= %s
          {cdr_queue_clause}
          {cdr_agent_clause}
        ORDER BY c.calldate ASC
        LIMIT 50000
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

        cursor.execute(sql_sla_current, [sla_target_wait_seconds, start, end, *queues, *agent_filter_values])
        current_sla_row = dict(zip([c[0] for c in cursor.description], cursor.fetchone() or []))

        cursor.execute(sql_prev_totals, [sla_target_wait_seconds, *prev_params])
        prev_totals_row = dict(zip([c[0] for c in cursor.description], cursor.fetchone() or []))

        cursor.execute(sql_top_callers, caller_params)
        top_callers = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]

        cursor.execute(sql_operator_cdr, cdr_params)
        operator_cdr_rows = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]

    daily = _daily_series_with_gaps(daily, start, end)
    hourly = _hourly_series_with_gaps(hourly)

    total_answered = sum(_safe_int(x.get("answered")) for x in daily)
    total_abandoned = sum(_safe_int(x.get("abandoned")) for x in daily)
    total_timeout = sum(_safe_int(x.get("timeout")) for x in daily)
    total_unanswered = total_abandoned + total_timeout
    total_calls = total_answered + total_unanswered
    answered_in_sla = _safe_int(current_sla_row.get("answered_in_sla"))
    kpi_sla_by_target = round(answered_in_sla * 100 / total_answered, 2) if total_answered else 0

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

    agent_filter_set = set()
    for raw in agents:
        for key in _agent_aliases(raw):
            agent_filter_set.add(key)

    operator_stats_map: Dict[str, Dict[str, Any]] = {}
    daily_direction_talk: Dict[str, Dict[str, int]] = {}
    total_incoming_talk_sec = 0
    total_outgoing_talk_sec = 0
    total_incoming_calls = 0
    total_outgoing_calls = 0

    for row in operator_cdr_rows:
        billsec = int(row.get("billsec") or 0)
        if billsec <= 0:
            continue

        queue_agent = str(row.get("queue_agent") or "").strip()
        operator_raw = queue_agent or str(row.get("dstchannel") or "").strip() or str(row.get("channel") or "").strip()
        if not operator_raw:
            src = str(row.get("src") or "").strip()
            dst = str(row.get("dst") or "").strip()
            if _is_internal_party(src):
                operator_raw = src
            elif _is_internal_party(dst):
                operator_raw = dst
        if not operator_raw:
            continue

        aliases = _agent_aliases(operator_raw)
        if not aliases:
            continue
        operator_key = aliases[-1]

        if agent_filter_set and not (set(aliases) & agent_filter_set):
            continue

        direction = _classify_call_direction(
            str(row.get("src") or ""),
            str(row.get("dst") or ""),
            str(row.get("dcontext") or ""),
            queue_agent,
        )
        day_label = str(row.get("calldate") or "")[:10]

        operator_stats_map.setdefault(
            operator_key,
            {
                "agent": operator_key,
                "agent_display": _display_agent(operator_raw, amap),
                "handled_calls": 0,
                "talk_sec_total": 0,
                "incoming_calls": 0,
                "incoming_talk_sec": 0,
                "outgoing_calls": 0,
                "outgoing_talk_sec": 0,
                "unknown_calls": 0,
                "unknown_talk_sec": 0,
            },
        )
        stat = operator_stats_map[operator_key]
        stat["handled_calls"] += 1
        stat["talk_sec_total"] += billsec
        if direction == "incoming":
            stat["incoming_calls"] += 1
            stat["incoming_talk_sec"] += billsec
            total_incoming_calls += 1
            total_incoming_talk_sec += billsec
        elif direction == "outgoing":
            stat["outgoing_calls"] += 1
            stat["outgoing_talk_sec"] += billsec
            total_outgoing_calls += 1
            total_outgoing_talk_sec += billsec
        else:
            stat["unknown_calls"] += 1
            stat["unknown_talk_sec"] += billsec

        if day_label:
            daily_direction_talk.setdefault(day_label, {"day": day_label, "incoming_talk_sec": 0, "outgoing_talk_sec": 0})
            if direction == "incoming":
                daily_direction_talk[day_label]["incoming_talk_sec"] += billsec
            elif direction == "outgoing":
                daily_direction_talk[day_label]["outgoing_talk_sec"] += billsec

    operator_duration_rows = sorted(
        operator_stats_map.values(),
        key=lambda item: (int(item.get("handled_calls") or 0), int(item.get("talk_sec_total") or 0)),
        reverse=True,
    )
    rank_calls = sorted(
        operator_duration_rows,
        key=lambda item: (int(item.get("handled_calls") or 0), int(item.get("talk_sec_total") or 0)),
        reverse=True,
    )
    rank_talk = sorted(
        operator_duration_rows,
        key=lambda item: (int(item.get("talk_sec_total") or 0), int(item.get("handled_calls") or 0)),
        reverse=True,
    )
    rank_by_calls_map = {str(row.get("agent")): idx for idx, row in enumerate(rank_calls, start=1)}
    rank_by_talk_map = {str(row.get("agent")): idx for idx, row in enumerate(rank_talk, start=1)}
    for row in operator_duration_rows:
        handled_calls = int(row.get("handled_calls") or 0)
        talk_sec_total = int(row.get("talk_sec_total") or 0)
        row["avg_talk_sec"] = round(talk_sec_total / handled_calls, 2) if handled_calls else 0
        row["talk_min_total"] = round(talk_sec_total / 60, 2)
        row["incoming_talk_min"] = round(int(row.get("incoming_talk_sec") or 0) / 60, 2)
        row["outgoing_talk_min"] = round(int(row.get("outgoing_talk_sec") or 0) / 60, 2)
        row["rank_by_calls"] = rank_by_calls_map.get(str(row.get("agent")), 0)
        row["rank_by_talk"] = rank_by_talk_map.get(str(row.get("agent")), 0)

    top_operator_by_calls = rank_calls[:20]
    top_operator_by_talk = rank_talk[:20]
    direction_daily_rows = [daily_direction_talk[key] for key in sorted(daily_direction_talk.keys())]
    for row in direction_daily_rows:
        row["incoming_talk_min"] = round(int(row.get("incoming_talk_sec") or 0) / 60, 2)
        row["outgoing_talk_min"] = round(int(row.get("outgoing_talk_sec") or 0) / 60, 2)

    daily_chart_input: List[Dict[str, Any]] = []
    for row in daily:
        total_day = int(row.get("answered") or 0) + int(row.get("unanswered") or 0)
        daily_chart_input.append(
            {
                "day": row.get("day"),
                "total": total_day,
            }
        )
    hourly_chart_input: List[Dict[str, Any]] = []
    for row in hourly:
        total_hour = int(row.get("answered") or 0) + int(row.get("unanswered") or 0)
        hourly_chart_input.append(
            {
                "hour": row.get("hour"),
                "total": total_hour,
            }
        )

    peak_day = max(daily_chart_input, key=lambda item: item.get("total") or 0, default={})
    peak_hour = max(hourly_chart_input, key=lambda item: item.get("total") or 0, default={})

    prev_answered = _safe_int(prev_totals_row.get("answered"))
    prev_abandoned = _safe_int(prev_totals_row.get("abandoned"))
    prev_timeout = _safe_int(prev_totals_row.get("timeout"))
    prev_total = prev_answered + prev_abandoned + prev_timeout
    prev_unanswered = prev_abandoned + prev_timeout
    prev_answered_in_sla = _safe_int(prev_totals_row.get("answered_in_sla"))
    prev_sla_by_target = round(prev_answered_in_sla * 100 / prev_answered, 2) if prev_answered else 0

    delta_total = total_calls - prev_total
    delta_answered = total_answered - prev_answered
    delta_unanswered = total_unanswered - prev_unanswered
    delta_sla_by_target = round(kpi_sla_by_target - prev_sla_by_target, 2)

    for row in top_callers:
        row["caller"] = str(row.get("caller") or "").strip()
        row["calls"] = int(row.get("calls") or 0)

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
        "kpi_sla_by_target": kpi_sla_by_target,
        "kpi_sla_target_percent": round(sla_target_percent, 2),
        "kpi_sla_target_wait_seconds": sla_target_wait_seconds,
        "kpi_sla_gap_to_target": round(kpi_sla_by_target - sla_target_percent, 2),
        "kpi_answered_in_sla": answered_in_sla,
        "kpi_avg_hold": round(sum_hold_answered / total_answered, 2) if total_answered else 0,
        "kpi_avg_talk": round(sum_talk_answered / total_answered, 2) if total_answered else 0,
        "kpi_aht": round((sum_hold_answered + sum_talk_answered) / total_answered, 2) if total_answered else 0,
        "kpi_total_talk_min": round(sum_talk_answered / 60, 2),
        "kpi_active_queues": len([x for x in per_queue if int(x.get("total_calls") or 0) > 0]),
        "kpi_active_agents": len([x for x in top_agents if int(x.get("answered") or 0) > 0]),
        "kpi_incoming_talk_min": round(total_incoming_talk_sec / 60, 2),
        "kpi_outgoing_talk_min": round(total_outgoing_talk_sec / 60, 2),
        "kpi_incoming_calls": total_incoming_calls,
        "kpi_outgoing_calls": total_outgoing_calls,
        "kpi_peak_day": peak_day.get("day", "-"),
        "kpi_peak_day_calls": peak_day.get("total", 0),
        "kpi_peak_hour": peak_hour.get("hour", "-"),
        "kpi_peak_hour_calls": peak_hour.get("total", 0),
        "kpi_prev_total": prev_total,
        "kpi_prev_answered": prev_answered,
        "kpi_prev_unanswered": prev_unanswered,
        "kpi_prev_sla_by_target": prev_sla_by_target,
        "kpi_delta_total": delta_total,
        "kpi_delta_total_percent": _percent_delta(total_calls, prev_total),
        "kpi_delta_answered": delta_answered,
        "kpi_delta_answered_percent": _percent_delta(total_answered, prev_answered),
        "kpi_delta_unanswered": delta_unanswered,
        "kpi_delta_unanswered_percent": _percent_delta(total_unanswered, prev_unanswered),
        "kpi_delta_sla_by_target": delta_sla_by_target,
        "kpi_prev_interval_start": prev_start,
        "kpi_prev_interval_end": prev_end,
        "daily": daily,
        "hourly": hourly,
        "per_queue": per_queue,
        "top_agents": top_agents,
        "top_callers": top_callers,
        "operator_duration_rows": operator_duration_rows,
        "operator_rank_by_calls": top_operator_by_calls,
        "operator_rank_by_talk": top_operator_by_talk,
        "daily_direction_talk": direction_daily_rows,
        "daily_line_chart": _line_chart(daily_chart_input, "day", "total", max_items=31),
        "hourly_bar_chart": _bar_chart(hourly_chart_input, "hour", "total", max_items=24),
        "queue_calls_chart": _bar_chart(per_queue, "queue_display", "total_calls", max_items=16),
        "agent_answered_chart": _bar_chart(top_agents, "agent_display", "answered", max_items=16),
        "frequent_callers_chart": _bar_chart(top_callers, "caller", "calls", max_items=16),
        "operator_total_calls_chart": _bar_chart(top_operator_by_calls, "agent_display", "handled_calls", max_items=16),
        "operator_total_talk_chart": _bar_chart(top_operator_by_talk, "agent_display", "talk_min_total", max_items=16),
        "incoming_talk_daily_chart": _line_chart(direction_daily_rows, "day", "incoming_talk_min", max_items=31),
        "outgoing_talk_daily_chart": _line_chart(direction_daily_rows, "day", "outgoing_talk_min", max_items=31),
    }


def payout_dataset(request: HttpRequest) -> Dict[str, Any]:
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

def dashboard_traffic_dataset(request: HttpRequest) -> Dict[str, Any]:
    data = analytics_dataset(request)
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

def dashboard_queues_dataset(request: HttpRequest) -> Dict[str, Any]:
    data = analytics_dataset(request)
    rows = data.get("per_queue", [])
    data["queues_calls_chart"] = _bar_chart(rows, "queue_display", "total_calls")
    data["queues_sla_chart"] = _bar_chart(rows, "queue_display", "sla")
    data["per_queue"] = rows
    return data

def dashboard_operators_dataset(request: HttpRequest) -> Dict[str, Any]:
    analytics = analytics_dataset(request)
    payouts = payout_dataset(request)
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

def _transcribe_call(callid: str) -> tuple[bool, str]:
    import time
    from urllib.parse import urlparse, urlunparse
    import requests
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
            candidate_urls.append(urlunparse(parsed._replace(scheme="http")))

        response = None
        last_error: requests.RequestException | None = None
        for target_url in candidate_urls:
            for attempt in range(1, request_attempts + 1):
                try:
                    response = requests.post(target_url, headers=request_headers, files=request_files, timeout=request_timeout)
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

def _fetch_recording_bytes_for_call(callid: str) -> tuple[str, bytes, str]:
    import os
    import mimetypes
    import requests
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
