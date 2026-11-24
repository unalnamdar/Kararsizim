from django.contrib import admin
from django.db.models import Count

from .models import Option, Poll, Report, Vote


class OptionInline(admin.TabularInline):
    model = Option
    extra = 0
    ordering = ("position",)


class ReportInline(admin.TabularInline):
    model = Report
    extra = 0
    fields = ("reason", "note", "user", "created_at")
    readonly_fields = fields
    can_delete = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Poll)
class PollAdmin(admin.ModelAdmin):
    list_display = ("question", "author", "created_at", "closes_at", "report_count")
    list_select_related = ("author",)
    search_fields = ("question", "author__username")
    date_hierarchy = "created_at"
    raw_id_fields = ("author",)
    inlines = [OptionInline, ReportInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_reports=Count("reports", distinct=True))

    @admin.display(description="bildirim", ordering="_reports")
    def report_count(self, obj):
        return obj._reports


@admin.register(Option)
class OptionAdmin(admin.ModelAdmin):
    list_display = ("text", "poll", "position")
    list_select_related = ("poll",)
    search_fields = ("text", "poll__question")
    raw_id_fields = ("poll",)


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ("poll", "option", "user", "voter_key", "ip_hash", "created_at")
    list_select_related = ("poll", "option", "user")
    search_fields = ("poll__question", "user__username", "voter_key", "ip_hash")
    raw_id_fields = ("poll", "option", "user")
    date_hierarchy = "created_at"


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("poll", "reason", "note", "reporter_name", "created_at")
    list_filter = ("reason", "created_at")
    list_select_related = ("poll", "user")
    search_fields = ("poll__question", "note", "user__username")
    raw_id_fields = ("poll", "user")
    date_hierarchy = "created_at"

    @admin.display(description="bildiren")
    def reporter_name(self, obj):
        return f"@{obj.user.username}" if obj.user else "misafir"
