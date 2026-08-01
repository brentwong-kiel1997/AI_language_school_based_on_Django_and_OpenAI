from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "display_name", "is_staff", "is_verified", "created_at")
    list_filter = ("is_staff", "is_superuser", "is_verified", "is_active")
    search_fields = ("email", "display_name", "username")
    ordering = ("-created_at",)

    fieldsets = BaseUserAdmin.fieldsets + (
        (_("Extra"), {"fields": ("display_name", "preferred_language", "avatar_url", "is_verified")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        (_("Extra"), {"fields": ("email", "display_name")}),
    )
