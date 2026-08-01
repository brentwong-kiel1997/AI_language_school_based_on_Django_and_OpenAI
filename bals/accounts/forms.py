from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class RegisterForm(forms.ModelForm):
    password1 = forms.CharField(
        label=_("Password"),
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": _("At least 8 characters"),
            "autocomplete": "new-password",
        }),
    )
    password2 = forms.CharField(
        label=_("Confirm password"),
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": _("Re-enter your password"),
            "autocomplete": "new-password",
        }),
    )

    class Meta:
        model = User
        fields = ("email", "display_name")
        widgets = {
            "email": forms.EmailInput(attrs={
                "class": "form-control",
                "placeholder": "you@example.com",
                "autocomplete": "email",
            }),
            "display_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": _("How should we call you?"),
                "autocomplete": "name",
            }),
        }

    def clean_email(self):
        email = self.cleaned_data.get("email", "").lower().strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_("This email is already registered."))
        return email

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", _("Passwords do not match."))
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        user.username = user.email  # keep username in sync
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    username = forms.EmailField(
        label=_("Email"),
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "placeholder": "you@example.com",
            "autocomplete": "email",
            "autofocus": True,
        }),
    )
    password = forms.CharField(
        label=_("Password"),
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": _("Your password"),
            "autocomplete": "current-password",
        }),
    )


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("display_name", "preferred_language", "avatar_url")
        widgets = {
            "display_name": forms.TextInput(attrs={"class": "form-control"}),
            "preferred_language": forms.Select(attrs={"class": "form-select"}),
            "avatar_url": forms.URLInput(attrs={
                "class": "form-control",
                "placeholder": "https://…",
            }),
        }


class CustomPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(
        label=_("Email"),
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "placeholder": "you@example.com",
            "autocomplete": "email",
        }),
    )


class CustomSetPasswordForm(SetPasswordForm):
    new_password1 = forms.CharField(
        label=_("New password"),
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "autocomplete": "new-password",
        }),
    )
    new_password2 = forms.CharField(
        label=_("Confirm new password"),
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "autocomplete": "new-password",
        }),
    )
