from django.db import models


class GeneralSettings(models.Model):
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

    class Meta:
        verbose_name = "Общие настройки"
        verbose_name_plural = "Общие настройки"

    def __str__(self):
        return "Общие настройки"
