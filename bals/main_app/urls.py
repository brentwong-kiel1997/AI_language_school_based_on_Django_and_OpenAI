from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('url_input', views.url_input, name='url_input'),
    path('wait/<slug:video_id>/', views.wait_view, name='wait'),
    path('transcript/<slug:transcribe_slug>', views.transcript, name='transcript'),
]