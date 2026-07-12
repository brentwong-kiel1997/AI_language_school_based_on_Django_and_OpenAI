from django.db import models
from django.utils import timezone
from django.utils.text import slugify



# Status of the background job that downloads/transcribes a YouTube video
# or generates learning materials. ``pending`` and ``processing`` are
# transient; the wait page polls until the row flips to ``ready`` (or
# ``failed``). Keeping it on the row means a server restart loses no
# information and we don't need an in-memory dict to coordinate.
JOB_PENDING = "pending"
JOB_PROCESSING = "processing"
JOB_READY = "ready"
JOB_FAILED = "failed"
JOB_STATUS_CHOICES = (
    (JOB_PENDING, "pending"),
    (JOB_PROCESSING, "processing"),
    (JOB_READY, "ready"),
    (JOB_FAILED, "failed"),
)


# Create your models here.

class Transcribed_Video(models.Model):
    video_id = models.CharField(max_length=100, unique=True)
    video_language = models.CharField(max_length=100)
    video_title = models.CharField(max_length=100)
    video_length = models.IntegerField()
    slug = models.SlugField(max_length=100, unique=True)
    video_text = models.TextField(blank=True)
    video_transcribe = models.TextField(blank=True)
    uploaded_date = models.DateTimeField(null=True, blank=True)
    # Background job bookkeeping – the wait page polls on these.
    status = models.CharField(
        max_length=20,
        choices=JOB_STATUS_CHOICES,
        default=JOB_PENDING,
    )
    error_message = models.TextField(blank=True)
    # ``default=timezone.now`` (not ``auto_now_add``) so makemigrations
    # can backfill existing rows in one shot, and so we can stamp the
    # field from inside background threads if we need to.
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.video_title

    def save(self, *args, **kwargs):
        self.slug = slugify(self.video_id)
        self.updated_at = timezone.now()
        super(Transcribed_Video, self).save(*args, **kwargs)



class Learning_Material(models.Model):
    linked_video = models.ForeignKey(Transcribed_Video, on_delete=models.CASCADE)
    native_language = models.CharField(max_length=100)
    material = models.TextField(blank=True)
    slug = models.SlugField(max_length=100, unique=True)
    status = models.CharField(
        max_length=20,
        choices=JOB_STATUS_CHOICES,
        default=JOB_PENDING,
    )
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.linked_video.video_title + '-' + self.native_language

    def save(self, *args, **kwargs):
        self.slug = slugify(self.linked_video.video_id + '-' + self.native_language)
        self.updated_at = timezone.now()
        super(Learning_Material, self).save(*args, **kwargs)


