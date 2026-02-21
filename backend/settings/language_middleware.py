from __future__ import annotations

import time

from django.utils import translation

from settings.models import GeneralSettings

_CACHE = {"lang": "ru", "ts": 0.0}
_TTL_SECONDS = 15


class SettingsLanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        now = time.time()
        if now - _CACHE["ts"] > _TTL_SECONDS:
            try:
                obj = GeneralSettings.objects.first()
                _CACHE["lang"] = (obj.ui_language if obj and obj.ui_language else "ru")[:2]
            except Exception:
                _CACHE["lang"] = "ru"
            _CACHE["ts"] = now

        lang = _CACHE["lang"]
        translation.activate(lang)
        request.LANGUAGE_CODE = lang
        response = self.get_response(request)
        translation.deactivate()
        return response
