from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List
import os
from django.http import FileResponse, Http404

from settings.models import GeneralSettings

import requests
from django.conf import settings
from django.db import connections
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from accounts.models import UserRoles
from accounts.permissions import login_required_json, require_roles
from .models import AgentsNew, QueueLog, QueuesNew

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
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return default


def _normalize_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, Iterable):
        return [str(item).strip() for item in value]
    return []


@require_GET
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST, UserRoles.AGENT)
def queues_list(request: HttpRequest) -> JsonResponse:
    items = list(QueuesNew.objects.order_by("queuename").values("queuename"))
    for item in items:
        item['descr'] = item['queuename']
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
        SELECT time, queuename, agent, event, data1, data2, data3
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
    with connections['asterisk'].cursor() as cursor:
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

    qs = QueueLog.objects.all()
    if start:
        qs = qs.filter(time__gte=start)
    if end:
        qs = qs.filter(time__lte=end)
    if queues:
        qs = qs.filter(queuename__in=queues)

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
        )[:1000]
    )
    return JsonResponse({"events": records})


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
    return JsonResponse(summary)

@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST)
def answered_cdr_report(request: HttpRequest) -> JsonResponse:
    payload = _parse_request_payload(request)
    start = _parse_datetime(payload.get("start"))
    end = _parse_datetime(payload.get("end"))

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
        LIMIT 1000
    """

    with connections['asterisk'].cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description]

    data = [dict(zip(columns, row)) for row in rows]

    return JsonResponse({"data": data})


@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST)
def sla_report(request: HttpRequest) -> JsonResponse:
    payload = _parse_request_payload(request)
    queues = _normalize_list(payload.get("queues") or payload.get("queue"))
    start = _parse_datetime(payload.get("start"))
    end = _parse_datetime(payload.get("end"))
    threshold = int(payload.get("threshold", 20))

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

    with connections['asterisk'].cursor() as cursor:
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

    with connections['asterisk'].cursor() as cursor:
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

    with connections['asterisk'].cursor() as cursor:
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


import socket

class AmiClient:
    def __init__(self, host, port, username, secret):
        self.host = host
        self.port = port
        self.username = username
        self.secret = secret
        self.socket = None

    def __enter__(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.host, self.port))
        # Read the initial "Asterisk Call Manager..." line
        self.socket.recv(1024)

        login_action = f"Action: Login\r\nUsername: {self.username}\r\nSecret: {self.secret}\r\n\r\n"
        self.socket.sendall(login_action.encode())
        login_response = self._read_response()
        if "Success" not in login_response:
            raise ConnectionRefusedError(f"AMI Login failed: {login_response}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.socket:
            logoff_action = "Action: Logoff\r\n\r\n"
            self.socket.sendall(logoff_action.encode())
            self.socket.close()

    def _read_response(self):
        response = ""
        while True:
            data = self.socket.recv(1024).decode()
            response += data
            if "\r\n\r\n" in response:
                break
        return response

    def send_action(self, action: str, **params: Any) -> Dict[str, Any]:
        action_str = f"Action: {action}\r\n"
        for key, value in params.items():
            action_str += f"{key}: {value}\r\n"
        action_str += "\r\n"
        self.socket.sendall(action_str.encode())

        response_data = ""
        while True:
            chunk = self.socket.recv(4096).decode()
            response_data += chunk
            if response_data.endswith("--END COMMAND--\r\n\r\n") or action in ["QueueStatus", "CoreShowChannels"] and response_data.endswith("\r\n\r\n"):
                 # Some commands dont have a clear end marker, we depend on a timeout from the socket
                 # For now we assume the double crlf is enough for our commands.
                 break
        return self._parse_response(response_data)

    def _parse_response(self, payload: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        entries: List[Dict[str, str]] = []
        current: Dict[str, str] = {}

        for line in payload.splitlines():
            line = line.strip()
            if not line or line.startswith("--END COMMAND--"):
                continue

            if line.startswith("Event:") or line.startswith("Response:") or line.startswith("Channel:"):
                if current:
                    entries.append(current)
                current = {}

            if ":" in line:
                key, value = line.split(":", 1)
                current[key.strip()] = value.strip()

        if current:
            entries.append(current)
        result["entries"] = entries
        return result

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
def queue_status(request: HttpRequest) -> JsonResponse:
    if request.user.role not in {UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST, UserRoles.AGENT}:
        return JsonResponse({"detail": "forbidden"}, status=403)
    data = _ami_response("QueueStatus")
    return JsonResponse(data)


@require_GET
@login_required_json
def queue_summary(request: HttpRequest) -> JsonResponse:
    if request.user.role not in {UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST, UserRoles.AGENT}:
        return JsonResponse({"detail": "forbidden"}, status=403)
    data = _ami_response("QueueSummary")
    return JsonResponse(data)


from django.http import StreamingHttpResponse

def get_recording(request: HttpRequest, uniqueid: str) -> FileResponse:
    settings = GeneralSettings.objects.first()
    if not settings or not settings.download_url:
        raise Http404("Recording download service not configured in admin panel.")

    # Sanitize uniqueid to prevent security issues
    if not uniqueid or not all(c.isalnum() or c in ".-" for c in uniqueid):
        raise Http404("Invalid uniqueid")

    with connections['asterisk'].cursor() as cursor:
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