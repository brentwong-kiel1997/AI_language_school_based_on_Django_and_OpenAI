from django.shortcuts import render, redirect
from .forms import UrlInputForm, MaterialForm
from .utils import Transcribe, Generator
from .models import Transcribed_Video, Learning_Material
import ast
from django.contrib import messages
import json



# Create your views here.
def home(request):
    model = Transcribed_Video.objects.all()

    # Retrieve unique video languages for filtering
    languages = Transcribed_Video.objects.values_list('video_language', flat=True).distinct()

    # Handle language filtering
    language_filter = request.GET.get('language_filter')
    if language_filter:
        model = model.filter(video_language=language_filter)

    return render(request, 'main_app/home.html', {'model': model, 'languages': languages})



def url_input(request):
    if request.method == 'POST':
        form = UrlInputForm(request.POST)
        if form.is_valid():
            if 'https://www.youtube.com/watch?v=' in form.cleaned_data['url']:
                video_url = form.cleaned_data['url']
                video_id = video_url[32:43]
                return redirect('wait', video_id=video_id)
            elif 'https://youtu.be/' in form.cleaned_data['url']:
                video_url = form.cleaned_data['url']
                video_id = video_url[17:28]
                return redirect('wait', video_id=video_id)
            else:
                messages.error(request, "Invalid url.")
                return redirect('url_input')
    else:
        form = UrlInputForm()
    return render(request, 'main_app/url_input.html', {'form': form})


def wait_view(request, video_id):
    video_url = 'https://www.youtube.com/watch?v=' + video_id
    if Transcribed_Video.objects.filter(video_id=video_id).exists():
        model = Transcribed_Video.objects.get(video_id=video_id)
    else:
        try:
            trans = Transcribe(url=video_url)
            trans.audio2text()
            model = Transcribed_Video(video_id=trans.id,
                                      video_language=trans.language,
                                      video_title=trans.title,
                                      video_length=int(trans.duration),
                                      video_text=trans.text_with_ts,
                                      video_transcribe=trans.transcript,
                                      uploaded_date=trans.upload_date)
            model.save()
            model = Transcribed_Video.objects.get(video_id=trans.id)
        except ValueError:
            messages.error(request, "Invalid url.")
            return redirect('url_input')

    return redirect('transcript', transcribe_slug=model.slug)
    # return render(request, 'main_app/wait.html', {'video_url': video_url})


def transcript(request, transcribe_slug):
    model = Transcribed_Video.objects.get(slug=transcribe_slug)
    embedded = f"https://www.youtube.com/embed/{model.video_id}?si=a8LSWwdSKrRParp8"
    text = ast.literal_eval(model.video_text)
    model2 = Learning_Material.objects.filter(linked_video=model)
    if request.method == 'POST':
        form = MaterialForm(request.POST)
        if form.is_valid():
            native_language = form.cleaned_data['native_language']
            transcribe_slug = model.slug
            return redirect('wait_for_chatbot',
                            transcribe_slug=transcribe_slug,
                            native_language=native_language)
        else:
            return redirect('transcript', transcribe_slug=transcribe_slug)
    else:
        form = MaterialForm()

    return render(request, 'main_app/transcript.html', {'text': text,
                                                        'embedded': embedded,
                                                        'model': model,
                                                        'form': form,
                                                        'model2': model2})


def wait_for_chatbot(request, transcribe_slug, native_language):
    model = Transcribed_Video.objects.get(slug=transcribe_slug)
    if Learning_Material.objects.filter(linked_video=model, native_language=native_language).exists():
        model2 = Learning_Material.objects.get(linked_video=model, native_language=native_language)
    else:
        test = Generator(target_language=model.video_language,
                         native_language=native_language,
                         text=model.video_text)
        test.chatbox()
        model2 = Learning_Material(linked_video=model,
                                   native_language=native_language,
                                   material=test.reply)
        model2.save()
    return redirect('learning_material', video_slug=model.video_id, native_language_slug=native_language)


def learning_material(request, video_slug, native_language_slug):
    model = Transcribed_Video.objects.get(video_id=video_slug)
    model2 = Learning_Material.objects.get(linked_video=model, native_language=native_language_slug)
    video_text = ast.literal_eval(model.video_text)
    embedded = f"https://www.youtube.com/embed/{model.video_id}?si=a8LSWwdSKrRParp8"
    reply = json.loads(model2.material)
    context = {'model2': model2,
               'model': model,
               'video_text': video_text,
               'embedded': embedded,
               'reply': reply,}
    return render(request, 'main_app/learning_material.html',
                  context=context)
