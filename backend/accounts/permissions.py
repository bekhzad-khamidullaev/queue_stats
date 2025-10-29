from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from django.http import HttpRequest, JsonResponse

from .models import UserRoles

ViewFunc = Callable[[HttpRequest, ...], JsonResponse]


def login_required_json(view: ViewFunc) -> ViewFunc:
    @wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any):
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "authentication required"}, status=401)
        return view(request, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


def require_roles(*roles: str) -> Callable[[ViewFunc], ViewFunc]:
    allowed = set(roles)

    if not allowed:
        allowed = {UserRoles.ADMIN}

    def decorator(view: ViewFunc) -> ViewFunc:
        @wraps(view)
        def wrapper(request: HttpRequest, *args: Any, **kwargs: Any):
            if not request.user.is_authenticated:
                return JsonResponse({"detail": "authentication required"}, status=401)
            if UserRoles.ADMIN in allowed and request.user.role == UserRoles.ADMIN:
                return view(request, *args, **kwargs)
            if request.user.role not in allowed:
                return JsonResponse({"detail": "forbidden"}, status=403)
            return view(request, *args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator

