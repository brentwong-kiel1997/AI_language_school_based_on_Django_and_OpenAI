from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """Custom user model with email as the primary identifier."""

    email = models.EmailField(_("email address"), unique=True)
    display_name = models.CharField(_("display name"), max_length=80, blank=True)
    preferred_language = models.CharField(
        _("preferred interface language"),
        max_length=10,
        default="zh",
        choices=[("zh", "简体中文"), ("en", "English")],
    )
    avatar_url = models.URLField(_("avatar URL"), blank=True)
    is_verified = models.BooleanField(_("email verified"), default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        ordering = ["-created_at"]

    def __str__(self):
        return self.display_name or self.email

    def get_short_name(self):
        return self.display_name or self.email.split("@")[0]
