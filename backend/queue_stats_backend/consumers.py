import asyncio
import json
import logging
import threading
from asgiref.sync import async_to_sync
from channels.generic.websocket import AsyncWebsocketConsumer, WebsocketConsumer
from channels.layers import get_channel_layer
from django.http import QueryDict
from django.template.loader import render_to_string
from settings.models import GeneralSettings
from stats.ami_integration import AMIEvent, AMIManager, _build_ami_snapshot

logger = logging.getLogger(__name__)


class RealtimeConsumer(WebsocketConsumer):
    """WebSocket consumer for JSON AMI events (API mode)."""

    ami_manager = None
    ami_lock = threading.Lock()
    group_name = "ami_realtime"

    def connect(self):
        async_to_sync(self.channel_layer.group_add)(self.group_name, self.channel_name)
        self.accept()
        self.send(text_data=json.dumps({"type": "connection", "message": "Connected"}))
        self._ensure_ami_connection()

    def disconnect(self, close_code):
        async_to_sync(self.channel_layer.group_discard)(self.group_name, self.channel_name)
        logger.info("WebSocket disconnected: %s", close_code)

    def receive(self, text_data):
        try:
            data = json.loads(text_data)
            if data.get("command") == "ping":
                self.send(text_data=json.dumps({"type": "pong", "timestamp": data.get("timestamp")}))
        except json.JSONDecodeError:
            self.send(text_data=json.dumps({"type": "error", "message": "Invalid JSON"}))

    def ami_event(self, event):
        self.send(text_data=json.dumps(event))

    def _ensure_ami_connection(self):
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
                        secret=settings.ami_password,
                    )

                    if RealtimeConsumer.ami_manager.connect():
                        RealtimeConsumer.ami_manager.on_event(self._broadcast_ami_event)
                    else:
                        RealtimeConsumer.ami_manager = None
                except Exception as exc:
                    logger.error("Error setting up AMI connection: %s", exc)
                    RealtimeConsumer.ami_manager = None

    @staticmethod
    def _broadcast_ami_event(event: AMIEvent):
        try:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                RealtimeConsumer.group_name,
                {
                    "type": "ami_event",
                    "event": event.event_type,
                    "data": event.data,
                },
            )
        except Exception as exc:
            logger.error("Error broadcasting AMI event: %s", exc)


class HtmxRealtimeConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer that streams HTML OOB fragments for HTMX dashboard."""

    async def connect(self):
        if not self.scope.get("user") or not self.scope["user"].is_authenticated:
            await self.close(code=4401)
            return
        query = QueryDict((self.scope.get("query_string") or b"").decode())
        self._filters = {
            "queues": query.get("queues", ""),
            "channel": query.get("channel", ""),
            "caller": query.get("caller", ""),
        }
        await self.accept()
        self._running = True
        self._task = asyncio.create_task(self._stream_loop())

    async def disconnect(self, close_code):
        self._running = False
        task = getattr(self, "_task", None)
        if task:
            task.cancel()

    async def receive(self, text_data=None, bytes_data=None):
        return

    async def _stream_loop(self):
        while self._running:
            try:
                context = await asyncio.to_thread(_build_ami_snapshot, None, self._filters)
                html = render_to_string("stats/partials/realtime_oob.html", context)
                await self.send(text_data=html)
            except Exception as exc:
                logger.error("HTMX realtime loop error: %s", exc)
            await asyncio.sleep(3)
