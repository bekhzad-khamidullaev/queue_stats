from django.urls import path
from . import views
from . import ami_views

urlpatterns = [
    path("meta/queues/", views.queues_list, name="queues_list"),
    path("meta/agents/", views.agents_list, name="agents_list"),
    path("reports/answered/", views.answered_report, name="answered_report"),
    path("reports/unanswered/", views.unanswered_report, name="unanswered_report"),
    path("reports/distribution/", views.distribution_report, name="distribution_report"),
    path("reports/raw-events/", views.raw_events, name="raw_events"),
    path("reports/raw/", views.raw_events_legacy, name="raw_events_legacy"),
    path("reports/summary/", views.summary_report, name="summary_report"),
    path("reports/answered-cdr/", views.answered_cdr_report, name="answered_cdr_report"),
    path("reports/unanswered-cdr/", views.unanswered_cdr_report, name="unanswered_cdr_report"),
    path("reports/outbound/", views.outbound_report, name="outbound_report"),
    path("reports/search/", views.queue_search, name="queue_search"),
    path("reports/dids/", views.dids_report, name="dids_report"),
    path("reports/trunks/", views.trunks_report, name="trunks_report"),
    path("reports/areport/", views.areport_legacy, name="areport_legacy"),
    path("reports/qreport/", views.qreport_legacy, name="qreport_legacy"),
    path("reports/sla/", views.sla_report, name="sla_report"),
    path("reports/volume/", views.volume_report, name="volume_report"),
    path("reports/agents-performance/", views.agent_performance_report, name="agent_performance_report"),
    path("realtime/active-calls/", views.active_calls, name="active_calls"),
    path("realtime/calls/", views.active_calls_legacy, name="active_calls_legacy"),
    path("realtime/queue-status/", views.queue_status, name="queue_status"),
    path("realtime/queues/", views.queue_status_legacy, name="queue_status_legacy"),
    path("realtime/queue-summary/", views.queue_summary, name="queue_summary"),
    path("recordings/<str:uniqueid>/", views.get_recording, name="get_recording"),
    
    # AMI Control Endpoints
    # Call Control
    path("ami/originate/", ami_views.ami_originate, name="ami_originate"),
    path("ami/hangup/", ami_views.ami_hangup, name="ami_hangup"),
    path("ami/redirect/", ami_views.ami_redirect, name="ami_redirect"),
    path("ami/bridge/", ami_views.ami_bridge, name="ami_bridge"),
    
    # Channel Status
    path("ami/status/", ami_views.ami_status, name="ami_status"),
    path("ami/channels/", ami_views.ami_core_show_channels, name="ami_core_show_channels"),
    
    # Queue Management
    path("ami/queue/status/", ami_views.ami_queue_status, name="ami_queue_status"),
    path("ami/queue/summary/", ami_views.ami_queue_summary, name="ami_queue_summary"),
    path("ami/queue/add/", ami_views.ami_queue_add, name="ami_queue_add"),
    path("ami/queue/remove/", ami_views.ami_queue_remove, name="ami_queue_remove"),
    path("ami/queue/pause/", ami_views.ami_queue_pause, name="ami_queue_pause"),
    path("ami/queue/reload/", ami_views.ami_queue_reload, name="ami_queue_reload"),
    
    # SIP/PJSIP
    path("ami/sip/peers/", ami_views.ami_sip_peers, name="ami_sip_peers"),
    path("ami/sip/peer/", ami_views.ami_sip_show_peer, name="ami_sip_show_peer"),
    path("ami/pjsip/endpoints/", ami_views.ami_pjsip_show_endpoints, name="ami_pjsip_show_endpoints"),
    path("ami/pjsip/endpoint/", ami_views.ami_pjsip_show_endpoint, name="ami_pjsip_show_endpoint"),
    
    # Monitoring
    path("ami/monitor/start/", ami_views.ami_monitor, name="ami_monitor"),
    path("ami/monitor/stop/", ami_views.ami_stop_monitor, name="ami_stop_monitor"),
    
    # Utilities
    path("ami/getvar/", ami_views.ami_get_var, name="ami_get_var"),
    path("ami/setvar/", ami_views.ami_set_var, name="ami_set_var"),
    path("ami/command/", ami_views.ami_command, name="ami_command"),
    path("ami/ping/", ami_views.ami_ping, name="ami_ping"),
]
