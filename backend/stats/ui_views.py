from typing import Any, Dict
import os
import mimetypes
from pathlib import Path
import logging
from datetime import datetime

import requests
from django.shortcuts import render, redirect
from django.http import HttpRequest, HttpResponse, Http404, StreamingHttpResponse, FileResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.conf import settings as django_settings
from django.db.models import QuerySet

from settings.models import QueueDisplayMapping, AgentDisplayMapping, OperatorPayoutRate, GeneralSettings

from .helpers import (
    _get_general_settings,
    _user_allowed,
    _admin_allowed,
    _display_agent,
    _agent_map,
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
def call_detail_page(request: HttpRequest, callid: str) -> HttpResponse:
    if not _user_allowed(request):
        return HttpResponse("forbidden", status=403)
    if not callid or not all(c.isalnum() or c in ".-_:" for c in callid):
        raise Http404("Invalid callid")

    notice = ""
    error = ""
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip().lower()
        if action == "transcribe":
            ok, message = _transcribe_call(callid)
            if ok:
                notice = message
            else:
                error = message

    dataset = call_detail_dataset(callid)
    should_autotranscribe = (
        request.method != "POST"
        and dataset.get("transcription_configured")
        and bool(dataset.get("cdr") and dataset["cdr"].get("has_recording"))
        and dataset.get("transcription") is None
    )
    if should_autotranscribe:
        ok, message = _transcribe_call(callid)
        if ok:
            notice = message
        else:
            error = message
        dataset = call_detail_dataset(callid)

    context = _base_context(request)
    context.update(dataset)
    context["notice"] = notice
    context["error"] = error
    return render(request, "stats/reports/call_detail_page.html", context)


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

    context = _base_context(request)
    payout_rows = []
    amap = _agent_map()
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
