from django.urls import path

from . import ui_views
from . import exports

urlpatterns = [
    path("", ui_views.home, name="home"),
    path("login/", ui_views.web_login, name="web-login"),
    path("logout/", ui_views.web_logout, name="web-logout"),

    path("reports/summary/", ui_views.report_summary_page, name="report-summary-page"),
    path("reports/answered/", ui_views.report_answered_page, name="report-answered-page"),
    path("reports/unanswered/", ui_views.report_unanswered_page, name="report-unanswered-page"),
    path("reports/cdr/", ui_views.report_cdr_page, name="report-cdr-page"),
    path("reports/outbound/", ui_views.report_outbound_page, name="report-outbound-page"),
    path("calls/<str:callid>/", ui_views.call_detail_page, name="call-detail-page"),
    path("calls/<str:callid>/transcription/start/", ui_views.call_transcription_start, name="call-transcription-start"),
    path("calls/<str:callid>/transcription/status/", ui_views.call_transcription_status, name="call-transcription-status"),
    path("realtime/", ui_views.realtime_page, name="realtime-page"),
    path("analytics/", ui_views.analytics_page, name="analytics-page"),
    path("payouts/", ui_views.payouts_page, name="payouts-page"),
    path("dashboards/", ui_views.dashboards_page, name="dashboards-page"),
    path("dashboards/traffic/", ui_views.dashboard_traffic_page, name="dashboard-traffic-page"),
    path("dashboards/queues/", ui_views.dashboard_queues_page, name="dashboard-queues-page"),
    path("dashboards/operators/", ui_views.dashboard_operators_page, name="dashboard-operators-page"),
    path("settings/", ui_views.settings_page, name="settings-page"),
    path("mappings/", ui_views.mappings_page, name="mappings-page"),

    path("recordings/<str:uniqueid>/stream/", ui_views.recording_stream, name="recording-stream"),
    path("ui/partials/realtime-oob/", ui_views.realtime_oob_partial, name="ui-realtime-oob"),

    path("ui/exports/answered.xlsx", exports.export_answered_excel, name="ui-export-answered-xlsx"),
    path("ui/exports/answered.pdf", exports.export_answered_pdf, name="ui-export-answered-pdf"),
    path("ui/exports/unanswered.xlsx", exports.export_unanswered_excel, name="ui-export-unanswered-xlsx"),
    path("ui/exports/unanswered.pdf", exports.export_unanswered_pdf, name="ui-export-unanswered-pdf"),
    path("ui/exports/cdr.xlsx", exports.export_cdr_excel, name="ui-export-cdr-xlsx"),
    path("ui/exports/cdr.pdf", exports.export_cdr_pdf, name="ui-export-cdr-pdf"),
    path("ui/exports/outbound.xlsx", exports.export_outbound_excel, name="ui-export-outbound-xlsx"),
    path("ui/exports/outbound.pdf", exports.export_outbound_pdf, name="ui-export-outbound-pdf"),
    path("ui/exports/dashboard-traffic.xlsx", exports.export_dashboard_traffic_excel, name="ui-export-dashboard-traffic-xlsx"),
    path("ui/exports/dashboard-traffic.pdf", exports.export_dashboard_traffic_pdf, name="ui-export-dashboard-traffic-pdf"),
    path("ui/exports/dashboard-queues.xlsx", exports.export_dashboard_queues_excel, name="ui-export-dashboard-queues-xlsx"),
    path("ui/exports/dashboard-queues.pdf", exports.export_dashboard_queues_pdf, name="ui-export-dashboard-queues-pdf"),
    path("ui/exports/dashboard-operators.xlsx", exports.export_dashboard_operators_excel, name="ui-export-dashboard-operators-xlsx"),
    path("ui/exports/dashboard-operators.pdf", exports.export_dashboard_operators_pdf, name="ui-export-dashboard-operators-pdf"),
    path("ui/exports/analytics.xlsx", exports.export_analytics_excel, name="ui-export-analytics-xlsx"),
    path("ui/exports/analytics.pdf", exports.export_analytics_pdf, name="ui-export-analytics-pdf"),
]
