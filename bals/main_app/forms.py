from django import forms


class UrlInputForm(forms.Form):
    url = forms.URLField(label='Enter the URL of the video you want to transcribe', max_length=1000)
