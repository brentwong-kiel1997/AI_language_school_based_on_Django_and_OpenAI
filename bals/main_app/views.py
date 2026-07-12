"""HTTP views.

The two slow views (``wait_view`` and ``wait_for_chatbot``) used to run
the YouTube download + ASR + LLM calls synchronously inside the request
thread, which made the browser sit on a blank loading screen for the
full round trip (often 30 s – 2 min). The user kept reporting "it
always gets stuck".  The fix is to fire the work on a daemon thread
(:func:`run_in_background` in :mod:`utils`) and reflect the outcome on
the row itself via the ``status`` field.  The wait page now polls until
``status == ready`` (or ``failed``) and then redirects.
"""

from __future__ import annotations

import ast
import json
import logging
import re
from urllib.parse import parse_qs, urlparse

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .forms import MaterialForm, UrlInputForm
from .models import (
    JOB_FAILED,
    JOB_PENDING,
    JOB_PROCESSING,
    JOB_READY,
    Learning_Material,
    Transcribed_Video,
)
from .utils import Generator, Transcribe, run_in_background

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Background job worker functions
# ---------------------------------------------------------------------------


def _do_transcription_job(video_id: str) -> None:
    """Worker: download + transcribe a YouTube video, write the row.

    Called on a daemon thread (no request context). It looks up the row
    by ``video_id``, flips its ``status`` to ``processing``, runs the
    full YouTube->ASR pipeline, and finally writes the outcome back to
    ``status`` = ``ready`` or ``failed``.
    """
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    row = Transcribed_Video.objects.get(video_id=video_id)
    row.status = JOB_PROCESSING
    row.error_message = ""
    row.save(update_fields=["status", "error_message", "updated_at"])

    try:
        trans = Transcribe(url=video_url)
        trans.audio2text()
    except Exception as exc:
        row.refresh_from_db()
        row.status = JOB_FAILED
        row.error_message = (str(exc) or exc.__class__.__name__)[:1000]
        row.save(update_fields=["status", "error_message", "updated_at"])
        logger.exception("transcription failed for %s", video_id)
        return

    # yt-dlp is happy but we still need to persist the transcript payload.
    row.refresh_from_db()
    row.video_title = trans.title
    row.video_language = trans.language
    row.video_length = int(trans.duration)
    row.video_text = json.dumps(trans.text_with_ts, ensure_ascii=False)
    row.video_transcribe = json.dumps(trans.transcript, ensure_ascii=False)
    if trans.upload_date:
        try:
            row.uploaded_date = timezone.datetime.strptime(
                trans.upload_date, "%Y-%m-%d"
            ).replace(tzinfo=timezone.get_current_timezone())
        except ValueError:
            row.uploaded_date = None
    row.status = JOB_READY
    row.save()


def _do_learning_material_job(transcribe_slug: str, native_language: str) -> None:
    """Worker: chat the LLM, write the learning-material row."""
    row = Learning_Material.objects.get(
        linked_video__slug=transcribe_slug,
        native_language=native_language,
    )
    row.status = JOB_PROCESSING
    row.error_message = ""
    row.save(update_fields=["status", "error_message", "updated_at"])

    video = row.linked_video
    try:
        gen = Generator(
            target_language=video.video_language,
            native_language=native_language,
            text=video.video_text,
        )
        gen.chatbox()
    except Exception as exc:
        row.refresh_from_db()
        row.status = JOB_FAILED
        row.error_message = (str(exc) or exc.__class__.__name__)[:1000]
        row.save(update_fields=["status", "error_message", "updated_at"])
        logger.exception("learning material failed for %s/%s",
                         transcribe_slug, native_language)
        return

    row.refresh_from_db()
    row.material = gen.reply
    row.status = JOB_READY
    row.save()


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def home(request):
    model = Transcribed_Video.objects.all()

    # Retrieve unique video languages for filtering
    languages = Transcribed_Video.objects.values_list(
        "video_language", flat=True
    ).distinct()

    # Handle language filtering
    language_filter = request.GET.get("language_filter")
    if language_filter:
        model = model.filter(video_language=language_filter)

    return render(
        request,
        "main_app/home.html",
        {"model": model, "languages": languages},
    )


@require_http_methods(["GET", "POST"])
def url_input(request):
    if request.method == "POST":
        form = UrlInputForm(request.POST)
        if form.is_valid():
            url = form.cleaned_data["url"]
            parsed = urlparse(url)
            host = parsed.netloc.lower().removeprefix("www.")
            video_id = ""
            if host in {"youtube.com", "m.youtube.com"}:
                if parsed.path == "/watch":
                    video_id = parse_qs(parsed.query).get("v", [""])[0]
                elif parsed.path.startswith(("/shorts/", "/embed/")):
                    video_id = parsed.path.strip("/").split("/")[1]
            elif host == "youtu.be":
                video_id = parsed.path.strip("/").split("/")[0]
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                return redirect("wait", video_id=video_id)
            messages.error(request, "无法识别这个 YouTube 链接，请检查后重试。")
    else:
        form = UrlInputForm()
    return render(request, "main_app/url_input.html", {"form": form})


def wait_view(request, video_id):
    """Submit a YouTube URL, kick off the download in the background, and
    immediately redirect to the polling wait page.

    State machine for the row:

        (no row)  -> create with status=pending
        pending   -> if no thread is alive, launch one
        processing -> just render the wait page
        ready     -> redirect to transcript
        failed    -> render the wait page (with the error inline)
    """
    video_url = "https://www.youtube.com/watch?v=" + video_id
    row = Transcribed_Video.objects.filter(video_id=video_id).first()

    if row is None:
        # First time we see this URL. Create the row in ``pending`` state
        # and fire the worker.  We can't populate the title / language /
        # length until the worker finishes, so stash empty strings /
        # 0 for now and the template only renders them when ``ready``.
        row = Transcribed_Video.objects.create(
            video_id=video_id,
            video_language="",
            video_title="(loading)",
            video_length=0,
            uploaded_date=timezone.now(),
            status=JOB_PENDING,
        )

    if request.GET.get("status") == "1":
        return JsonResponse({
            "status": row.status,
            "error": row.error_message,
            "redirect_url": f"/transcript/{row.slug}" if row.status == JOB_READY else "",
        })

    if row.status == JOB_READY:
        return redirect("transcript", transcribe_slug=row.slug)

    should_retry = request.GET.get("retry") == "1"
    if row.status == JOB_PENDING or (row.status == JOB_FAILED and should_retry):
        # Failed jobs retry only after an explicit user action.
        row.status = JOB_PENDING
        row.error_message = ""
        row.save(update_fields=["status", "error_message", "updated_at"])
        run_in_background(
            _do_transcription_job,
            video_id,
            thread_name=f"bals-transcribe-{video_id}",
        )

    return render(
        request,
        "main_app/wait.html",
        {
            "video_url": video_url,
            "video_id": video_id,
            "row": row,
            "poll_target": "wait",
            "poll_args": {"video_id": video_id},
            "poll_on_ready_redirect": f"/transcript/{row.slug}",
        },
    )


def transcript(request, transcribe_slug):
    """Render the transcript + the form to start the learning-material job."""
    model = Transcribed_Video.objects.get(slug=transcribe_slug)
    if model.status != JOB_READY:
        # Someone bookmarked the transcript URL but the job hasn't finished.
        return redirect("wait", video_id=model.video_id)

    embed_origin = request.build_absolute_uri("/").rstrip("/")
    embedded = (
        f"https://www.youtube.com/embed/{model.video_id}"
        f"?origin={embed_origin}&rel=0&playsinline=1&enablejsapi=1"
    )
    text = ast.literal_eval(model.video_text) if model.video_text else {}
    model2 = Learning_Material.objects.filter(linked_video=model)
    if request.method == "POST":
        form = MaterialForm(request.POST)
        if form.is_valid():
            native_language = form.cleaned_data["native_language"]
            return redirect(
                "wait_for_chatbot",
                transcribe_slug=transcribe_slug,
                native_language=native_language,
            )
        else:
            return redirect("transcript", transcribe_slug=transcribe_slug)
    else:
        form = MaterialForm()

    return render(
        request,
        "main_app/transcript.html",
        {
            "text": text,
            "embedded": embedded,
            "youtube_url": f"https://www.youtube.com/watch?v={model.video_id}",
            "model": model,
            "form": form,
            "model2": model2,
        },
    )


def wait_for_chatbot(request, transcribe_slug, native_language):
    """Mirror of ``wait_view`` for the learning-material job."""
    video = Transcribed_Video.objects.get(slug=transcribe_slug)
    row = Learning_Material.objects.filter(
        linked_video=video, native_language=native_language
    ).first()

    if row is None:
        row = Learning_Material.objects.create(
            linked_video=video,
            native_language=native_language,
            material="",
            status=JOB_PENDING,
        )

    if request.GET.get("status") == "1":
        redirect_url = (
            f"/learning_material/{video.video_id}/{native_language}"
            if row.status == JOB_READY else ""
        )
        return JsonResponse({"status": row.status, "error": row.error_message,
                             "redirect_url": redirect_url})

    if row.status == JOB_READY:
        return redirect(
            "learning_material",
            video_slug=video.video_id,
            native_language_slug=native_language,
        )

    should_retry = request.GET.get("retry") == "1"
    if row.status == JOB_PENDING or (row.status == JOB_FAILED and should_retry):
        row.status = JOB_PENDING
        row.error_message = ""
        row.save(update_fields=["status", "error_message", "updated_at"])
        run_in_background(
            _do_learning_material_job,
            transcribe_slug,
            native_language,
            thread_name=f"bals-lm-{video.video_id}-{native_language}",
        )

    return render(
        request,
        "main_app/wait.html",
        {
            "video_url": f"/transcript/{transcribe_slug}",
            "video_id": video.video_id,
            "row": row,
            "poll_target": "wait_for_chatbot",
            "poll_args": {
                "transcribe_slug": transcribe_slug,
                "native_language": native_language,
            },
            "poll_on_ready_redirect": (
                f"/learning_material/{video.video_id}/{native_language}"
            ),
        },
    )


def learning_material(request, video_slug, native_language_slug):
    model = Transcribed_Video.objects.get(video_id=video_slug)
    model2 = Learning_Material.objects.get(
        linked_video=model, native_language=native_language_slug
    )
    if model2.status != JOB_READY:
        return redirect(
            "wait_for_chatbot",
            transcribe_slug=model.slug,
            native_language=native_language_slug,
        )

    video_text = ast.literal_eval(model.video_text) if model.video_text else {}
    embed_origin = request.build_absolute_uri("/").rstrip("/")
    embedded = (
        f"https://www.youtube.com/embed/{model.video_id}"
        f"?origin={embed_origin}&rel=0&playsinline=1&enablejsapi=1"
    )
    reply = json.loads(model2.material) if model2.material else {}
    context = {
        "model2": model2,
        "model": model,
        "video_text": video_text,
        "embedded": embedded,
        "youtube_url": f"https://www.youtube.com/watch?v={model.video_id}",
        "reply": reply,
    }
    return render(request, "main_app/learning_material.html", context=context)
