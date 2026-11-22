from django.contrib import admin

from .models import Option, Poll


class OptionInline(admin.TabularInline):
    model = Option
    extra = 0
    ordering = ("position",)


@admin.register(Poll)
class PollAdmin(admin.ModelAdmin):
    list_display = ("question", "author", "created_at")
    list_select_related = ("author",)
    search_fields = ("question", "author__username")
    date_hierarchy = "created_at"
    raw_id_fields = ("author",)
    inlines = [OptionInline]


@admin.register(Option)
class OptionAdmin(admin.ModelAdmin):
    list_display = ("text", "poll", "position")
    list_select_related = ("poll",)
    search_fields = ("text", "poll__question")
    raw_id_fields = ("poll",)
