from django.urls import path

from . import views

urlpatterns = [
    path("meta/queues/", views.queues_list, name="queues-list"),
    path("meta/agents/", views.agents_list, name="agents-list"),
    path("reports/answered/", views.answered_report, name="answered-report"),
    path("reports/unanswered/", views.unanswered_report, name="unanswered-report"),
    path("reports/distribution/", views.distribution_report, name="distribution-report"),
    path("reports/raw/", views.raw_events, name="raw-events"),
    path("reports/summary/", views.summary_report, name="summary-report"),
    path("reports/answered-cdr/", views.answered_cdr_report, name="answered-cdr-report"),
    path("reports/sla/", views.sla_report, name="sla-report"),
    path("reports/volume/", views.volume_report, name="volume-report"),
        path("reports/agents-performance/", views.agent_performance_report, name="agents-performance-report"),
        path("recordings/<str:uniqueid>/", views.get_recording, name="get-recording"),
         path("realtime/calls/", views.active_calls, name="active-calls"),    path("realtime/queues/", views.queue_status, name="queue-status"),
    path("realtime/queue-summary/", views.queue_summary, name="queue-summary"),
]
