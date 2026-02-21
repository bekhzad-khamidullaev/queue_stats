from django.urls import path

from . import ui_views

urlpatterns = [
    path("", ui_views.dashboard, name="dashboard"),
    path("login/", ui_views.web_login, name="web-login"),
    path("logout/", ui_views.web_logout, name="web-logout"),
    path("ui/partials/answered/", ui_views.answered_partial, name="ui-answered-partial"),
    path("ui/partials/cdr/", ui_views.cdr_partial, name="ui-cdr-partial"),
    path("ui/partials/realtime-oob/", ui_views.realtime_oob_partial, name="ui-realtime-oob"),
    path("ui/exports/answered.xlsx", ui_views.export_answered_excel, name="ui-export-answered-xlsx"),
    path("ui/exports/answered.pdf", ui_views.export_answered_pdf, name="ui-export-answered-pdf"),
    path("ui/exports/cdr.xlsx", ui_views.export_cdr_excel, name="ui-export-cdr-xlsx"),
    path("ui/exports/cdr.pdf", ui_views.export_cdr_pdf, name="ui-export-cdr-pdf"),
]
