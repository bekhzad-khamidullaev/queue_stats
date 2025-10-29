from django.contrib import admin, messages
from .models import GeneralSettings
import json
from pathlib import Path


@admin.register(GeneralSettings)
class GeneralSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        # Prevent adding more than one instance
        return not GeneralSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        # Prevent deleting the instance
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        db_config = {
            "ENGINE": "django.db.backends.mysql",
            "NAME": obj.db_name,
            "USER": obj.db_user,
            "PASSWORD": obj.db_password,
            "HOST": obj.db_host,
            "PORT": obj.db_port,
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }

        # Assumes settings.py is in a subdirectory of BASE_DIR
        config_path = Path(__file__).resolve().parent.parent / "asterisk_db.json"
        with open(config_path, "w") as f:
            json.dump(db_config, f, indent=4)

        messages.add_message(
            request, messages.WARNING, "Настройки базы данных Asterisk были изменены. Требуется перезапуск сервера, чтобы применить их."
        )
