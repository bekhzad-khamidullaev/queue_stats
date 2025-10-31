"""Comprehensive Asterisk Manager Interface (AMI) Client"""
import socket
import threading
import time
import logging
from typing import Any, Callable, Dict, List, Optional
from queue import Queue

logger = logging.getLogger(__name__)


class AMIEvent:
    """Represents an AMI event"""
    def __init__(self, data: Dict[str, str]):
        self.data = data
        self.event_type = data.get('Event', '')
        self.privilege = data.get('Privilege', '')
    
    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)
    
    def __getitem__(self, key: str) -> Any:
        return self.data[key]
    
    def __repr__(self) -> str:
        return f"AMIEvent({self.event_type})"


class AMIManager:
    """Full-featured AMI Manager with event handling and comprehensive action support"""
    
    def __init__(self, host: str, port: int, username: str, secret: str):
        self.host = host
        self.port = port
        self.username = username
        self.secret = secret
        self.socket: Optional[socket.socket] = None
        self.connected = False
        self.authenticated = False
        
        # Event handling
        self.event_queue: Queue = Queue()
        self.event_callbacks: List[Callable[[AMIEvent], None]] = []
        self.listener_thread: Optional[threading.Thread] = None
        self.running = False
        
        # Response tracking
        self.action_id_counter = 0
        self.pending_responses: Dict[str, Queue] = {}
        
    def connect(self) -> bool:
        """Connect to AMI and authenticate"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10)
            self.socket.connect((self.host, self.port))
            
            # Read welcome message
            welcome = self.socket.recv(1024).decode('utf-8')
            logger.info(f"AMI Welcome: {welcome.strip()}")
            self.connected = True
            
            # Authenticate
            if self._login():
                self.authenticated = True
                # Start event listener
                self.running = True
                self.listener_thread = threading.Thread(target=self._event_listener, daemon=True)
                self.listener_thread.start()
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to connect to AMI: {e}")
            self.disconnect()
            return False
    
    def disconnect(self):
        """Disconnect from AMI"""
        self.running = False
        self.authenticated = False
        if self.socket:
            try:
                if self.connected:
                    self._send_action("Logoff")
            except:
                pass
            finally:
                try:
                    self.socket.close()
                except:
                    pass
                self.socket = None
                self.connected = False
    
    def _login(self) -> bool:
        """Login to AMI"""
        login_msg = f"Action: Login\r\nUsername: {self.username}\r\nSecret: {self.secret}\r\n\r\n"
        self.socket.sendall(login_msg.encode('utf-8'))
        
        response = self._read_response()
        success = 'Response: Success' in response
        if success:
            logger.info("AMI authentication successful")
        else:
            logger.error(f"AMI authentication failed: {response}")
        return success
    
    def _read_response(self, timeout: float = 5.0) -> str:
        """Read a complete AMI response"""
        response = ""
        self.socket.settimeout(timeout)
        try:
            while True:
                chunk = self.socket.recv(4096).decode('utf-8', errors='ignore')
                if not chunk:
                    break
                response += chunk
                if "\r\n\r\n" in response:
                    break
        except socket.timeout:
            pass
        return response
    
    def _parse_response(self, data: str) -> List[Dict[str, str]]:
        """Parse AMI response into structured data"""
        entries = []
        current = {}
        
        for line in data.split('\r\n'):
            line = line.strip()
            if not line:
                if current:
                    entries.append(current)
                    current = {}
                continue
            
            if ':' in line:
                key, value = line.split(':', 1)
                current[key.strip()] = value.strip()
        
        if current:
            entries.append(current)
        
        return entries
    
    def _event_listener(self):
        """Background thread to listen for AMI events"""
        buffer = ""
        while self.running and self.socket:
            try:
                self.socket.settimeout(0.1)
                chunk = self.socket.recv(4096).decode('utf-8', errors='ignore')
                if not chunk:
                    break
                
                buffer += chunk
                
                # Process complete messages
                while "\r\n\r\n" in buffer:
                    msg, buffer = buffer.split("\r\n\r\n", 1)
                    self._process_message(msg)
                    
            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"Event listener error: {e}")
                break
    
    def _process_message(self, msg: str):
        """Process a single AMI message (event or response)"""
        parsed = self._parse_response(msg + "\r\n\r\n")
        if not parsed:
            return
        
        entry = parsed[0]
        
        # Check if it's an event
        if 'Event' in entry:
            event = AMIEvent(entry)
            self.event_queue.put(event)
            
            # Call registered callbacks
            for callback in self.event_callbacks:
                try:
                    callback(event)
                except Exception as e:
                    logger.error(f"Event callback error: {e}")
        
        # Check if it's a response to an action
        elif 'ActionID' in entry:
            action_id = entry['ActionID']
            if action_id in self.pending_responses:
                self.pending_responses[action_id].put(parsed)
    
    def _send_action(self, action: str, **params) -> Optional[List[Dict[str, str]]]:
        """Send an AMI action and wait for response"""
        if not self.authenticated:
            return None
        
        # Generate unique ActionID
        self.action_id_counter += 1
        action_id = f"cbuff_{self.action_id_counter}_{int(time.time() * 1000)}"
        
        # Prepare response queue
        response_queue = Queue()
        self.pending_responses[action_id] = response_queue
        
        # Build action message
        msg = f"Action: {action}\r\nActionID: {action_id}\r\n"
        for key, value in params.items():
            msg += f"{key}: {value}\r\n"
        msg += "\r\n"
        
        try:
            self.socket.sendall(msg.encode('utf-8'))
            
            # Collect all responses until completion or timeout
            all_responses = []
            timeout_time = time.time() + 10
            
            while time.time() < timeout_time:
                try:
                    response = response_queue.get(timeout=0.5)
                    all_responses.extend(response)
                    
                    # Check if this is the final response
                    for entry in response:
                        if entry.get('EventList') == 'Complete' or \
                           'Complete' in entry.get('Event', '') or \
                           entry.get('Response') == 'Success':
                            # Got completion marker
                            return all_responses if all_responses else response
                except:
                    # Timeout on this iteration, check if we have any responses
                    if all_responses:
                        return all_responses
            
            logger.warning(f"Timeout waiting for action {action} response")
            return all_responses if all_responses else None
        finally:
            # Cleanup with timeout to prevent memory leaks
            if action_id in self.pending_responses:
                del self.pending_responses[action_id]
    
    def on_event(self, callback: Callable[[AMIEvent], None]):
        """Register event callback"""
        self.event_callbacks.append(callback)
    
    # =========================================================================
    # AMI Actions - Comprehensive Command Support
    # =========================================================================
    
    def originate(self, channel: str, exten: str, context: str, priority: int = 1, 
                  callerid: Optional[str] = None, timeout: int = 30000,
                  variable: Optional[Dict[str, str]] = None, **kwargs) -> Dict:
        """Originate a call"""
        params = {
            'Channel': channel,
            'Exten': exten,
            'Context': context,
            'Priority': priority,
            'Timeout': timeout,
        }
        if callerid:
            params['CallerID'] = callerid
        if variable:
            for key, value in variable.items():
                params[f'Variable'] = f"{key}={value}"
        params.update(kwargs)
        
        response = self._send_action('Originate', **params)
        return {'success': response and 'Success' in str(response), 'data': response}
    
    def hangup(self, channel: str, cause: int = 16) -> Dict:
        """Hangup a channel"""
        response = self._send_action('Hangup', Channel=channel, Cause=cause)
        return {'success': response and 'Success' in str(response), 'data': response}
    
    def redirect(self, channel: str, exten: str, context: str, priority: int = 1,
                 extra_channel: Optional[str] = None) -> Dict:
        """Redirect a channel"""
        params = {'Channel': channel, 'Exten': exten, 'Context': context, 'Priority': priority}
        if extra_channel:
            params['ExtraChannel'] = extra_channel
        response = self._send_action('Redirect', **params)
        return {'success': response and 'Success' in str(response), 'data': response}
    
    def status(self, channel: Optional[str] = None) -> Dict:
        """Get channel status"""
        params = {}
        if channel:
            params['Channel'] = channel
        response = self._send_action('Status', **params)
        return {'success': True, 'channels': response or []}
    
    def core_show_channels(self) -> Dict:
        """Get all active channels"""
        response = self._send_action('CoreShowChannels')
        return {'success': True, 'channels': response or []}
    
    def queue_status(self, queue: Optional[str] = None, member: Optional[str] = None) -> Dict:
        """Get queue status"""
        params = {}
        if queue:
            params['Queue'] = queue
        if member:
            params['Member'] = member
        response = self._send_action('QueueStatus', **params)
        
        # Parse queue status response - restructure into queue objects with members
        queues = []
        current_queue = None
        
        if response:
            for entry in response:
                event_type = entry.get('Event', '')
                
                if event_type == 'QueueParams':
                    # Start new queue
                    if current_queue:
                        queues.append(current_queue)
                    current_queue = dict(entry)
                    current_queue['members'] = []
                elif event_type == 'QueueMember' and current_queue:
                    # Add member to current queue
                    current_queue['members'].append(entry)
                elif event_type == 'QueueStatusComplete':
                    # End of queue list
                    if current_queue:
                        queues.append(current_queue)
                        current_queue = None
            
            # Add last queue if not completed
            if current_queue:
                queues.append(current_queue)
        
        return {'success': True, 'queues': queues}
    
    def queue_summary(self, queue: Optional[str] = None) -> Dict:
        """Get queue summary"""
        params = {}
        if queue:
            params['Queue'] = queue
        response = self._send_action('QueueSummary', **params)
        return {'success': True, 'summary': response or []}
    
    def queue_add(self, queue: str, interface: str, penalty: int = 0, 
                  paused: bool = False, member_name: Optional[str] = None,
                  state_interface: Optional[str] = None) -> Dict:
        """Add member to queue"""
        params = {
            'Queue': queue,
            'Interface': interface,
            'Penalty': penalty,
            'Paused': 'true' if paused else 'false'
        }
        if member_name:
            params['MemberName'] = member_name
        if state_interface:
            params['StateInterface'] = state_interface
        response = self._send_action('QueueAdd', **params)
        return {'success': response and 'Success' in str(response), 'data': response}
    
    def queue_remove(self, queue: str, interface: str) -> Dict:
        """Remove member from queue"""
        response = self._send_action('QueueRemove', Queue=queue, Interface=interface)
        return {'success': response and 'Success' in str(response), 'data': response}
    
    def queue_pause(self, queue: str, interface: str, paused: bool = True,
                    reason: Optional[str] = None) -> Dict:
        """Pause/unpause queue member"""
        params = {
            'Queue': queue,
            'Interface': interface,
            'Paused': 'true' if paused else 'false'
        }
        if reason:
            params['Reason'] = reason
        response = self._send_action('QueuePause', **params)
        return {'success': response and 'Success' in str(response), 'data': response}
    
    def queue_reload(self, queue: Optional[str] = None, members: bool = True,
                     rules: bool = True, parameters: bool = True) -> Dict:
        """Reload queue configuration"""
        params = {}
        if queue:
            params['Queue'] = queue
        params['Members'] = 'yes' if members else 'no'
        params['Rules'] = 'yes' if rules else 'no'
        params['Parameters'] = 'yes' if parameters else 'no'
        response = self._send_action('QueueReload', **params)
        return {'success': response and 'Success' in str(response), 'data': response}
    
    def queue_log(self, queue: str, event: str, uniqueid: Optional[str] = None,
                  interface: Optional[str] = None, message: Optional[str] = None) -> Dict:
        """Add entry to queue log"""
        params = {'Queue': queue, 'Event': event}
        if uniqueid:
            params['Uniqueid'] = uniqueid
        if interface:
            params['Interface'] = interface
        if message:
            params['Message'] = message
        response = self._send_action('QueueLog', **params)
        return {'success': response and 'Success' in str(response), 'data': response}
    
    def sip_peers(self) -> Dict:
        """Get SIP peers"""
        response = self._send_action('SIPpeers')
        return {'success': True, 'peers': response or []}
    
    def sip_show_peer(self, peer: str) -> Dict:
        """Get SIP peer details"""
        response = self._send_action('SIPshowpeer', Peer=peer)
        return {'success': True, 'peer': response or []}
    
    def pjsip_show_endpoints(self) -> Dict:
        """Get PJSIP endpoints"""
        response = self._send_action('PJSIPShowEndpoints')
        return {'success': True, 'endpoints': response or []}
    
    def pjsip_show_endpoint(self, endpoint: str) -> Dict:
        """Get PJSIP endpoint details"""
        response = self._send_action('PJSIPShowEndpoint', Endpoint=endpoint)
        return {'success': True, 'endpoint': response or []}
    
    def command(self, command: str) -> Dict:
        """Execute CLI command"""
        response = self._send_action('Command', Command=command)
        return {'success': True, 'output': response or []}
    
    def ping(self) -> Dict:
        """Ping AMI"""
        response = self._send_action('Ping')
        return {'success': response and 'Pong' in str(response), 'data': response}
    
    def get_var(self, channel: str, variable: str) -> Dict:
        """Get channel variable"""
        response = self._send_action('Getvar', Channel=channel, Variable=variable)
        value = None
        if response:
            for entry in response:
                if 'Value' in entry:
                    value = entry['Value']
                    break
        return {'success': True, 'value': value, 'data': response}
    
    def set_var(self, channel: str, variable: str, value: str) -> Dict:
        """Set channel variable"""
        response = self._send_action('Setvar', Channel=channel, Variable=variable, Value=value)
        return {'success': response and 'Success' in str(response), 'data': response}
    
    def bridge(self, channel1: str, channel2: str, tone: bool = True) -> Dict:
        """Bridge two channels"""
        response = self._send_action('Bridge', Channel1=channel1, Channel2=channel2,
                                    Tone='yes' if tone else 'no')
        return {'success': response and 'Success' in str(response), 'data': response}
    
    def park(self, channel: str, channel2: str, timeout: int = 45000,
             parkinglot: Optional[str] = None) -> Dict:
        """Park a channel"""
        params = {'Channel': channel, 'Channel2': channel2, 'Timeout': timeout}
        if parkinglot:
            params['Parkinglot'] = parkinglot
        response = self._send_action('Park', **params)
        return {'success': response and 'Success' in str(response), 'data': response}
    
    def parked_calls(self) -> Dict:
        """Get parked calls"""
        response = self._send_action('ParkedCalls')
        return {'success': True, 'calls': response or []}
    
    def monitor(self, channel: str, file: Optional[str] = None, 
                format: str = 'wav', mix: bool = True) -> Dict:
        """Start monitoring a channel"""
        params = {'Channel': channel, 'Format': format, 'Mix': 'true' if mix else 'false'}
        if file:
            params['File'] = file
        response = self._send_action('Monitor', **params)
        return {'success': response and 'Success' in str(response), 'data': response}
    
    def stop_monitor(self, channel: str) -> Dict:
        """Stop monitoring a channel"""
        response = self._send_action('StopMonitor', Channel=channel)
        return {'success': response and 'Success' in str(response), 'data': response}
    
    def mixmonitor_mute(self, channel: str, direction: str = 'both', state: bool = True) -> Dict:
        """Mute/unmute MixMonitor on a channel"""
        response = self._send_action('MixMonitorMute', Channel=channel, 
                                    Direction=direction, State='1' if state else '0')
        return {'success': response and 'Success' in str(response), 'data': response}
    
    def absolute_timeout(self, channel: str, timeout: int) -> Dict:
        """Set absolute timeout on a channel"""
        response = self._send_action('AbsoluteTimeout', Channel=channel, Timeout=timeout)
        return {'success': response and 'Success' in str(response), 'data': response}
    
    def extension_state(self, exten: str, context: str) -> Dict:
        """Get extension state"""
        response = self._send_action('ExtensionState', Exten=exten, Context=context)
        return {'success': True, 'state': response or []}
    
    def mailbox_status(self, mailbox: str) -> Dict:
        """Get mailbox status"""
        response = self._send_action('MailboxStatus', Mailbox=mailbox)
        return {'success': True, 'status': response or []}
    
    def mailbox_count(self, mailbox: str) -> Dict:
        """Get mailbox message count"""
        response = self._send_action('MailboxCount', Mailbox=mailbox)
        return {'success': True, 'count': response or []}
