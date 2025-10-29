from django.db import models


class GeneralSettings(models.Model):
    recording_path = models.CharField(
        max_length=255,
        verbose_name="Путь к записям разговоров",
        help_text="Путь к каталогу, где хранятся записи разговоров. Например, /var/spool/asterisk/monitor/",
        blank=True,
    )

    # Asterisk DB Settings
    db_host = models.CharField("Хост БД", max_length=100, default="localhost")
    db_port = models.IntegerField("Порт БД", default=3306)
    db_name = models.CharField("Имя БД", max_length=100, default="asteriskcdrdb")
    db_user = models.CharField("Пользователь БД", max_length=100, default="asteriskuser")
    db_password = models.CharField("Пароль БД", max_length=255, blank=True, help_text="Пароль хранится в открытом виде. Убедитесь, что доступ к серверу ограничен.")

    class Meta:
        verbose_name = "Общие настройки"
        verbose_name_plural = "Общие настройки"

    def __str__(self):
        return "Общие настройки"
