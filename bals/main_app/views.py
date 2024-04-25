from django.shortcuts import render, redirect
from .forms import UrlInputForm

# Create your views here.
def home(request):
    return render(request, 'main_app/home.html')


def url_input(request):
    if request.method == 'POST':
        form = UrlInputForm(request.POST)
        if form.is_valid():
            video_url = form.cleaned_data['url']
            video_id = video_url.strip('https://www.youtube.com/watch?v=')
            return redirect('wait', video_id=video_id)
    else:
        form = UrlInputForm()
    return render(request, 'main_app/url_input.html', {'form': form})


def wait_view(request, video_id):
    video_url = 'https://www.youtube.com/watch?v=' + video_id
    return render(request, 'main_app/wait.html', {'video_url': video_url})


def transcript(request, transcribe_slug):
    pass
