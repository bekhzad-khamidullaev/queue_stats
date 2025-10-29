from __future__ import annotations

from django.contrib.auth.models import AbstractUser
from django.db import models


class UserRoles(models.TextChoices):
    ADMIN = "admin", "Администратор"
    SUPERVISOR = "supervisor", "Супервайзер"
    ANALYST = "analyst", "Аналитик"
    AGENT = "agent", "Агент"


class User(AbstractUser):
    role = models.CharField(
        max_length=32,
        choices=UserRoles.choices,
        default=UserRoles.AGENT,
    )

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    @property
    def allowed_reports(self) -> set[str]:
        if self.role == UserRoles.ADMIN:
            return {"*"}
        if self.role == UserRoles.SUPERVISOR:
            return {"summary", "answered", "unanswered", "distribution", "realtime", "raw"}
        if self.role == UserRoles.ANALYST:
            return {"summary", "answered", "unanswered", "distribution", "raw"}
        return {"realtime"}

