from django.db import models


# Create your models here.

class Transcribed_Video(models.Model):
    video_id = models.CharField(max_length=100, unique=True)
    video_language = models.CharField(max_length=100)
    video_title = models.CharField(max_length=100)
    video_length = models.IntegerField()
    slug = models.SlugField(max_length=100, unique=True)
    video_text = models.TextField()
    video_transcribe = models.TextField()

    def __str__(self):
        return self.video_title
