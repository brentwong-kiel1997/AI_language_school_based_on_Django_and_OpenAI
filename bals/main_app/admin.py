from django.contrib import admin
from .models import Transcribed_Video, Learning_Material
# Register your models here.

@admin.register(Transcribed_Video)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['video_title', 'video_language', 'video_length']

@admin.register(Learning_Material)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['linked_video', 'native_language']