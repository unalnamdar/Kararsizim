from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .forms import LoginThrottleMixin
from .models import User


class ThrottledAdminLoginForm(LoginThrottleMixin, AdminAuthenticationForm):
    """The admin sign-in page shares the site's limit on password guesses."""


admin.site.login_form = ThrottledAdminLoginForm


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("-date_joined",)
    list_display = ("username", "email", "is_staff", "is_active", "date_joined")
    search_fields = ("username", "email")
    fieldsets = (
        (None, {"fields": ("email", "username", "password")}),
        ("Yetkiler", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Önemli tarihler", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "username", "password1", "password2")}),
    )
