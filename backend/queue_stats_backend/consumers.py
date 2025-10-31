import json
import threading
import logging
from channels.generic.websocket import WebsocketConsumer
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from settings.models import GeneralSettings
from stats.ami_manager import AMIManager, AMIEvent

logger = logging.getLogger(__name__)


class RealtimeConsumer(WebsocketConsumer):
    """WebSocket consumer for real-time AMI events"""
    
    ami_manager = None
    ami_lock = threading.Lock()
    group_name = "ami_realtime"
    
    def connect(self):
        # Join group for broadcasting
        async_to_sync(self.channel_layer.group_add)(
            self.group_name,
            self.channel_name
        )
        
        self.accept()
        self.send(text_data=json.dumps({"type": "connection", "message": "Connected to Asterisk realtime events"}))
        
        # Start AMI connection if not already started
        self._ensure_ami_connection()
    
    def disconnect(self, close_code):
        # Leave group
        async_to_sync(self.channel_layer.group_discard)(
            self.group_name,
            self.channel_name
        )
        logger.info(f"WebSocket disconnected: {close_code}")
    
    def receive(self, text_data):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(text_data)
            command = data.get("command")
            
            if command == "ping":
                self.send(text_data=json.dumps({"type": "pong", "timestamp": data.get("timestamp")}))
            elif command == "subscribe":
                event_types = data.get("events", [])
                self.send(text_data=json.dumps({
                    "type": "subscribed",
                    "events": event_types
                }))
        except json.JSONDecodeError:
            self.send(text_data=json.dumps({"type": "error", "message": "Invalid JSON"}))
    
    # Handler for group messages
    def ami_event(self, event):
        """Receive AMI event from channel layer and send to WebSocket"""
        self.send(text_data=json.dumps(event))
    
    def _ensure_ami_connection(self):
        """Ensure AMI manager is connected (singleton pattern)"""
        with self.ami_lock:
            if RealtimeConsumer.ami_manager is None or not RealtimeConsumer.ami_manager.authenticated:
                try:
                    settings = GeneralSettings.objects.first()
                    if not settings or not settings.ami_host:
                        logger.error("AMI settings not configured")
                        return
                    
                    RealtimeConsumer.ami_manager = AMIManager(
                        host=settings.ami_host,
                        port=settings.ami_port,
                        username=settings.ami_user,
                        secret=settings.ami_password
                    )
                    
                    if RealtimeConsumer.ami_manager.connect():
                        # Register event callback for group broadcasting
                        RealtimeConsumer.ami_manager.on_event(self._broadcast_ami_event)
                        logger.info("AMI connection established for WebSocket")
                    else:
                        logger.error("Failed to connect AMI manager")
                        # Retry on next connection
                        RealtimeConsumer.ami_manager = None
                except Exception as e:
                    logger.error(f"Error setting up AMI connection: {e}")
                    RealtimeConsumer.ami_manager = None
    
    @staticmethod
    def _broadcast_ami_event(event: AMIEvent):
        """Broadcast AMI event to all connected WebSocket clients"""
        try:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                RealtimeConsumer.group_name,
                {
                    "type": "ami_event",
                    "event": event.event_type,
                    "data": event.data
                }
            )
        except Exception as e:
            logger.error(f"Error broadcasting AMI event: {e}")

