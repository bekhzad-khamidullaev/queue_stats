"""
WSGI config for queue_stats_backend project.
"""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "queue_stats_backend.settings")

application = get_wsgi_application()

