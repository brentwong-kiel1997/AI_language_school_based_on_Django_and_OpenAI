from django import forms


class UrlInputForm(forms.Form):
    url = forms.URLField(label='YouTube 视频链接', max_length=1000)


class MaterialForm(forms.Form):
    CHOICES = [
        ('Chinese', '中文'),
        ('English', '英语'),
        ('Ukrainian', '乌克兰语'),
    ]
    native_language = forms.ChoiceField(choices=CHOICES, widget=forms.Select, label='你的母语')
