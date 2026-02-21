from django.db import models


class GeneralSettings(models.Model):
    LANGUAGE_CHOICES = [
        ("uz", "Uzbek"),
        ("ru", "Russian"),
        ("en", "English"),
    ]

    # Recording Download Service Settings
    download_url = models.CharField("URL сервиса загрузки", max_length=255, blank=True, help_text="URL для запроса файла, например, http://192.168.88.171:5000/download")
    download_token = models.CharField("Токен сервиса загрузки", max_length=255, blank=True)
    download_user = models.CharField("Пользователь сервиса загрузки", max_length=100, blank=True)
    download_password = models.CharField("Пароль сервиса загрузки", max_length=255, blank=True)

    # Asterisk DB Settings
    db_host = models.CharField("Хост БД", max_length=100, default="localhost")
    db_port = models.IntegerField("Порт БД", default=3306)
    db_name = models.CharField("Имя БД", max_length=100, default="asteriskcdrdb")
    db_user = models.CharField("Пользователь БД", max_length=100, default="asteriskuser")
    db_password = models.CharField("Пароль БД", max_length=255, blank=True, help_text="Пароль хранится в открытом виде. Убедитесь, что доступ к серверу ограничен.")

    # Asterisk AMI Settings
    ami_host = models.CharField("Хост AMI", max_length=100, default="localhost")
    ami_port = models.IntegerField("Порт AMI", default=5038)
    ami_user = models.CharField("Пользователь AMI", max_length=100, default="admin")
    ami_password = models.CharField("Пароль AMI", max_length=255, blank=True, help_text="Пароль хранится в открытом виде.")

    # Business/App Settings
    currency_code = models.CharField("Валюта", max_length=8, default="UZS")
    default_payout_rate_per_minute = models.DecimalField("Базовая цена за минуту", max_digits=10, decimal_places=2, default=0)
    ui_language = models.CharField("Язык интерфейса", max_length=2, choices=LANGUAGE_CHOICES, default="ru")
    business_day_start = models.TimeField("Начало бизнес-дня", default="09:00")
    business_day_end = models.TimeField("Конец бизнес-дня", default="18:00")
    sla_target_percent = models.DecimalField("Цель SLA, %", max_digits=5, decimal_places=2, default=80)
    sla_target_wait_seconds = models.IntegerField("SLA порог ожидания, сек", default=20)

    class Meta:
        verbose_name = "Общие настройки"
        verbose_name_plural = "Общие настройки"

    def __str__(self):
        return "Общие настройки"


class QueueDisplayMapping(models.Model):
    queue_system_name = models.CharField("Системное имя очереди", max_length=128, unique=True)
    queue_display_name = models.CharField("Отображаемое имя очереди", max_length=255)

    class Meta:
        verbose_name = "Маппинг очереди"
        verbose_name_plural = "Маппинг очередей"
        ordering = ["queue_system_name"]

    def __str__(self):
        return f"{self.queue_system_name} -> {self.queue_display_name}"


class AgentDisplayMapping(models.Model):
    agent_system_name = models.CharField("Системное имя оператора", max_length=128, unique=True)
    agent_display_name = models.CharField("Отображаемое имя оператора", max_length=255)

    class Meta:
        verbose_name = "Маппинг оператора"
        verbose_name_plural = "Маппинг операторов"
        ordering = ["agent_system_name"]

    def __str__(self):
        return f"{self.agent_system_name} -> {self.agent_display_name}"


class OperatorPayoutRate(models.Model):
    agent_system_name = models.CharField("Системное имя оператора", max_length=128, unique=True)
    rate_per_minute = models.DecimalField("Ставка за минуту", max_digits=10, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Ставка оператора"
        verbose_name_plural = "Ставки операторов"
        ordering = ["agent_system_name"]

    def __str__(self):
        return f"{self.agent_system_name}: {self.rate_per_minute}/min"
