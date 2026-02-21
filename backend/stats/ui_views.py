from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import connections
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from accounts.models import UserRoles
from settings.models import GeneralSettings
from .ami_manager import AMIManager
from .views import _fetch_queuelog_rows, _normalize_list, _parse_datetime


def _user_allowed(request: HttpRequest) -> bool:
    return request.user.is_authenticated and request.user.role in {
        UserRoles.ADMIN,
        UserRoles.SUPERVISOR,
        UserRoles.ANALYST,
        UserRoles.AGENT,
    }


def _interval_from_request(request: HttpRequest) -> tuple[datetime, datetime]:
    start = _parse_datetime(request.GET.get("start"))
    end = _parse_datetime(request.GET.get("end"))
    if not end:
        end = datetime.now().replace(hour=23, minute=59, second=59)
    if not start:
        start = end.replace(hour=0, minute=0, second=0)
    return start, end


def _answered_dataset(request: HttpRequest) -> Dict[str, Any]:
    start, end = _interval_from_request(request)
    queues = _normalize_list(request.GET.get("queues"))
    agents = _normalize_list(request.GET.get("agents"))

    rows = _fetch_queuelog_rows(start, end, queues, agents, ["COMPLETECALLER", "COMPLETEAGENT"])
    flat_rows: List[Dict[str, Any]] = []
    for row in rows:
        flat_rows.append(
            {
                "time": row.get("time"),
                "queue": row.get("queuename"),
                "agent": row.get("agent"),
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
        "queues": queues,
        "agents": agents,
        "rows": flat_rows[:500],
        "total": total,
        "avg_hold": avg_hold,
        "avg_talk": avg_talk,
    }


def _unanswered_dataset(request: HttpRequest) -> Dict[str, Any]:
    start, end = _interval_from_request(request)
    queues = _normalize_list(request.GET.get("queues"))
    rows = _fetch_queuelog_rows(start, end, queues, None, ["ABANDON", "EXITWITHTIMEOUT"])

    flat_rows: List[Dict[str, Any]] = []
    for row in rows:
        flat_rows.append(
            {
                "time": row.get("time"),
                "queue": row.get("queuename"),
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
        "queues": queues,
        "rows": flat_rows[:500],
        "total": total,
        "avg_wait": avg_wait,
    }


def _cdr_dataset(request: HttpRequest) -> Dict[str, Any]:
    start, end = _interval_from_request(request)
    sql = """
        SELECT uniqueid, calldate, src, dst, duration, billsec, disposition, recordingfile
        FROM cdr
        WHERE calldate >= %s AND calldate <= %s
        ORDER BY calldate DESC
        LIMIT 2000
    """
    with connections["default"].cursor() as cursor:
        cursor.execute(sql, [start, end])
        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description]
    data = [dict(zip(columns, row)) for row in rows]
    return {"start": start, "end": end, "rows": data[:500], "total": len(data)}


def _summary_dataset(request: HttpRequest) -> Dict[str, Any]:
    start, end = _interval_from_request(request)
    queues = _normalize_list(request.GET.get("queues"))
    rows = _fetch_queuelog_rows(
        start,
        end,
        queues,
        None,
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
    return {
        "start": start,
        "end": end,
        "queues": queues,
        "total": total,
        "answered": answered,
        "abandoned": abandoned,
        "timeout": timeout,
        "service_level": round(answered * 100 / total, 2) if total else 0,
        "avg_wait": round(wait_total / answered, 2) if answered else 0,
        "avg_talk": round(talk_total / answered, 2) if answered else 0,
        "per_queue": [{"queue": k, **v} for k, v in sorted(by_queue.items(), key=lambda item: item[0])],
    }


def _build_ami_snapshot() -> Dict[str, Any]:
    settings = GeneralSettings.objects.first()
    if not settings or not settings.ami_host:
        return {"queue_summary": [], "active_calls": [], "ami_error": "AMI не настроен"}

    manager = AMIManager(
        host=settings.ami_host,
        port=settings.ami_port,
        username=settings.ami_user,
        secret=settings.ami_password,
    )

    if not manager.connect():
        return {"queue_summary": [], "active_calls": [], "ami_error": "Нет соединения с AMI"}

    try:
        summary_raw = manager.queue_summary().get("summary", [])
        channels_raw = manager.core_show_channels().get("channels", [])
    finally:
        manager.disconnect()

    queue_summary: List[Dict[str, Any]] = []
    for row in summary_raw:
        if str(row.get("Event", "")) != "QueueSummary":
            continue
        queue_summary.append(
            {
                "queue": row.get("Queue", ""),
                "logged_in": row.get("LoggedIn", "0"),
                "available": row.get("Available", "0"),
                "callers": row.get("Callers", "0"),
                "hold_time": row.get("HoldTime", "0"),
                "longest_hold": row.get("LongestHoldTime", "0"),
            }
        )

    active_calls: List[Dict[str, Any]] = []
    for row in channels_raw:
        if str(row.get("Event", "")) != "CoreShowChannel":
            continue
        active_calls.append(
            {
                "channel": row.get("Channel", ""),
                "caller": row.get("CallerIDNum", ""),
                "connected": row.get("ConnectedLineNum", ""),
                "duration": row.get("Duration", ""),
                "application": row.get("Application", ""),
            }
        )

    return {"queue_summary": queue_summary, "active_calls": active_calls, "ami_error": ""}


def web_login(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("dashboard")

    context: Dict[str, Any] = {}
    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        user = authenticate(request, username=username, password=password)
        if user is None:
            context["error"] = "Неверный логин или пароль"
        else:
            login(request, user)
            return redirect("dashboard")

    return render(request, "stats/login.html", context)


@login_required
def web_logout(request: HttpRequest) -> HttpResponse:
    logout(request)
    return redirect("web-login")


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)

    queues: List[str] = []
    with connections["default"].cursor() as cursor:
        try:
            cursor.execute("SELECT queuename FROM queues_new ORDER BY queuename")
            queues = [str(row[0]) for row in cursor.fetchall()]
        except Exception:
            queues = []

    now = datetime.now()
    context = {
        "queues": queues,
        "default_start": now.replace(hour=0, minute=0, second=0).strftime("%Y-%m-%d %H:%M:%S"),
        "default_end": now.replace(hour=23, minute=59, second=59).strftime("%Y-%m-%d %H:%M:%S"),
    }
    context.update(_build_ami_snapshot())
    return render(request, "stats/dashboard.html", context)


@login_required
def summary_partial(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    return render(request, "stats/partials/summary_report.html", _summary_dataset(request))


@login_required
def answered_partial(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    return render(request, "stats/partials/answered_report.html", _answered_dataset(request))


@login_required
def unanswered_partial(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    return render(request, "stats/partials/unanswered_report.html", _unanswered_dataset(request))


@login_required
def cdr_partial(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    return render(request, "stats/partials/cdr_report.html", _cdr_dataset(request))


@login_required
def export_answered_excel(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)

    data = _answered_dataset(request)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Answered"
    sheet.append(["time", "queue", "agent", "hold_sec", "talk_sec"])
    for row in data["rows"]:
        sheet.append([row["time"], row["queue"], row["agent"], row["hold"], row["talk"]])

    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    response = HttpResponse(
        output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
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
    sheet.append(["time", "queue", "event", "start_pos", "end_pos", "wait_sec"])
    for row in data["rows"]:
        sheet.append([row["time"], row["queue"], row["event"], row["start_pos"], row["end_pos"], row["wait_sec"]])

    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    response = HttpResponse(
        output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
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
    sheet.append(["uniqueid", "calldate", "src", "dst", "duration", "billsec", "disposition", "recordingfile"])
    for row in data["rows"]:
        sheet.append(
            [
                row.get("uniqueid"),
                row.get("calldate"),
                row.get("src"),
                row.get("dst"),
                row.get("duration"),
                row.get("billsec"),
                row.get("disposition"),
                row.get("recordingfile"),
            ]
        )

    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    response = HttpResponse(
        output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="cdr_report.xlsx"'
    return response


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
    for row in rows[:120]:
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


@login_required
def export_answered_pdf(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)

    data = _answered_dataset(request)
    pdf_data = _draw_table_pdf(
        "Answered Report",
        ["time", "queue", "agent", "hold_sec", "talk_sec"],
        [[r["time"], r["queue"], r["agent"], r["hold"], r["talk"]] for r in data["rows"]],
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
        ["time", "queue", "event", "start_pos", "end_pos", "wait_sec"],
        [[r["time"], r["queue"], r["event"], r["start_pos"], r["end_pos"], r["wait_sec"]] for r in data["rows"]],
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
        ["uniqueid", "calldate", "src", "dst", "duration", "billsec", "disp"],
        [
            [
                r.get("uniqueid"),
                r.get("calldate"),
                r.get("src"),
                r.get("dst"),
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
def realtime_oob_partial(request: HttpRequest) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    return render(request, "stats/partials/realtime_oob.html", _build_ami_snapshot())
