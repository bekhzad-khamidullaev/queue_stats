from django.apps import AppConfig
import os
import sys


class StatsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "stats"
    verbose_name = "Queue Statistics"

    def ready(self):
        command = " ".join(sys.argv).lower()
        if any(x in command for x in ("makemigrations", "migrate", "collectstatic", "test", "check")):
            return
        if "runserver" in command and os.environ.get("RUN_MAIN") != "true":
            return
        if os.environ.get("DISABLE_AMI_SYNC") == "1":
            return
        try:
            from .realtime_sync import start_realtime_sync_worker

            start_realtime_sync_worker()
        except Exception:
            # do not break app startup if background sync failed to boot
            return
