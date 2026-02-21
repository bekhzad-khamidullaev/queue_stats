"""queue_stats_backend URL Configuration."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/", include("stats.urls")),
    path("", include("stats.ui_urls")),
]

if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
    if getattr(settings, "MEDIA_URL", None):
        urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
