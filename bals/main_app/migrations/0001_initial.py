# NOTE: This migration was retroactively completed when status /
# error_message / created_at / updated_at columns were added. The
# ``Learning_Material`` table already existed in the on-disk sqlite
# (it was created out-of-band against an older model definition) so
# we declare it here for migration-state purposes, but the
# corresponding ``CREATE TABLE`` is faked on existing databases via
# ``manage.py migrate main_app --fake-initial``.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Transcribed_Video',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('video_id', models.CharField(max_length=100, unique=True)),
                ('video_language', models.CharField(max_length=100)),
                ('video_title', models.CharField(max_length=100)),
                ('video_length', models.IntegerField()),
                ('slug', models.SlugField(max_length=100, unique=True)),
                ('video_text', models.TextField(blank=True)),
                ('video_transcribe', models.TextField(blank=True)),
                ('uploaded_date', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(choices=[('pending', 'pending'), ('processing', 'processing'), ('ready', 'ready'), ('failed', 'failed')], default='pending', max_length=20)),
                ('error_message', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(default=django.utils.timezone.now)),
            ],
        ),
        migrations.CreateModel(
            name='Learning_Material',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('native_language', models.CharField(max_length=100)),
                ('material', models.TextField(blank=True)),
                ('slug', models.SlugField(max_length=100, unique=True)),
                ('status', models.CharField(choices=[('pending', 'pending'), ('processing', 'processing'), ('ready', 'ready'), ('failed', 'failed')], default='pending', max_length=20)),
                ('error_message', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('linked_video', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='main_app.transcribed_video')),
            ],
        ),
    ]
