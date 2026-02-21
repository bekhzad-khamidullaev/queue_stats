from django.contrib import admin

from .models import AgentDisplayMapping, GeneralSettings, OperatorPayoutRate, QueueDisplayMapping


@admin.register(GeneralSettings)
class GeneralSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not GeneralSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(QueueDisplayMapping)
class QueueDisplayMappingAdmin(admin.ModelAdmin):
    list_display = ("queue_system_name", "queue_display_name")
    search_fields = ("queue_system_name", "queue_display_name")


@admin.register(AgentDisplayMapping)
class AgentDisplayMappingAdmin(admin.ModelAdmin):
    list_display = ("agent_system_name", "agent_display_name")
    search_fields = ("agent_system_name", "agent_display_name")


@admin.register(OperatorPayoutRate)
class OperatorPayoutRateAdmin(admin.ModelAdmin):
    list_display = ("agent_system_name", "rate_per_minute")
    search_fields = ("agent_system_name",)
