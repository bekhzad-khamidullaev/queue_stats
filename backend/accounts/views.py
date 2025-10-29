from __future__ import annotations

import json
from typing import Any, Dict

from django.contrib.auth import authenticate, login, logout
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from .models import User, UserRoles
from .permissions import login_required_json, require_roles


def _read_payload(request: HttpRequest) -> Dict[str, Any]:
    if request.body:
        try:
            return json.loads(request.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
    if request.POST:
        return request.POST.dict()
    return {}


def _user_payload(user: User) -> Dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "role": user.role,
        "allowed_reports": list(user.allowed_reports),
        "is_superuser": user.is_superuser,
    }


@csrf_exempt
@require_http_methods(["POST"])
def login_view(request: HttpRequest) -> JsonResponse:
    payload = _read_payload(request)
    username = payload.get("username")
    password = payload.get("password")
    if not username or not password:
        return JsonResponse({"detail": "username and password required"}, status=400)
    user = authenticate(request, username=username, password=password)
    if user is None:
        return JsonResponse({"detail": "invalid credentials"}, status=401)
    login(request, user)
    return JsonResponse({"user": _user_payload(user)})


@csrf_exempt
@require_http_methods(["POST"])
def logout_view(request: HttpRequest) -> JsonResponse:
    logout(request)
    return JsonResponse({"detail": "ok"})


@login_required_json
@require_GET
def me_view(request: HttpRequest) -> JsonResponse:
    assert isinstance(request.user, User)
    return JsonResponse({"user": _user_payload(request.user)})


@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_roles(UserRoles.ADMIN)
def users_collection(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        data = [_user_payload(user) for user in User.objects.order_by("username")]
        return JsonResponse({"users": data})

    payload = _read_payload(request)
    username = payload.get("username")
    password = payload.get("password")
    role = payload.get("role", UserRoles.AGENT)

    if not username or not password:
        return JsonResponse({"detail": "username and password required"}, status=400)
    if role not in dict(UserRoles.choices):
        return JsonResponse({"detail": "invalid role"}, status=400)

    if User.objects.filter(username=username).exists():
        return JsonResponse({"detail": "username already exists"}, status=400)

    user = User.objects.create_user(
        username=username,
        password=password,
        role=role,
        first_name=payload.get("first_name", ""),
        last_name=payload.get("last_name", ""),
        email=payload.get("email", ""),
        is_superuser=payload.get("is_superuser", False),
        is_staff=payload.get("is_staff", role == UserRoles.ADMIN),
    )
    return JsonResponse({"user": _user_payload(user)}, status=201)


@csrf_exempt
@require_http_methods(["PATCH", "DELETE"])
@require_roles(UserRoles.ADMIN)
def users_detail(request: HttpRequest, user_id: int) -> JsonResponse:
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return JsonResponse({"detail": "not found"}, status=404)

    if request.method == "DELETE":
        if request.user.pk == user.pk:
            return JsonResponse({"detail": "cannot delete current user"}, status=400)
        user.delete()
        return JsonResponse({"detail": "deleted"})

    payload = _read_payload(request)
    updated = False

    if "first_name" in payload:
        user.first_name = payload["first_name"]
        updated = True
    if "last_name" in payload:
        user.last_name = payload["last_name"]
        updated = True
    if "email" in payload:
        user.email = payload["email"]
        updated = True
    if "role" in payload:
        role = payload["role"]
        if role not in dict(UserRoles.choices):
            return JsonResponse({"detail": "invalid role"}, status=400)
        user.role = role
        updated = True
    if "is_staff" in payload:
        user.is_staff = bool(payload["is_staff"])
        updated = True
    if "is_superuser" in payload:
        user.is_superuser = bool(payload["is_superuser"])
        updated = True
    if "password" in payload and payload["password"]:
        user.set_password(payload["password"])
        updated = True

    if updated:
        user.save()

    return JsonResponse({"user": _user_payload(user)})

