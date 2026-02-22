from __future__ import annotations

import json
import socket
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List

import requests
from django.db import connections
from django.http import FileResponse, Http404, HttpRequest, JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from accounts.models import UserRoles
from accounts.permissions import login_required_json, require_roles
from settings.models import GeneralSettings
from .models import AgentsNew, QueueLog, QueuesNew
from .utils import api_pagination_meta as _pagination_meta
from .utils import api_pagination_params as _pagination_from_payload
from .utils import to_int as _to_int

JsonDict = Dict[str, Any]





def _parse_request_payload(request: HttpRequest) -> JsonDict:
    if request.body:
        try:
            return json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
    if request.GET:
        return request.GET.dict()
    return {}


def _parse_datetime(value: str | None, default: datetime | None = None) -> datetime | None:
    if not value:
        return default
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return default


from .helpers import _normalize_list


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _join_enterqueue_callerids(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    caller_by_callid: Dict[str, str] = {}
    enriched: List[Dict[str, Any]] = []
    for row in rows:
        callid = str(row.get("callid") or "")
        if row.get("event") == "ENTERQUEUE":
            caller_by_callid[callid] = str(row.get("data2") or "")
            continue
        copy = dict(row)
        if callid in caller_by_callid:
            copy["callerid"] = caller_by_callid[callid]
        enriched.append(copy)
    return enriched


@require_GET
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST, UserRoles.AGENT)
def queues_list(request: HttpRequest) -> JsonResponse:
    items = list(QueuesNew.objects.order_by("queuename").values("queuename", "descr"))
    return JsonResponse({"queues": items})


@require_GET
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST)
def agents_list(request: HttpRequest) -> JsonResponse:
    items = list(AgentsNew.objects.order_by("agent").values("agent", "name"))
    return JsonResponse({"agents": items})


def _fetch_queuelog_rows(
    start: datetime,
    end: datetime,
    queues: Iterable[str] | None,
    agents: Iterable[str] | None,
    events: Iterable[str],
) -> List[Dict[str, Any]]:
    queue_params = list(queues or [])
    agent_params = list(agents or [])
    sql = f"""
        SELECT time, callid, queuename, agent, event, data1, data2, data3
        FROM queuelog
        WHERE time >= %s AND time <= %s
          AND event IN ({",".join(["%s"] * len(events))})
    """
    params: List[Any] = [start, end, *events]
    if queue_params:
        sql += f" AND queuename IN ({','.join(['%s'] * len(queue_params))})"
        params.extend(queue_params)
    if agent_params:
        sql += f" AND agent IN ({','.join(['%s'] * len(agent_params))})"
        params.extend(agent_params)
    with connections['default'].cursor() as cursor:
        cursor.execute(sql, params)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST)
def answered_report(request: HttpRequest) -> JsonResponse:
    payload = _parse_request_payload(request)
    queues = _normalize_list(payload.get("queues") or payload.get("queue"))
    agents = _normalize_list(payload.get("agents") or payload.get("agent"))
    start = _parse_datetime(payload.get("start")) or datetime.now().replace(hour=0, minute=0, second=0)
    end = _parse_datetime(payload.get("end")) or datetime.now().replace(hour=23, minute=59, second=59)

    rows = _fetch_queuelog_rows(start, end, queues, agents, ["COMPLETECALLER", "COMPLETEAGENT"])

    total_calls_per_agent: Counter[str] = Counter()
    total_hold_per_agent: Counter[str] = Counter()
    total_time_per_agent: Counter[str] = Counter()
    hold_distribution: Dict[str, List[int]] = defaultdict(list)

    grand_total_calls = 0
    grand_total_hold = 0
    grand_total_time = 0

    for row in rows:
        agent = row["agent"]
        queue = row["queuename"]
        hold = int(row.get("data1") or 0)
        talk = int(row.get("data2") or 0)

        total_calls_per_agent[agent] += 1
        total_hold_per_agent[agent] += hold
        total_time_per_agent[agent] += talk
        hold_distribution[queue].append(hold)

        grand_total_calls += 1
        grand_total_hold += hold
        grand_total_time += talk

    agents_summary = []
    for agent, calls in total_calls_per_agent.items():
        talk_time = total_time_per_agent[agent]
        hold_time = total_hold_per_agent[agent]
        avg_talk = talk_time / calls if calls else 0
        avg_hold = hold_time / calls if calls else 0
        agents_summary.append(
            {
                "agent": agent,
                "calls": calls,
                "calls_percent": round(calls * 100 / grand_total_calls, 2) if grand_total_calls else 0,
                "talk_time_total": talk_time,
                "talk_time_percent": round(talk_time * 100 / grand_total_time, 2) if grand_total_time else 0,
                "talk_time_avg": round(avg_talk, 2),
                "hold_time_total": hold_time,
                "hold_time_avg": round(avg_hold, 2),
            }
        )

    def _bucketize(values: List[int]) -> Dict[str, int]:
        buckets = {
            "0-5": 0,
            "6-10": 0,
            "11-15": 0,
            "16-20": 0,
            "21-25": 0,
            "26-30": 0,
            "31+": 0,
        }
        for value in values:
            if value <= 5:
                buckets["0-5"] += 1
            elif value <= 10:
                buckets["6-10"] += 1
            elif value <= 15:
                buckets["11-15"] += 1
            elif value <= 20:
                buckets["16-20"] += 1
            elif value <= 25:
                buckets["21-25"] += 1
            elif value <= 30:
                buckets["26-30"] += 1
            else:
                buckets["31+"] += 1
        buckets["total"] = len(values)
        return buckets

    response_distribution = {queue: _bucketize(values) for queue, values in hold_distribution.items()}

    summary = {
        "interval": {"start": start.isoformat(sep=" "), "end": end.isoformat(sep=" ")},
        "queues": queues,
        "agents": agents,
        "total_calls": grand_total_calls,
        "avg_talk_time": round(grand_total_time / grand_total_calls, 2) if grand_total_calls else 0,
        "total_talk_minutes": round(grand_total_time / 60, 2),
        "avg_hold_time": round(grand_total_hold / grand_total_calls, 2) if grand_total_calls else 0,
    }

    return JsonResponse(
        {
            "summary": summary,
            "agents": agents_summary,
            "response_distribution": response_distribution,
        }
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST)
def unanswered_report(request: HttpRequest) -> JsonResponse:
    payload = _parse_request_payload(request)
    queues = _normalize_list(payload.get("queues") or payload.get("queue"))
    start = _parse_datetime(payload.get("start")) or datetime.now().replace(hour=0, minute=0, second=0)
    end = _parse_datetime(payload.get("end")) or datetime.now().replace(hour=23, minute=59, second=59)

    rows = _fetch_queuelog_rows(start, end, queues, None, ["ABANDON", "EXITWITHTIMEOUT"])

    total_calls = 0
    total_hold = 0
    total_abandon_calls = 0
    total_timeout_calls = 0
    total_start_pos = 0
    total_end_pos = 0

    abandon_buckets: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for row in rows:
        queue = row["queuename"]
        total_calls += 1
        hold = int(row.get("data3") or 0)
        total_hold += hold
        start_pos = int(row.get("data2") or 0)
        end_pos = int(row.get("data1") or 0)
        total_start_pos += start_pos
        total_end_pos += end_pos

        if row["event"] == "ABANDON":
            total_abandon_calls += 1
            value = int(row.get("data3") or 0)
            if value <= 10:
                abandon_buckets[queue]["0-10"] += 1
            elif value <= 20:
                abandon_buckets[queue]["11-20"] += 1
            elif value <= 30:
                abandon_buckets[queue]["21-30"] += 1
            elif value <= 40:
                abandon_buckets[queue]["31-40"] += 1
            elif value <= 50:
                abandon_buckets[queue]["41-50"] += 1
            elif value <= 60:
                abandon_buckets[queue]["51-60"] += 1
            else:
                abandon_buckets[queue]["61+"] += 1
        elif row["event"] == "EXITWITHTIMEOUT":
            total_timeout_calls += 1

    summary = {
        "interval": {"start": start.isoformat(sep=" "), "end": end.isoformat(sep=" ")},
        "queues": queues,
        "total_unanswered": total_calls,
        "avg_wait_before_disconnect": round(total_hold / total_calls, 2) if total_calls else 0,
        "avg_queue_position_disconnect": round(total_end_pos / total_calls, 2) if total_calls else 0,
        "avg_queue_position_start": round(total_start_pos / total_calls, 2) if total_calls else 0,
        "abandon_percent": round(total_abandon_calls * 100 / total_calls, 2) if total_calls else 0,
        "timeout_percent": round(total_timeout_calls * 100 / total_calls, 2) if total_calls else 0,
    }

    buckets = {
        queue: {
            "0-10": data.get("0-10", 0),
            "11-20": data.get("11-20", 0),
            "21-30": data.get("21-30", 0),
            "31-40": data.get("31-40", 0),
            "41-50": data.get("41-50", 0),
            "51-60": data.get("51-60", 0),
            "61+": data.get("61+", 0),
        }
        for queue, data in abandon_buckets.items()
    }

    return JsonResponse(
        {
            "summary": summary,
            "distribution": buckets,
            "reasons": {
                "abandon_calls": total_abandon_calls,
                "timeout_calls": total_timeout_calls,
            },
        }
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST)
def distribution_report(request: HttpRequest) -> JsonResponse:
    payload = _parse_request_payload(request)
    queues = _normalize_list(payload.get("queues") or payload.get("queue"))
    agents = _normalize_list(payload.get("agents") or payload.get("agent"))
    start = _parse_datetime(payload.get("start")) or datetime.now().replace(hour=0, minute=0, second=0)
    end = _parse_datetime(payload.get("end")) or datetime.now().replace(hour=23, minute=59, second=59)

    rows = _fetch_queuelog_rows(
        start,
        end,
        queues,
        agents,
        ["ENTERQUEUE", "CONNECT", "COMPLETECALLER", "COMPLETEAGENT", "ABANDON", "EXITWITHKEY"],
    )

    timeline: Dict[str, Counter[int]] = defaultdict(Counter)
    agent_calls: Counter[str] = Counter()
    for row in rows:
        queue = row["queuename"]
        event = row["event"]
        if event == "CONNECT":
            agent_calls[row["agent"]] += 1
        hour = row["time"].hour if isinstance(row["time"], datetime) else datetime.fromisoformat(str(row["time"])).hour
        timeline[queue][hour] += 1

    timeline_data = {
        queue: [{"hour": hour, "calls": count} for hour, count in sorted(counter.items())]
        for queue, counter in timeline.items()
    }

    return JsonResponse({"timeline": timeline_data, "agent_calls": dict(agent_calls)})


@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST)
def raw_events(request: HttpRequest) -> JsonResponse:
    payload = _parse_request_payload(request)
    queues = _normalize_list(payload.get("queues") or payload.get("queue"))
    start = _parse_datetime(payload.get("start"))
    end = _parse_datetime(payload.get("end"))
    page, page_size, offset = _pagination_from_payload(payload)

    qs = QueueLog.objects.all()
    if start:
        qs = qs.filter(time__gte=start)
    if end:
        qs = qs.filter(time__lte=end)
    if queues:
        qs = qs.filter(queuename__in=queues)

    total = qs.count()
    records = list(
        qs.values(
            "time",
            "callid",
            "queuename",
            "agent",
            "event",
            "data1",
            "data2",
            "data3",
            "data4",
            "data5",
        )[offset:offset + page_size]
    )
    return JsonResponse({"events": records, "pagination": _pagination_meta(total, page, page_size)})


@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST)
def raw_events_legacy(request: HttpRequest) -> JsonResponse:
    return raw_events(request)


@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST)
def summary_report(request: HttpRequest) -> JsonResponse:
    payload = _parse_request_payload(request)
    queues = _normalize_list(payload.get("queues") or payload.get("queue"))
    start = _parse_datetime(payload.get("start")) or datetime.now().replace(hour=0, minute=0, second=0)
    end = _parse_datetime(payload.get("end")) or datetime.now().replace(hour=23, minute=59, second=59)

    rows = _fetch_queuelog_rows(
        start,
        end,
        queues,
        None,
        ["ENTERQUEUE", "CONNECT", "COMPLETECALLER", "COMPLETEAGENT", "ABANDON", "EXITWITHTIMEOUT"],
    )

    calls_per_queue: Counter[str] = Counter()
    answered_calls = 0
    abandoned_calls = 0
    timeout_calls = 0
    total_wait_time = 0
    total_talk_time = 0

    for row in rows:
        queue = row["queuename"]
        event = row["event"]
        calls_per_queue[queue] += 1
        if event in {"COMPLETECALLER", "COMPLETEAGENT"}:
            answered_calls += 1
            total_wait_time += int(row.get("data1") or 0)
            total_talk_time += int(row.get("data2") or 0)
        elif event == "ABANDON":
            abandoned_calls += 1
        elif event == "EXITWITHTIMEOUT":
            timeout_calls += 1

    total_calls = answered_calls + abandoned_calls + timeout_calls
    summary = {
        "interval": {"start": start.isoformat(sep=" "), "end": end.isoformat(sep=" ")},
        "queues": queues,
        "total_calls": total_calls,
        "answered_calls": answered_calls,
        "abandoned_calls": abandoned_calls,
        "timeout_calls": timeout_calls,
        "service_level": round(answered_calls * 100 / total_calls, 2) if total_calls else 0,
        "avg_wait_time": round(total_wait_time / answered_calls, 2) if answered_calls else 0,
        "avg_talk_time": round(total_talk_time / answered_calls, 2) if answered_calls else 0,
        "calls_per_queue": dict(calls_per_queue),
    }
    return JsonResponse({"summary": summary})

@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST)
def answered_cdr_report(request: HttpRequest) -> JsonResponse:
    payload = _parse_request_payload(request)
    start = _parse_datetime(payload.get("start"))
    end = _parse_datetime(payload.get("end"))
    page, page_size, offset = _pagination_from_payload(payload)

    if not end:
        end = datetime.now().replace(hour=23, minute=59, second=59)
    if not start:
        start = end.replace(hour=0, minute=0, second=0)

    params: List[Any] = [start, end]
    # Assuming disposition 'ANSWERED' for answered calls
    where_clauses = ["disposition = 'ANSWERED'"]

    sql = f"""
        SELECT uniqueid, calldate, src, dst, duration, billsec, recordingfile
        FROM cdr
        WHERE calldate >= %s AND calldate <= %s AND {" AND ".join(where_clauses)}
        ORDER BY calldate DESC
        LIMIT %s OFFSET %s
    """
    count_sql = f"""
        SELECT COUNT(*)
        FROM cdr
        WHERE calldate >= %s AND calldate <= %s AND {" AND ".join(where_clauses)}
    """

    with connections['default'].cursor() as cursor:
        cursor.execute(count_sql, params)
        total = int(cursor.fetchone()[0] or 0)
        cursor.execute(sql, [*params, page_size, offset])
        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description]

    data = [dict(zip(columns, row)) for row in rows]

    return JsonResponse({"data": data, "pagination": _pagination_meta(total, page, page_size)})


@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST)
def unanswered_cdr_report(request: HttpRequest) -> JsonResponse:
    payload = _parse_request_payload(request)
    queues = _normalize_list(payload.get("queues") or payload.get("queue"))
    callerid_search = (payload.get("callerid") or payload.get("callerid_search") or "").strip()
    start = _parse_datetime(payload.get("start"))
    end = _parse_datetime(payload.get("end"))
    page, page_size, offset = _pagination_from_payload(payload)

    if not end:
        end = datetime.now().replace(hour=23, minute=59, second=59)
    if not start:
        start = end.replace(hour=0, minute=0, second=0)
    where = [
        "q.time >= %s",
        "q.time <= %s",
        "q.event IN ('ABANDON','EXITWITHTIMEOUT')",
    ]
    params: List[Any] = [start, end]
    if queues:
        where.append(f"q.queuename IN ({','.join(['%s'] * len(queues))})")
        params.extend(queues)
    if callerid_search:
        where.append(
            """
            EXISTS (
                SELECT 1
                FROM queuelog q2
                WHERE q2.callid = q.callid
                  AND q2.time >= %s AND q2.time <= %s
                  AND q2.event = 'ENTERQUEUE'
                  AND q2.data2 LIKE %s
            )
            """
        )
        params.extend([start, end, f"%{callerid_search}%"])
    where_sql = " AND ".join(where)
    data_sql = f"""
        SELECT q.time, q.callid, q.queuename, q.agent, q.event, q.data1, q.data2, q.data3
        FROM queuelog q
        WHERE {where_sql}
        ORDER BY q.time DESC
        LIMIT %s OFFSET %s
    """
    count_sql = f"SELECT COUNT(*) FROM queuelog q WHERE {where_sql}"

    with connections['default'].cursor() as cursor:
        cursor.execute(count_sql, params)
        total = int(cursor.fetchone()[0] or 0)
        cursor.execute(data_sql, [*params, page_size, offset])
        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description]

        page_records = [dict(zip(columns, row)) for row in rows]
        callids = [str(item.get("callid") or "") for item in page_records]
        caller_map: Dict[str, str] = {}
        if callids:
            placeholders = ",".join(["%s"] * len(callids))
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
                callids,
            )
            for callid, caller in cursor.fetchall():
                caller_map[str(callid)] = str(caller or "")

    for row in page_records:
        row["callerid"] = caller_map.get(str(row.get("callid") or ""), "")

    return JsonResponse({"data": page_records, "pagination": _pagination_meta(total, page, page_size)})


@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST)
def outbound_report(request: HttpRequest) -> JsonResponse:
    payload = _parse_request_payload(request)
    agents = _normalize_list(payload.get("agents") or payload.get("agent"))
    start = _parse_datetime(payload.get("start"))
    end = _parse_datetime(payload.get("end"))
    page, page_size, offset = _pagination_from_payload(payload)

    if not end:
        end = datetime.now().replace(hour=23, minute=59, second=59)
    if not start:
        start = end.replace(hour=0, minute=0, second=0)

    params: List[Any] = [start, end]
    agent_clause = ""
    if agents:
        agent_clause = f" AND cnam IN ({','.join(['%s'] * len(agents))})"
        params.extend(agents)

    where_sql = f"""
        WHERE calldate >= %s AND calldate <= %s
        {agent_clause}
    """
    sql = f"""
        SELECT calldate, uniqueid, billsec, disposition, src, dst, cnum, cnam, recordingfile
        FROM cdr
        {where_sql}
        ORDER BY calldate DESC
        LIMIT %s OFFSET %s
    """
    count_sql = f"SELECT COUNT(*) FROM cdr {where_sql}"
    overview_sql = f"""
        SELECT
            COALESCE(NULLIF(cnum, ''), NULLIF(cnam, ''), 'UNKNOWN') AS agent_key,
            SUM(CASE WHEN disposition = 'ANSWERED' THEN 1 ELSE 0 END) AS answered,
            SUM(CASE WHEN disposition = 'NO ANSWER' THEN 1 ELSE 0 END) AS no_answer,
            SUM(CASE WHEN disposition = 'BUSY' THEN 1 ELSE 0 END) AS busy,
            COUNT(*) AS total
        FROM cdr
        {where_sql}
        GROUP BY agent_key
    """

    with connections['default'].cursor() as cursor:
        cursor.execute(count_sql, params)
        total = int(cursor.fetchone()[0] or 0)
        cursor.execute(sql, [*params, page_size, offset])
        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description]
        cursor.execute(overview_sql, params)
        overview_rows = cursor.fetchall()

    records = [dict(zip(columns, row)) for row in rows]
    overview: Dict[str, Dict[str, int]] = {}
    for agent_key, answered, no_answer, busy, total_count in overview_rows:
        overview[str(agent_key)] = {
            "ANSWERED": int(answered or 0),
            "NO ANSWER": int(no_answer or 0),
            "BUSY": int(busy or 0),
            "TOTAL": int(total_count or 0),
        }

    return JsonResponse({"data": records, "overview": overview, "pagination": _pagination_meta(total, page, page_size)})


@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST)
def dids_report(request: HttpRequest) -> JsonResponse:
    payload = _parse_request_payload(request)
    start = _parse_datetime(payload.get("start"))
    end = _parse_datetime(payload.get("end"))

    if not end:
        end = datetime.now().replace(hour=23, minute=59, second=59)
    if not start:
        start = end.replace(hour=0, minute=0, second=0)

    sql = """
        SELECT callid, event, data1
        FROM queuelog
        WHERE time >= %s AND time <= %s
          AND event IN ('COMPLETEAGENT','COMPLETECALLER','DID','ABANDON')
        ORDER BY callid DESC
    """
    with connections['default'].cursor() as cursor:
        cursor.execute(sql, [start, end])
        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description]

    events_by_call: Dict[str, Dict[str, int]] = defaultdict(lambda: {"ABN": 0, "ANS": 0})
    did_by_call: Dict[str, str] = {}
    for row in [dict(zip(columns, r)) for r in rows]:
        callid = str(row["callid"])
        event = str(row["event"])
        if event == "DID":
            did_by_call[callid] = str(row.get("data1") or "")
        elif event == "ABANDON":
            events_by_call[callid]["ABN"] = 1
        elif event in {"COMPLETEAGENT", "COMPLETECALLER"}:
            events_by_call[callid]["ANS"] = 1

    counts: Dict[str, Dict[str, int]] = defaultdict(lambda: {"ABN": 0, "ANS": 0, "ALL": 0})
    for callid, did in did_by_call.items():
        if not did:
            continue
        counts[did]["ABN"] += events_by_call[callid]["ABN"]
        counts[did]["ANS"] += events_by_call[callid]["ANS"]
        counts[did]["ALL"] += 1

    totals = {"ABN": 0, "ANS": 0, "ALL": 0}
    for value in counts.values():
        totals["ABN"] += value["ABN"]
        totals["ANS"] += value["ANS"]
        totals["ALL"] += value["ALL"]
    counts["Всего"] = totals

    result = [{"did": did, **stats} for did, stats in sorted(counts.items(), key=lambda x: x[0])]
    return JsonResponse({"data": result})


@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST)
def trunks_report(request: HttpRequest) -> JsonResponse:
    payload = _parse_request_payload(request)
    queues = _normalize_list(payload.get("queues") or payload.get("queue"))
    start = _parse_datetime(payload.get("start"))
    end = _parse_datetime(payload.get("end"))

    if not end:
        end = datetime.now().replace(hour=23, minute=59, second=59)
    if not start:
        start = end.replace(hour=0, minute=0, second=0)

    params: List[Any] = [start, end]
    queue_clause = ""
    if queues:
        queue_clause = f" AND dst IN ({','.join(['%s'] * len(queues))})"
        params.extend(queues)

    sql = f"""
        SELECT channel, lastapp
        FROM cdr
        WHERE calldate >= %s AND calldate <= %s
          AND disposition = 'ANSWERED'
          {queue_clause}
    """
    with connections['default'].cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description]

    trunk_stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"ABN": 0, "ANS": 0, "ALL": 0})
    for row in [dict(zip(columns, r)) for r in rows]:
        channel = str(row.get("channel") or "")
        trunk = channel.split("-")[0] if "-" in channel else channel
        lastapp = str(row.get("lastapp") or "")
        if lastapp == "Queue":
            trunk_stats[trunk]["ANS"] += 1
        else:
            trunk_stats[trunk]["ABN"] += 1
        trunk_stats[trunk]["ALL"] += 1

    totals = {"ABN": 0, "ANS": 0, "ALL": 0}
    for value in trunk_stats.values():
        totals["ABN"] += value["ABN"]
        totals["ANS"] += value["ANS"]
        totals["ALL"] += value["ALL"]
    trunk_stats["Всего"] = totals

    result = [{"trunk": trunk, **stats} for trunk, stats in sorted(trunk_stats.items(), key=lambda x: x[0])]
    return JsonResponse({"data": result})


@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST)
def queue_search(request: HttpRequest) -> JsonResponse:
    payload = _parse_request_payload(request)
    callerid = (payload.get("callerid") or "").strip()
    uniqueid = (payload.get("uniqueid") or "").strip()
    include_ringnoanswer = _parse_bool(payload.get("include_ringnoanswer"), default=True)
    alltime = _parse_bool(payload.get("alltime"), default=False)
    start = _parse_datetime(payload.get("start"))
    end = _parse_datetime(payload.get("end"))
    page, page_size, offset = _pagination_from_payload(payload)

    where: List[str] = []
    params: List[Any] = []
    if not alltime:
        if not end:
            end = datetime.now().replace(hour=23, minute=59, second=59)
        if not start:
            start = end.replace(hour=0, minute=0, second=0)
        where.extend(["time >= %s", "time <= %s"])
        params.extend([start, end])

    if callerid:
        where.append("callid IN (SELECT DISTINCT callid FROM queuelog WHERE data2 LIKE %s)")
        params.append(f"%{callerid}%")
    if uniqueid:
        where.append("callid = %s")
        params.append(uniqueid)
    if not include_ringnoanswer:
        where.append("event <> 'RINGNOANSWER'")

    sql = """
        SELECT time, callid, queuename, agent, event, data1, data2, data3, data4, data5
        FROM queuelog
    """
    count_sql = "SELECT COUNT(*) FROM queuelog"
    if where:
        where_sql = " WHERE " + " AND ".join(where)
        sql += where_sql
        count_sql += where_sql
    sql += " ORDER BY time DESC LIMIT %s OFFSET %s"

    with connections['default'].cursor() as cursor:
        cursor.execute(count_sql, params)
        total = int(cursor.fetchone()[0] or 0)
        cursor.execute(sql, [*params, page_size, offset])
        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description]

    return JsonResponse(
        {
            "events": [dict(zip(columns, r)) for r in rows],
            "pagination": _pagination_meta(total, page, page_size),
        }
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST)
def sla_report(request: HttpRequest) -> JsonResponse:
    payload = _parse_request_payload(request)
    queues = _normalize_list(payload.get("queues") or payload.get("queue"))
    start = _parse_datetime(payload.get("start"))
    end = _parse_datetime(payload.get("end"))
    _cfg = GeneralSettings.objects.first()
    default_threshold = int(_cfg.sla_target_wait_seconds) if _cfg else 20
    threshold = int(payload.get("threshold", default_threshold))

    if not end:
        end = datetime.now().replace(hour=23, minute=59, second=59)
    if not start:
        start = (end - timedelta(days=6)).replace(hour=0, minute=0, second=0)

    params: List[Any] = [threshold, start, end]
    queue_clause = ""
    if queues:
        queue_clause = f" AND queuename IN ({','.join(['%s'] * len(queues))})"
        params.extend(queues)

    sql = f"""
        SELECT
            DATE(time) AS day,
            SUM(CASE WHEN event IN ('COMPLETECALLER', 'COMPLETEAGENT') THEN 1 ELSE 0 END) AS total_answered,
            SUM(CASE WHEN event IN ('COMPLETECALLER', 'COMPLETEAGENT') AND CAST(data1 AS UNSIGNED) <= %s THEN 1 ELSE 0 END) AS sla_answered
        FROM queuelog
        WHERE time >= %s AND time <= %s
        AND event IN ('COMPLETECALLER', 'COMPLETEAGENT')
        {queue_clause}
        GROUP BY day
        ORDER BY day
    """

    with connections['default'].cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description]

    daily_data = [dict(zip(columns, row)) for row in rows]

    return JsonResponse(
        {
            "interval": {"start": start.isoformat(sep=" "), "end": end.isoformat(sep=" ")},
            "queues": queues,
            "threshold": threshold,
            "daily": daily_data,
        }
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST)
def volume_report(request: HttpRequest) -> JsonResponse:
    payload = _parse_request_payload(request)
    queues = _normalize_list(payload.get("queues") or payload.get("queue"))
    start = _parse_datetime(payload.get("start"))
    end = _parse_datetime(payload.get("end"))

    if not end:
        end = datetime.now().replace(hour=23, minute=59, second=59)
    if not start:
        start = (end - timedelta(days=6)).replace(hour=0, minute=0, second=0)

    params: List[Any] = [start, end]
    queue_clause = ""
    if queues:
        queue_clause = f" AND queuename IN ({','.join(['%s'] * len(queues))})"
        params.extend(queues)

    sql_daily = f"""
        SELECT DATE(time) AS day,
            SUM(CASE WHEN event IN ('COMPLETECALLER','COMPLETEAGENT') THEN 1 ELSE 0 END) AS answered,
            SUM(CASE WHEN event IN ('ABANDON','EXITWITHTIMEOUT') THEN 1 ELSE 0 END) AS unanswered
        FROM queuelog
        WHERE time >= %s AND time <= %s
        {queue_clause}
        GROUP BY day
        ORDER BY day
    """

    sql_hourly = f"""
        SELECT DATE(time) AS day, HOUR(time) AS hour,
            SUM(CASE WHEN event IN ('COMPLETECALLER','COMPLETEAGENT') THEN 1 ELSE 0 END) AS answered,
            SUM(CASE WHEN event IN ('ABANDON','EXITWITHTIMEOUT') THEN 1 ELSE 0 END) AS unanswered
        FROM queuelog
        WHERE time >= %s AND time <= %s
        {queue_clause}
        GROUP BY day, hour
        ORDER BY day, hour
    """

    sql_queue = f"""
        SELECT queuename,
            SUM(CASE WHEN event IN ('COMPLETECALLER','COMPLETEAGENT') THEN 1 ELSE 0 END) AS answered,
            SUM(CASE WHEN event IN ('ABANDON','EXITWITHTIMEOUT') THEN 1 ELSE 0 END) AS unanswered
        FROM queuelog
        WHERE time >= %s AND time <= %s
        {queue_clause}
        GROUP BY queuename
        ORDER BY answered DESC
    """

    with connections['default'].cursor() as cursor:
        cursor.execute(sql_daily, params)
        daily_rows = cursor.fetchall()
        daily_columns = [col[0] for col in cursor.description]

        cursor.execute(sql_hourly, params)
        hourly_rows = cursor.fetchall()
        hourly_columns = [col[0] for col in cursor.description]

        cursor.execute(sql_queue, params)
        queue_rows = cursor.fetchall()
        queue_columns = [col[0] for col in cursor.description]

    daily = [dict(zip(daily_columns, row)) for row in daily_rows]
    hourly = [dict(zip(hourly_columns, row)) for row in hourly_rows]
    per_queue = [dict(zip(queue_columns, row)) for row in queue_rows]

    return JsonResponse(
        {
            "interval": {"start": start.isoformat(sep=" "), "end": end.isoformat(sep=" ")},
            "queues": queues,
            "daily": daily,
            "hourly": hourly,
            "per_queue": per_queue,
        }
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST)
def agent_performance_report(request: HttpRequest) -> JsonResponse:
    payload = _parse_request_payload(request)
    queues = _normalize_list(payload.get("queues") or payload.get("queue"))
    agents = _normalize_list(payload.get("agents") or payload.get("agent"))
    start = _parse_datetime(payload.get("start"))
    end = _parse_datetime(payload.get("end"))

    if not end:
        end = datetime.now().replace(hour=23, minute=59, second=59)
    if not start:
        start = (end - timedelta(days=6)).replace(hour=0, minute=0, second=0)

    params: List[Any] = [start, end]
    queue_clause = ""
    agent_clause = ""
    if queues:
        queue_clause = f" AND queuename IN ({','.join(['%s'] * len(queues))})"
        params.extend(queues)
    if agents:
        agent_clause = f" AND agent IN ({','.join(['%s'] * len(agents))})"
        params.extend(agents)

    sql_agents = f"""
        SELECT agent,
            SUM(CASE WHEN event IN ('COMPLETECALLER','COMPLETEAGENT') THEN 1 ELSE 0 END) AS answered_calls,
            SUM(CASE WHEN event IN ('COMPLETECALLER','COMPLETEAGENT') THEN CAST(data1 AS UNSIGNED) ELSE 0 END) AS wait_time,
            SUM(CASE WHEN event IN ('COMPLETECALLER','COMPLETEAGENT') THEN CAST(data2 AS UNSIGNED) ELSE 0 END) AS talk_time
        FROM queuelog
        WHERE time >= %s AND time <= %s
        {queue_clause}
        {agent_clause}
        AND agent IS NOT NULL AND agent <> ''
        GROUP BY agent
        ORDER BY answered_calls DESC
    """

    sql_trends = f"""
        SELECT agent,
            DATE(time) AS day,
            SUM(CASE WHEN event IN ('COMPLETECALLER','COMPLETEAGENT') THEN 1 ELSE 0 END) AS answered_calls
        FROM queuelog
        WHERE time >= %s AND time <= %s
        {queue_clause}
        {agent_clause}
        AND agent IS NOT NULL AND agent <> ''
        GROUP BY agent, day
        ORDER BY agent, day
    """

    with connections['default'].cursor() as cursor:
        cursor.execute(sql_agents, params)
        agent_rows = cursor.fetchall()
        agent_columns = [col[0] for col in cursor.description]

        cursor.execute(sql_trends, params)
        trend_rows = cursor.fetchall()
        trend_columns = [col[0] for col in cursor.description]

    agents_stats = []
    for row in agent_rows:
        record = dict(zip(agent_columns, row))
        calls = record["answered_calls"] or 0
        talk_time = record["talk_time"] or 0
        wait_time = record["wait_time"] or 0
        record["avg_talk_time"] = round(talk_time / calls, 2) if calls else 0
        record["avg_wait_time"] = round(wait_time / calls, 2) if calls else 0
        agents_stats.append(record)

    trends = [dict(zip(trend_columns, row)) for row in trend_rows]

    return JsonResponse(
        {
            "interval": {"start": start.isoformat(sep=" "), "end": end.isoformat(sep=" ")},
            "queues": queues,
            "agents_filter": agents,
            "agents": agents_stats,
            "trends": trends,
        }
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST)
def areport_legacy(request: HttpRequest) -> JsonResponse:
    payload = _parse_request_payload(request)
    queues = _normalize_list(payload.get("queues") or payload.get("queue"))
    agents_filter = _normalize_list(payload.get("agents") or payload.get("agent"))
    start = _parse_datetime(payload.get("start"))
    end = _parse_datetime(payload.get("end"))

    if not end:
        end = datetime.now().replace(hour=23, minute=59, second=59)
    if not start:
        start = (end - timedelta(days=6)).replace(hour=0, minute=0, second=0)

    params: List[Any] = [start, end]
    queue_clause = ""
    agent_clause = ""
    if queues:
        queue_clause = f" AND queuename IN ({','.join(['%s'] * len(queues))})"
        params.extend(queues)
    if agents_filter:
        agent_clause = f" AND agent IN ({','.join(['%s'] * len(agents_filter))})"
        params.extend(agents_filter)

    sql = f"""
        SELECT time, callid, agent, event, data1, data2, data3, data4
        FROM queuelog
        WHERE time >= %s AND time <= %s
          {queue_clause}
          {agent_clause}
          AND agent IS NOT NULL AND agent <> ''
        ORDER BY time
    """

    with connections['default'].cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description]

    by_day_agent: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(
        lambda: defaultdict(
            lambda: {
                "talk_sec": 0,
                "calls": 0,
                "pause_start": None,
                "pause_sec": 0,
                "transfer_hold_sec": 0,
                "rna": 0,
                "add_times": [],
                "remove_times": [],
            }
        )
    )

    for row in [dict(zip(columns, r)) for r in rows]:
        dt = row.get("time")
        if not isinstance(dt, datetime):
            dt = datetime.fromisoformat(str(dt))
        day = dt.date().isoformat()
        agent = str(row.get("agent") or "").strip()
        event = str(row.get("event") or "")
        bucket = by_day_agent[day][agent]

        if event in {"COMPLETECALLER", "COMPLETEAGENT"}:
            bucket["talk_sec"] += int(row.get("data2") or 0)
            bucket["calls"] += 1
        elif event == "PAUSE":
            bucket["pause_start"] = dt
        elif event == "UNPAUSE":
            pause_start = bucket.get("pause_start")
            if isinstance(pause_start, datetime) and dt >= pause_start:
                bucket["pause_sec"] += int((dt - pause_start).total_seconds())
            bucket["pause_start"] = None
        elif event in {"BLINDTRANSFER", "ATTENDEDTRANSFER"}:
            bucket["transfer_hold_sec"] += int(row.get("data3") or 0) + int(row.get("data4") or 0)
        elif event == "RINGNOANSWER" and int(row.get("data1") or 0) > 1500:
            bucket["rna"] += 1
        elif event == "ADDMEMBER" and str(row.get("callid") or "") == "MANAGER":
            bucket["add_times"].append(dt)
        elif event == "REMOVEMEMBER" and str(row.get("callid") or "") == "MANAGER":
            bucket["remove_times"].append(dt)

    _cfg = GeneralSettings.objects.first()
    if _cfg:
        from datetime import date, time as _time
        _bds = _cfg.business_day_start or _time(9, 0)
        _bde = _cfg.business_day_end or _time(18, 0)
        _default_work_sec = int(
            (datetime.combine(date.today(), _bde) - datetime.combine(date.today(), _bds)).total_seconds()
        )
    else:
        _default_work_sec = 9 * 3600

    rows_out: List[Dict[str, Any]] = []
    for day in sorted(by_day_agent.keys()):
        for agent in sorted(by_day_agent[day].keys()):
            bucket = by_day_agent[day][agent]
            add_times = sorted(bucket["add_times"])
            remove_times = sorted(bucket["remove_times"])
            if add_times and remove_times:
                work_sec = max(0, int((remove_times[-1] - add_times[0]).total_seconds()))
            else:
                work_sec = _default_work_sec
            free_sec = max(0, work_sec - bucket["talk_sec"] - bucket["pause_sec"])
            calls = bucket["calls"]
            rows_out.append(
                {
                    "day": day,
                    "agent": agent,
                    "incall_min": round(bucket["talk_sec"] / 60),
                    "pause_min": round(bucket["pause_sec"] / 60),
                    "free_min": round(free_sec / 60),
                    "transfer_hold_min": round(bucket["transfer_hold_sec"] / 60),
                    "calls": calls,
                    "avg_talk_sec": round(bucket["talk_sec"] / calls, 2) if calls else 0,
                    "rna": bucket["rna"],
                }
            )

    return JsonResponse(
        {
            "interval": {"start": start.isoformat(sep=" "), "end": end.isoformat(sep=" ")},
            "queues": queues,
            "agents_filter": agents_filter,
            "rows": rows_out,
        }
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST)
def qreport_legacy(request: HttpRequest) -> JsonResponse:
    payload = _parse_request_payload(request)
    queues = _normalize_list(payload.get("queues") or payload.get("queue"))
    start = _parse_datetime(payload.get("start"))
    end = _parse_datetime(payload.get("end"))

    if not end:
        end = datetime.now().replace(hour=23, minute=59, second=59)
    if not start:
        start = (end - timedelta(days=6)).replace(hour=0, minute=0, second=0)

    params: List[Any] = [start, end]
    queue_clause = ""
    if queues:
        queue_clause = f" AND queuename IN ({','.join(['%s'] * len(queues))})"
        params.extend(queues)

    sql = f"""
        SELECT time, agent, queuename, event, data3
        FROM queuelog
        WHERE time >= %s AND time <= %s
          {queue_clause}
          AND event IN ('CONNECT', 'ENTERQUEUE', 'COMPLETECALLER', 'COMPLETEAGENT', 'RINGNOANSWER')
        ORDER BY time
    """

    with connections['default'].cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description]

    by_day_hour: Dict[str, Dict[int, Dict[str, Any]]] = defaultdict(lambda: defaultdict(lambda: {"dep": 0, "agents": set()}))
    for row in [dict(zip(columns, r)) for r in rows]:
        dt = row.get("time")
        if not isinstance(dt, datetime):
            dt = datetime.fromisoformat(str(dt))
        day = dt.date().isoformat()
        hour = dt.hour
        event = str(row.get("event") or "")

        if event == "ENTERQUEUE":
            depth = int(row.get("data3") or 0)
            if depth > by_day_hour[day][hour]["dep"]:
                by_day_hour[day][hour]["dep"] = depth
        if event in {"COMPLETECALLER", "COMPLETEAGENT", "RINGNOANSWER"}:
            agent = str(row.get("agent") or "").strip()
            if agent:
                by_day_hour[day][hour]["agents"].add(agent)

    result: List[Dict[str, Any]] = []
    for day in sorted(by_day_hour.keys()):
        dep = {str(h): int(by_day_hour[day][h]["dep"]) for h in range(24)}
        agents = {str(h): len(by_day_hour[day][h]["agents"]) for h in range(24)}
        result.append({"day": day, "dep": dep, "agents": agents})

    return JsonResponse(
        {
            "interval": {"start": start.isoformat(sep=" "), "end": end.isoformat(sep=" ")},
            "queues": queues,
            "rows": result,
        }
    )


def _ami_response(action: str, **params: Any) -> Dict[str, Any]:
    general_settings = GeneralSettings.objects.first()
    if not general_settings or not general_settings.ami_host:
        return {"error": "AMI settings not configured in admin panel."}

    try:
        with AmiClient(
            host=general_settings.ami_host,
            port=general_settings.ami_port,
            username=general_settings.ami_user,
            secret=general_settings.ami_password,
        ) as client:
            return client.send_action(action, **params)
    except (socket.error, ConnectionRefusedError, Exception) as exc:
        return {"error": str(exc), "action": action}


@require_GET
@login_required_json
def active_calls(request: HttpRequest) -> JsonResponse:
    if request.user.role not in {UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST, UserRoles.AGENT}:
        return JsonResponse({"detail": "forbidden"}, status=403)
    data = _ami_response("CoreShowChannels")
    return JsonResponse(data)


@require_GET
@login_required_json
def active_calls_legacy(request: HttpRequest) -> JsonResponse:
    return active_calls(request)


@require_GET
@login_required_json
def queue_status(request: HttpRequest) -> JsonResponse:
    if request.user.role not in {UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST, UserRoles.AGENT}:
        return JsonResponse({"detail": "forbidden"}, status=403)
    data = _ami_response("QueueStatus")
    return JsonResponse(data)


@require_GET
@login_required_json
def queue_status_legacy(request: HttpRequest) -> JsonResponse:
    return queue_status(request)


@require_GET
@login_required_json
def queue_summary(request: HttpRequest) -> JsonResponse:
    if request.user.role not in {UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST, UserRoles.AGENT}:
        return JsonResponse({"detail": "forbidden"}, status=403)
    data = _ami_response("QueueSummary")
    return JsonResponse(data)


@require_GET
@login_required_json
def get_recording(request: HttpRequest, uniqueid: str) -> FileResponse:
    settings = GeneralSettings.objects.first()
    if not settings or not settings.download_url:
        raise Http404("Recording download service not configured in admin panel.")

    # Sanitize uniqueid to prevent security issues
    if not uniqueid or not all(c.isalnum() or c in ".-" for c in uniqueid):
        raise Http404("Invalid uniqueid")

    with connections['default'].cursor() as cursor:
        cursor.execute("SELECT recordingfile FROM cdr WHERE uniqueid = %s", [uniqueid])
        row = cursor.fetchone()

    if not row or not row[0]:
        raise Http404("Recording not found in CDR database.")

    recording_path = row[0]
    if not recording_path:
        raise Http404("Recording file path is empty in CDR database.")

    params = {
        "url": recording_path,
        "token": settings.download_token,
    }

    auth = (settings.download_user, settings.download_password)

    try:
        response = requests.get(settings.download_url, params=params, auth=auth, stream=True, timeout=10)
        response.raise_for_status()  # Raise an exception for bad status codes

        # Stream the response back to the client
        return StreamingHttpResponse(
            response.iter_content(chunk_size=8192),
            content_type=response.headers.get("Content-Type"),
            status=response.status_code,
            reason=response.reason,
        )
    except requests.RequestException as e:
        raise Http404(f"Failed to fetch recording from download service: {e}")
