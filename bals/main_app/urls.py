from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('url_input', views.url_input, name='url_input'),
    path('wait/<slug:video_id>/', views.wait_view, name='wait'),
    path('transcript/<slug:transcribe_slug>', views.transcript, name='transcript'),
    path('wait_for_chatbot/<slug:transcribe_slug>/<slug:native_language>', views.wait_for_chatbot, name='wait_for_chatbot'),
    path('learning_material/<slug:video_slug>/<slug:native_language_slug>', views.learning_material, name='learning_material'),
    path(
        'learning_material/<slug:video_slug>/<slug:native_language_slug>/export.json',
        views.learning_material_export,
        name='learning_material_export',
    ),
    path(
        'api/progress/<slug:video_slug>/<slug:native_language_slug>/',
        views.update_progress,
        name='update_progress',
    ),
]