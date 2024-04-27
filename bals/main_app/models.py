from django.db import models
from django.utils.text import slugify


# Create your models here.

class Transcribed_Video(models.Model):
    video_id = models.CharField(max_length=100, unique=True)
    video_language = models.CharField(max_length=100)
    video_title = models.CharField(max_length=100)
    video_length = models.IntegerField()
    slug = models.SlugField(max_length=100, unique=True)
    video_text = models.TextField()
    video_transcribe = models.TextField()
    uploaded_date = models.DateTimeField()

    def __str__(self):
        return self.video_title

    def save(self, *args, **kwargs):
        self.slug = slugify(self.video_id)
        super(Transcribed_Video, self).save(*args, **kwargs)


class Learning_Material(models.Model):
    linked_video = models.ForeignKey(Transcribed_Video, on_delete=models.CASCADE)
    native_language = models.CharField(max_length=100)
    material = models.TextField()
    slug = models.SlugField(max_length=100, unique=True)

    def __str__(self):
        return self.linked_video.video_title + '-' + self.native_language

    def save(self, *args, **kwargs):
        self.slug = slugify(self.linked_video.video_id + '-' + self.native_language)
        super(Learning_Material, self).save(*args, **kwargs)
