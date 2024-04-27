from django import forms


class UrlInputForm(forms.Form):
    url = forms.URLField(label='Enter the URL of the video you want to transcribe', max_length=1000)


class MaterialForm(forms.Form):
    CHOICES = [
        ('English', 'English'),
        ('Ukrainian', 'Ukrainian'),
    ]
    native_language = forms.ChoiceField(choices=CHOICES, widget=forms.Select, label='Enter your native language')
