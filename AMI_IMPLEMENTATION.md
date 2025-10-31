# Asterisk AMI Implementation Guide

## Overview

This project now includes complete Asterisk Manager Interface (AMI) control capabilities for managing Asterisk PBX through both API endpoints and a real-time WebSocket interface.

## Backend Components

### 1. AMI Manager (`backend/stats/ami_manager.py`)

Comprehensive AMI client with:
- **Connection Management**: Automatic authentication, reconnection handling
- **Event Handling**: Real-time event listener with callback support
- **Action Support**: 30+ AMI actions including:
  - Call control (originate, hangup, redirect, bridge)
  - Queue management (add/remove members, pause/unpause, reload)
  - Channel operations (status, variables, monitoring)
  - SIP/PJSIP management
  - Parking, monitoring, and more

### 2. API Views (`backend/stats/ami_views.py`)

RESTful API endpoints:
- **Call Control**: `/api/ami/originate/`, `/api/ami/hangup/`, `/api/ami/redirect/`, `/api/ami/bridge/`
- **Channel Status**: `/api/ami/status/`, `/api/ami/channels/`
- **Queue Management**: `/api/ami/queue/status/`, `/api/ami/queue/add/`, `/api/ami/queue/remove/`, `/api/ami/queue/pause/`
- **SIP/PJSIP**: `/api/ami/sip/peers/`, `/api/ami/pjsip/endpoints/`
- **Monitoring**: `/api/ami/monitor/start/`, `/api/ami/monitor/stop/`
- **Utilities**: `/api/ami/getvar/`, `/api/ami/setvar/`, `/api/ami/command/`, `/api/ami/ping/`

### 3. WebSocket Consumer (`backend/queue_stats_backend/consumers.py`)

Real-time event streaming:
- Maintains persistent AMI connection
- Broadcasts all AMI events to connected WebSocket clients
- Events include: new channels, hangups, queue events, agent status changes, etc.

## Frontend Components

### AMI Control View (`frontend/src/views/AMIControlView.jsx`)

Comprehensive management interface with tabs:

1. **Channels Tab**:
   - View all active channels
   - Hangup channels
   - Real-time updates via WebSocket

2. **Queues Tab**:
   - View queue status and members
   - Add/remove queue members
   - Pause/unpause agents
   - Monitor queue metrics

3. **Events Tab**:
   - Real-time AMI event stream
   - Event history (last 100 events)
   - JSON view of event data

4. **Actions Tab**:
   - Originate calls
   - Get/set channel variables
   - Ping AMI connection
   - Execute custom actions

## Configuration

AMI settings are configured in Django Admin under **General Settings**:
- AMI Host (default: localhost)
- AMI Port (default: 5038)
- AMI Username
- AMI Password

## Asterisk Configuration

### Required in `/etc/asterisk/manager.conf`:

```ini
[general]
enabled = yes
port = 5038
bindaddr = 127.0.0.1

[admin]
secret = your_secret_password
deny = 0.0.0.0/0.0.0.0
permit = 127.0.0.1/255.255.255.0
read = system,call,log,verbose,command,agent,user,config,dtmf,reporting,cdr,dialplan
write = system,call,log,verbose,command,agent,user,config,dtmf,reporting,cdr,dialplan
```

Reload configuration:
```bash
asterisk -rx "manager reload"
```

## Security Considerations

- AMI control actions are restricted to Admin and Supervisor roles
- Read-only operations available to all authenticated users
- WebSocket connection requires authentication
- AMI credentials stored in database (consider encryption for production)
- Never expose AMI port (5038) to public internet

## Usage Examples

### Originate a Call (API)

```javascript
await client.post('/api/ami/originate/', {
  channel: 'PJSIP/100',
  exten: '200',
  context: 'default',
  priority: 1,
  timeout: 30000
});
```

### Pause Queue Member

```javascript
await client.post('/api/ami/queue/pause/', {
  queue: 'support',
  interface: 'PJSIP/100',
  paused: true,
  reason: 'Break'
});
```

### Listen to Real-time Events

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/realtime/');
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'ami_event') {
    console.log('Event:', data.event, data.data);
  }
};
```

## Event Types

Common AMI events broadcasted:
- **Newchannel**: New call initiated
- **Hangup**: Call ended
- **QueueMemberAdded/Removed**: Queue membership changes
- **QueueMemberPause**: Agent pause status changed
- **AgentCalled/Connect/Complete**: Queue call flow
- **Bridge**: Channels bridged
- And 100+ more event types

## Troubleshooting

1. **Connection Failed**: Check AMI credentials in Django Admin
2. **Permission Denied**: Verify user role has proper permissions
3. **WebSocket Disconnects**: Check Channels configuration in settings.py
4. **No Events**: Ensure AMI user has proper read permissions in manager.conf

## Extensions

To add new AMI actions:

1. Add method to `AMIManager` class in `ami_manager.py`
2. Create view function in `ami_views.py`
3. Add URL pattern in `stats/urls.py`
4. Add UI controls in `AMIControlView.jsx`

## Performance Notes

- AMI connection is singleton per WebSocket consumer
- Events are queued and processed asynchronously
- Frontend limits event history to 100 items
- WebSocket heartbeat prevents connection timeouts
