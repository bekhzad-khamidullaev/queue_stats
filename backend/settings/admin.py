from django.contrib import admin

from .models import GeneralSettings


@admin.register(GeneralSettings)
class GeneralSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not GeneralSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
