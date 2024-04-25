from django.contrib import admin
from .models import Transcribed_Video
# Register your models here.

@admin.register(Transcribed_Video)
class CategoryAdmin(admin.ModelAdmin):
    prepopulated_fields = {'slug': ('video_id', )}