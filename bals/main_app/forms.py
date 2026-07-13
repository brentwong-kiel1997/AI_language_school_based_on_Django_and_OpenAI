from django import forms
from django.utils.translation import gettext_lazy as _


class UrlInputForm(forms.Form):
    url = forms.URLField(label=_("YouTube video URL"), max_length=1000)


class MaterialForm(forms.Form):
    CHOICES = [
        ('Chinese', _("Chinese")),
        ('English', _("English")),
        ('Ukrainian', _("Ukrainian")),
    ]
    native_language = forms.ChoiceField(choices=CHOICES, widget=forms.Select, label=_("Your native language"))
