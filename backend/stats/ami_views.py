"""API views for Asterisk AMI management"""
from django.http import JsonResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_GET, require_POST
import json
from typing import Dict, Any

from accounts.models import UserRoles
from accounts.permissions import login_required_json, require_roles
from settings.models import GeneralSettings
from .ami_integration import AMIEvent, AMIManager


def _get_ami_manager() -> AMIManager:
    """Get configured AMI manager instance"""
    from django.conf import settings
    db_settings = GeneralSettings.objects.first()
    
    # Use DB settings if available, otherwise fallback to settings.py (which pulls from .env)
    host = db_settings.ami_host if db_settings and db_settings.ami_host != 'localhost' else getattr(settings, 'ASTERISK_AMI_HOST', '127.0.0.1')
    port = db_settings.ami_port if db_settings and db_settings.ami_port != 5038 else getattr(settings, 'ASTERISK_AMI_PORT', 5038)
    user = db_settings.ami_user if db_settings and db_settings.ami_user != 'admin' else getattr(settings, 'ASTERISK_AMI_USER', 'admin')
    password = db_settings.ami_password if db_settings and db_settings.ami_password else getattr(settings, 'ASTERISK_AMI_PASSWORD', '')

    return AMIManager(
        host=host,
        port=port,
        username=user,
        secret=password
    )


def _ami_action(action_func, **params) -> JsonResponse:
    """Execute AMI action with connection handling"""
    try:
        manager = _get_ami_manager()
        if not manager.connect():
            return JsonResponse({'error': 'Failed to connect to AMI'}, status=500)
        
        try:
            result = action_func(manager, **params)
            return JsonResponse(result)
        finally:
            manager.disconnect()
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'AMI error: {str(e)}'}, status=500)


# =============================================================================
# Call Control
# =============================================================================

@csrf_exempt
@require_POST
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR)
def ami_originate(request: HttpRequest) -> JsonResponse:
    """Originate a call"""
    try:
        data = json.loads(request.body)
        channel = data.get('channel')
        exten = data.get('exten')
        context = data.get('context')
        
        if not all([channel, exten, context]):
            return JsonResponse({'error': 'Missing required fields'}, status=400)
        
        return _ami_action(
            lambda mgr, **p: mgr.originate(**p),
            channel=channel,
            exten=exten,
            context=context,
            priority=data.get('priority', 1),
            callerid=data.get('callerid'),
            timeout=data.get('timeout', 30000),
            variable=data.get('variable')
        )
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)


@csrf_exempt
@require_POST
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR)
def ami_hangup(request: HttpRequest) -> JsonResponse:
    """Hangup a channel"""
    try:
        data = json.loads(request.body)
        channel = data.get('channel')
        
        if not channel:
            return JsonResponse({'error': 'Channel required'}, status=400)
        
        return _ami_action(
            lambda mgr, **p: mgr.hangup(**p),
            channel=channel,
            cause=data.get('cause', 16)
        )
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)


@csrf_exempt
@require_POST
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR)
def ami_redirect(request: HttpRequest) -> JsonResponse:
    """Redirect a channel"""
    try:
        data = json.loads(request.body)
        channel = data.get('channel')
        exten = data.get('exten')
        context = data.get('context')
        
        if not all([channel, exten, context]):
            return JsonResponse({'error': 'Missing required fields'}, status=400)
        
        return _ami_action(
            lambda mgr, **p: mgr.redirect(**p),
            channel=channel,
            exten=exten,
            context=context,
            priority=data.get('priority', 1),
            extra_channel=data.get('extra_channel')
        )
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)


@csrf_exempt
@require_POST
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR)
def ami_bridge(request: HttpRequest) -> JsonResponse:
    """Bridge two channels"""
    try:
        data = json.loads(request.body)
        channel1 = data.get('channel1')
        channel2 = data.get('channel2')
        
        if not all([channel1, channel2]):
            return JsonResponse({'error': 'Both channels required'}, status=400)
        
        return _ami_action(
            lambda mgr, **p: mgr.bridge(**p),
            channel1=channel1,
            channel2=channel2,
            tone=data.get('tone', True)
        )
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)


# =============================================================================
# Channel Status
# =============================================================================

@require_GET
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST, UserRoles.AGENT)
def ami_status(request: HttpRequest) -> JsonResponse:
    """Get channel status"""
    channel = request.GET.get('channel')
    return _ami_action(
        lambda mgr, **p: mgr.status(**p),
        channel=channel
    )


@require_GET
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST, UserRoles.AGENT)
def ami_core_show_channels(request: HttpRequest) -> JsonResponse:
    """Get all active channels"""
    return _ami_action(lambda mgr: mgr.core_show_channels())


# =============================================================================
# Queue Management
# =============================================================================

@require_GET
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST, UserRoles.AGENT)
def ami_queue_status(request: HttpRequest) -> JsonResponse:
    """Get queue status"""
    queue = request.GET.get('queue')
    member = request.GET.get('member')
    return _ami_action(
        lambda mgr, **p: mgr.queue_status(**p),
        queue=queue,
        member=member
    )


@require_GET
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST, UserRoles.AGENT)
def ami_queue_summary(request: HttpRequest) -> JsonResponse:
    """Get queue summary"""
    queue = request.GET.get('queue')
    return _ami_action(
        lambda mgr, **p: mgr.queue_summary(**p),
        queue=queue
    )


@csrf_exempt
@require_POST
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR)
def ami_queue_add(request: HttpRequest) -> JsonResponse:
    """Add member to queue"""
    try:
        data = json.loads(request.body)
        queue = data.get('queue')
        interface = data.get('interface')
        
        if not all([queue, interface]):
            return JsonResponse({'error': 'Queue and interface required'}, status=400)
        
        return _ami_action(
            lambda mgr, **p: mgr.queue_add(**p),
            queue=queue,
            interface=interface,
            penalty=data.get('penalty', 0),
            paused=data.get('paused', False),
            member_name=data.get('member_name'),
            state_interface=data.get('state_interface')
        )
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)


@csrf_exempt
@require_POST
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR)
def ami_queue_remove(request: HttpRequest) -> JsonResponse:
    """Remove member from queue"""
    try:
        data = json.loads(request.body)
        queue = data.get('queue')
        interface = data.get('interface')
        
        if not all([queue, interface]):
            return JsonResponse({'error': 'Queue and interface required'}, status=400)
        
        return _ami_action(
            lambda mgr, **p: mgr.queue_remove(**p),
            queue=queue,
            interface=interface
        )
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)


@csrf_exempt
@require_POST
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR)
def ami_queue_pause(request: HttpRequest) -> JsonResponse:
    """Pause/unpause queue member"""
    try:
        data = json.loads(request.body)
        queue = data.get('queue')
        interface = data.get('interface')
        paused = data.get('paused', True)
        
        if not all([queue, interface]):
            return JsonResponse({'error': 'Queue and interface required'}, status=400)
        
        return _ami_action(
            lambda mgr, **p: mgr.queue_pause(**p),
            queue=queue,
            interface=interface,
            paused=paused,
            reason=data.get('reason')
        )
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)


@csrf_exempt
@require_POST
@require_roles(UserRoles.ADMIN)
def ami_queue_reload(request: HttpRequest) -> JsonResponse:
    """Reload queue configuration"""
    try:
        data = json.loads(request.body) if request.body else {}
        return _ami_action(
            lambda mgr, **p: mgr.queue_reload(**p),
            queue=data.get('queue'),
            members=data.get('members', True),
            rules=data.get('rules', True),
            parameters=data.get('parameters', True)
        )
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)


# =============================================================================
# SIP/PJSIP Management
# =============================================================================

@require_GET
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR)
def ami_sip_peers(request: HttpRequest) -> JsonResponse:
    """Get SIP peers"""
    return _ami_action(lambda mgr: mgr.sip_peers())


@require_GET
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR)
def ami_sip_show_peer(request: HttpRequest) -> JsonResponse:
    """Get SIP peer details"""
    peer = request.GET.get('peer')
    if not peer:
        return JsonResponse({'error': 'Peer required'}, status=400)
    return _ami_action(
        lambda mgr, **p: mgr.sip_show_peer(**p),
        peer=peer
    )


@require_GET
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR)
def ami_pjsip_show_endpoints(request: HttpRequest) -> JsonResponse:
    """Get PJSIP endpoints"""
    return _ami_action(lambda mgr: mgr.pjsip_show_endpoints())


@require_GET
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR)
def ami_pjsip_show_endpoint(request: HttpRequest) -> JsonResponse:
    """Get PJSIP endpoint details"""
    endpoint = request.GET.get('endpoint')
    if not endpoint:
        return JsonResponse({'error': 'Endpoint required'}, status=400)
    return _ami_action(
        lambda mgr, **p: mgr.pjsip_show_endpoint(**p),
        endpoint=endpoint
    )


# =============================================================================
# Monitoring
# =============================================================================

@csrf_exempt
@require_POST
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR)
def ami_monitor(request: HttpRequest) -> JsonResponse:
    """Start monitoring a channel"""
    try:
        data = json.loads(request.body)
        channel = data.get('channel')
        
        if not channel:
            return JsonResponse({'error': 'Channel required'}, status=400)
        
        return _ami_action(
            lambda mgr, **p: mgr.monitor(**p),
            channel=channel,
            file=data.get('file'),
            format=data.get('format', 'wav'),
            mix=data.get('mix', True)
        )
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)


@csrf_exempt
@require_POST
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR)
def ami_stop_monitor(request: HttpRequest) -> JsonResponse:
    """Stop monitoring a channel"""
    try:
        data = json.loads(request.body)
        channel = data.get('channel')
        
        if not channel:
            return JsonResponse({'error': 'Channel required'}, status=400)
        
        return _ami_action(
            lambda mgr, **p: mgr.stop_monitor(**p),
            channel=channel
        )
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)


# =============================================================================
# Variables and Utilities
# =============================================================================

@csrf_exempt
@require_http_methods(['GET', 'POST'])
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR)
def ami_get_var(request: HttpRequest) -> JsonResponse:
    """Get channel variable"""
    if request.method == 'GET':
        channel = request.GET.get('channel')
        variable = request.GET.get('variable')
    else:
        try:
            data = json.loads(request.body)
            channel = data.get('channel')
            variable = data.get('variable')
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
    
    if not all([channel, variable]):
        return JsonResponse({'error': 'Channel and variable required'}, status=400)
    
    return _ami_action(
        lambda mgr, **p: mgr.get_var(**p),
        channel=channel,
        variable=variable
    )


@csrf_exempt
@require_POST
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR)
def ami_set_var(request: HttpRequest) -> JsonResponse:
    """Set channel variable"""
    try:
        data = json.loads(request.body)
        channel = data.get('channel')
        variable = data.get('variable')
        value = data.get('value')
        
        if not all([channel, variable, value is not None]):
            return JsonResponse({'error': 'Channel, variable, and value required'}, status=400)
        
        return _ami_action(
            lambda mgr, **p: mgr.set_var(**p),
            channel=channel,
            variable=variable,
            value=str(value)
        )
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)


@csrf_exempt
@require_http_methods(['GET', 'POST'])
@require_roles(UserRoles.ADMIN)
def ami_command(request: HttpRequest) -> JsonResponse:
    """Execute CLI command"""
    if request.method == 'GET':
        command = request.GET.get('command')
    else:
        try:
            data = json.loads(request.body)
            command = data.get('command')
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
    
    if not command:
        return JsonResponse({'error': 'Command required'}, status=400)
    
    return _ami_action(
        lambda mgr, **p: mgr.command(**p),
        command=command
    )


@require_GET
@require_roles(UserRoles.ADMIN, UserRoles.SUPERVISOR, UserRoles.ANALYST, UserRoles.AGENT)
def ami_ping(request: HttpRequest) -> JsonResponse:
    """Ping AMI connection"""
    return _ami_action(lambda mgr: mgr.ping())
