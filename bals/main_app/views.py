"""HTTP views.

The two slow views (``wait_view`` and ``wait_for_chatbot``) used to run
the YouTube download + LLM calls synchronously inside the request
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
from urllib.parse import parse_qs, urlencode, urlparse

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from prompts.registry import canonical_target_language

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


def _youtube_embed_url(request, video_id):
    """Build a YouTube embed URL with the request's scheme and host."""
    query = urlencode({
        "origin": request.build_absolute_uri("/").rstrip("/"),
        "rel": 0,
        "playsinline": 1,
        "enablejsapi": 1,
    })
    return f"https://www.youtube.com/embed/{video_id}?{query}"


# ---------------------------------------------------------------------------
# Background job worker functions
# ---------------------------------------------------------------------------


def _do_transcription_job(video_id: str) -> None:
    """Worker: download + transcribe a YouTube video, write the row.

    Called on a daemon thread (no request context). It looks up the row
    by ``video_id``, flips its ``status`` to ``processing``, runs the
    full YouTube->caption pipeline, and finally writes the outcome back to
    ``status`` = ``ready`` or ``failed``.
    """
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        row = Transcribed_Video.objects.get(video_id=video_id)
    except Transcribed_Video.DoesNotExist:
        logger.exception("transcription job: video_id %s not found", video_id)
        return
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
    row.video_title = trans.title[:300]
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
    try:
        row = Learning_Material.objects.get(
            linked_video__slug=transcribe_slug,
            native_language=native_language,
        )
    except Learning_Material.DoesNotExist:
        logger.exception(
            "learning material job: slug %s / lang %s not found",
            transcribe_slug,
            native_language,
        )
        return
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
    from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

    model = Transcribed_Video.objects.all().order_by('-created_at')

    # Retrieve unique video languages for filtering
    languages = Transcribed_Video.objects.values_list(
        "video_language", flat=True
    ).distinct()

    # Handle language filtering
    language_filter = request.GET.get("language_filter")
    if language_filter:
        model = model.filter(video_language=language_filter)

    # Title search
    query = (request.GET.get("q") or "").strip()
    if query:
        model = model.filter(video_title__icontains=query)

    # Pagination
    paginator = Paginator(model, 12)  # 12 courses per page
    page = request.GET.get('page')
    try:
        model = paginator.page(page)
    except PageNotAnInteger:
        model = paginator.page(1)
    except EmptyPage:
        model = paginator.page(paginator.num_pages)

    return render(
        request,
        "main_app/home.html",
        {"model": model, "languages": languages},
    )


@require_http_methods(["GET", "POST"])
@login_required
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
            messages.error(request, _("We couldn't recognize this YouTube URL. Please check it and try again."))
    else:
        form = UrlInputForm()
    return render(request, "main_app/url_input.html", {"form": form})


@login_required
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
            video_title="(loading…)",
            video_length=0,
            uploaded_date=timezone.now(),
            status=JOB_PENDING,
        )

    if request.GET.get("status") == "1":
        return JsonResponse({
            "status": row.status,
            "error": row.error_message,
            "redirect_url": reverse("transcript", kwargs={"transcribe_slug": row.slug}) if row.status == JOB_READY else "",
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
            "poll_on_ready_redirect": reverse("transcript", kwargs={"transcribe_slug": row.slug}),
        },
    )


def transcript(request, transcribe_slug):
    """Render the transcript + the form to start the learning-material job."""
    model = Transcribed_Video.objects.get(slug=transcribe_slug)
    if model.status != JOB_READY:
        # Someone bookmarked the transcript URL but the job hasn't finished.
        return redirect("wait", video_id=model.video_id)

    embedded = _youtube_embed_url(request, model.video_id)
    try:
        text = ast.literal_eval(model.video_text) if model.video_text else {}
    except (ValueError, SyntaxError):
        text = {}
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
            created_by=request.user if request.user.is_authenticated else None,
        )

    if request.GET.get("status") == "1":
        redirect_url = (
            reverse("learning_material", kwargs={"video_slug": video.video_id, "native_language_slug": native_language})
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
            "video_url": reverse("transcript", kwargs={"transcribe_slug": transcribe_slug}),
            "video_id": video.video_id,
            "row": row,
            "poll_target": "wait_for_chatbot",
            "poll_args": {
                "transcribe_slug": transcribe_slug,
                "native_language": native_language,
            },
            "poll_on_ready_redirect": (
                reverse("learning_material", kwargs={"video_slug": video.video_id, "native_language_slug": native_language})
            ),
        },
    )


def _load_learning_material(video_slug: str, native_language_slug: str) -> dict:
    """Load transcribed video + ready lesson row and the same formatted page data."""
    model = Transcribed_Video.objects.get(video_id=video_slug)
    model2 = Learning_Material.objects.get(
        linked_video=model, native_language=native_language_slug
    )
    try:
        video_text = ast.literal_eval(model.video_text) if model.video_text else {}
    except (ValueError, SyntaxError):
        video_text = {}
    if not isinstance(video_text, dict):
        video_text = {}
    try:
        reply = json.loads(model2.material) if model2.material else {}
    except (TypeError, json.JSONDecodeError):
        reply = {}
    if not isinstance(reply, dict):
        reply = {}
    translation = reply.get("translation") if isinstance(reply.get("translation"), dict) else {}
    return {
        "model": model,
        "model2": model2,
        "video_text": video_text,
        "reply": reply,
        "word_items": _format_lexicon_entries(
            reply.get("import_words"), model.video_language
        ),
        "grammar_items": _format_grammar_entries(reply.get("import_grammars")),
        "listening_items": _format_listening_tasks(reply.get("listening_tasks")),
        "comprehension_items": _format_comprehension_qa(
            reply.get("questions"), reply.get("answers")
        ),
        "expression": _format_expression_section(reply),
        "translation": translation,
    }


def _lesson_export_payload(data: dict) -> dict:
    """JSON consumed by the browser PDF builder (no DOM scraping)."""
    model = data["model"]
    model2 = data["model2"]
    reply = data["reply"]
    expression = data["expression"]
    sections = []

    def add(section_id: str, title: str, section_type: str, **body):
        sections.append({"id": section_id, "title": title, "type": section_type, **body})

    can_do = reply.get("can_do") if isinstance(reply.get("can_do"), list) else []
    can_do = [str(x).strip() for x in can_do if str(x).strip()]
    if can_do:
        add("goals", str(_("Lesson goals")), "list", items=can_do)

    warm_up = reply.get("warm_up") if isinstance(reply.get("warm_up"), list) else []
    warm_up = [str(x).strip() for x in warm_up if str(x).strip()]
    if warm_up:
        add("warmup", str(_("Warm-up")), "list", items=warm_up)

    if data["word_items"]:
        add("vocab", str(_("Key vocabulary")), "vocab", words=data["word_items"])

    if data["grammar_items"]:
        add("grammar", str(_("Grammar")), "grammar", items=data["grammar_items"])

    if data["listening_items"]:
        add(
            "listening",
            str(_("Listening comprehension")),
            "listening",
            tasks=data["listening_items"],
        )

    if data["comprehension_items"]:
        add(
            "comprehension",
            str(_("Comprehension questions")),
            "qa",
            items=data["comprehension_items"],
        )

    if expression.get("has_content"):
        add(
            "expression",
            str(_("Expression practice")),
            "expression",
            speaking=expression.get("speaking") or {},
            writing=expression.get("writing") or {},
            review=expression.get("review") or [],
        )

    if data["video_text"]:
        add(
            "transcript",
            str(_("Video transcript")),
            "captions",
            rows=[{"time": str(k), "text": str(v)} for k, v in data["video_text"].items()],
        )

    if data["translation"]:
        add(
            "translation",
            str(_("Full translation")),
            "captions",
            rows=[{"time": str(k), "text": str(v)} for k, v in data["translation"].items()],
        )

    return {
        "meta": {
            "brand": "BALS",
            "title": model.video_title or "",
            "kicker": str(_("Your personalized learning course")),
            "target_label": str(_("Target language")),
            "native_label": str(_("Native language")),
            "target": (model.video_language or "").capitalize(),
            "native": (model2.native_language or "").capitalize(),
            "contents": str(_("Contents")),
            "answer": str(_("Answer")),
            "sample": str(_("Sample answer")),
            "footer": str(_("Exported from BALS for personal study")),
            "labels": {
                "speaking": str(_("Speaking task")),
                "writing": str(_("Writing task")),
                "review": str(_("Review")),
                "useful_language": str(_("Useful language")),
                "checklist": str(_("Checklist")),
                "support_phrases": str(_("Support phrases")),
                "typical_collocations": str(_("Typical collocations")),
                "forms": str(_("Forms")),
                "example_sentence": str(_("Example sentence")),
                "note": str(_("Note")),
                "more_phrases": str(_("More phrases")),
                "practice": str(_("Practice")),
                **_lexicon_aside_labels(model.video_language or ""),
            },
        },
        "sections": sections,
    }


def learning_material(request, video_slug, native_language_slug):
    data = _load_learning_material(video_slug, native_language_slug)
    if data["model2"].status != JOB_READY:
        return redirect(
            "wait_for_chatbot",
            transcribe_slug=data["model"].slug,
            native_language=native_language_slug,
        )

    context = {
        "model2": data["model2"],
        "model": data["model"],
        "video_text": data["video_text"],
        "embedded": _youtube_embed_url(request, data["model"].video_id),
        "youtube_url": f"https://www.youtube.com/watch?v={data['model'].video_id}",
        "reply": data["reply"],
        "word_items": data["word_items"],
        "grammar_items": data["grammar_items"],
        "listening_items": data["listening_items"],
        "comprehension_items": data["comprehension_items"],
        "expression": data["expression"],
        "export_url": reverse(
            "learning_material_export",
            kwargs={
                "video_slug": video_slug,
                "native_language_slug": native_language_slug,
            },
        ),
        "lexicon_labels": _lexicon_aside_labels(data["model"].video_language or ""),
    }
    return render(request, "main_app/learning_material.html", context=context)


@require_http_methods(["GET"])
def learning_material_export(request, video_slug, native_language_slug):
    """Return the formatted lesson JSON used to build the learning page / PDF."""
    try:
        data = _load_learning_material(video_slug, native_language_slug)
    except (Transcribed_Video.DoesNotExist, Learning_Material.DoesNotExist):
        return JsonResponse({"error": "not_found"}, status=404)
    if data["model2"].status != JOB_READY:
        return JsonResponse({"error": "not_ready", "status": data["model2"].status}, status=409)
    return JsonResponse(_lesson_export_payload(data))


@require_http_methods(["POST"])
def update_progress(request, video_slug, native_language_slug):
    """AJAX endpoint: record which tab the user is on / mark completed."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "login_required"}, status=401)
    try:
        material = Learning_Material.objects.get(
            linked_video__video_id=video_slug,
            native_language=native_language_slug,
        )
    except Learning_Material.DoesNotExist:
        return JsonResponse({"error": "not_found"}, status=404)

    from .models import LearningProgress

    progress, _ = LearningProgress.objects.get_or_create(
        user=request.user,
        material=material,
    )

    body = json.loads(request.body) if request.body else {}
    tab = body.get("tab", "")
    if tab:
        progress.current_tab = tab
        completed = set(progress.completed_tabs or [])
        completed.add(tab)
        progress.completed_tabs = sorted(completed)
        if progress.status == LearningProgress.STATUS_NOT_STARTED:
            progress.status = LearningProgress.STATUS_IN_PROGRESS
    if body.get("complete"):
        progress.status = LearningProgress.STATUS_COMPLETED
    progress.save(update_fields=["current_tab", "completed_tabs", "status", "last_accessed_at"])

    return JsonResponse({
        "status": progress.status,
        "current_tab": progress.current_tab,
        "completed_tabs": progress.completed_tabs,
    })


def _lexicon_aside_labels(target_language: str) -> dict[str, str]:
    """Dictionary aside abbreviations for the lesson target language."""
    lang = canonical_target_language(target_language)
    if lang == "english":
        return {"syn": "Syn.", "ant": "Ant.", "phrase": "Phr.", "note": "Note"}
    if lang == "german":
        return {"syn": "Syn.", "ant": "Ant.", "phrase": "Redw.", "note": "Anm."}
    if lang == "russian":
        return {"syn": "син.", "ant": "ант.", "phrase": "фраз.", "note": "прим."}
    return {"syn": "Syn.", "ant": "Ant.", "phrase": "Phr.", "note": "Note"}


_RU_POS_ABBR = {
    "noun": "сущ.",
    "verb": "глаг.",
    "adjective": "прил.",
    "adverb": "нареч.",
    "pronoun": "мест.",
    "preposition": "предл.",
    "conjunction": "союз",
    "particle": "част.",
    "interjection": "межд.",
    "numeral": "числ.",
    "substantiv": "сущ.",
}

_EN_POS_ABBR = {
    "noun": "n.",
    "verb": "v.",
    "adjective": "adj.",
    "adverb": "adv.",
    "pronoun": "pron.",
    "preposition": "prep.",
    "conjunction": "conj.",
    "determiner": "det.",
    "interjection": "interj.",
    "phrasal verb": "phr. v.",
    "numeral": "num.",
    "n.": "n.",
    "v.": "v.",
    "adj.": "adj.",
    "adv.": "adv.",
}

_DE_POS_ABBR = {
    "noun": "Subst.",
    "substantiv": "Subst.",
    "verb": "Verb",
    "adjective": "Adj.",
    "adjektiv": "Adj.",
    "adverb": "Adv.",
    "adverbium": "Adv.",
    "preposition": "Präp.",
    "präposition": "Präp.",
    "conjunction": "Konj.",
    "konjunktion": "Konj.",
    "pronoun": "Pron.",
    "pronomen": "Pron.",
}

_GENDER_ABBR = {
    "masculine": "м.",
    "male": "м.",
    "м": "м.",
    "м.": "м.",
    "мужской": "м.",
    "feminine": "ж.",
    "female": "ж.",
    "ж": "ж.",
    "ж.": "ж.",
    "женский": "ж.",
    "neuter": "ср.",
    "ср": "ср.",
    "ср.": "ср.",
    "средний": "ср.",
}

_ASPECT_ABBR = {
    "perfective": "сов.",
    "imperfective": "несов.",
    "сов": "сов.",
    "сов.": "сов.",
    "несов": "несов.",
    "несов.": "несов.",
}


def _as_text_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif item is not None:
                out.append(str(item))
        return out
    return [str(value)]


def _abbr(value, mapping: dict) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return mapping.get(text.lower(), text)


def _headword(entry: dict) -> str:
    """Prefer stress-marked form (dictionary headword)."""
    pron = entry.get("pronunciation")
    if isinstance(pron, dict):
        marked = pron.get("stress_marked")
        if isinstance(marked, str) and marked.strip():
            return marked.strip()
    if isinstance(pron, str) and any(ch in pron for ch in "а́е́и́о́у́ы́э́ю́я́ё́А́Е́И́О́У́Ы́Э́Ю́Я́"):
        return pron.strip()
    return str(entry.get("term") or entry.get("word") or entry.get("label") or "").strip()


def _pos_for_language(pos_raw: str, target_language: str) -> str:
    """Normalize part-of-speech labels for the lesson target language."""
    text = str(pos_raw or "").strip()
    if not text:
        return ""
    lang = canonical_target_language(target_language)
    if lang == "english":
        return _EN_POS_ABBR.get(text.lower(), text)
    if lang == "german":
        return _DE_POS_ABBR.get(text.lower(), text)
    if lang == "russian":
        return _RU_POS_ABBR.get(text.lower(), text)
    return text


def _grammar_tagline(entry: dict, pos: str, target_language: str = "") -> str:
    """Build a language-appropriate grammar tag after the headword."""
    lang = canonical_target_language(target_language)
    bits = []
    if pos:
        bits.append(pos)

    if lang == "english":
        cefr = str(entry.get("cefr") or "").strip()
        if cefr:
            bits.append(cefr)
        register = str(entry.get("register") or "").strip()
        if register and register.lower() not in {"neutral", "null"}:
            bits.append(register)
    elif lang == "german":
        article = str(entry.get("article") or "").strip()
        if article:
            bits.append(article)
        info = entry.get("grammatical_info") if isinstance(entry.get("grammatical_info"), dict) else {}
        gender = str((info or {}).get("gender") or entry.get("gender") or "").strip()
        if gender:
            abbr = {"masculine": "m.", "feminine": "f.", "neuter": "n."}.get(gender.lower(), gender)
            bits.append(abbr)
        forms = entry.get("plural_or_forms") or entry.get("forms")
        if isinstance(forms, dict):
            plural = forms.get("plural") or forms.get("Pl.")
            if isinstance(plural, str) and plural.strip():
                bits.append(f"Pl. {plural.strip()}")
    else:
        info = entry.get("grammatical_info") if isinstance(entry.get("grammatical_info"), dict) else {}
        gender = _abbr(info.get("gender") or entry.get("gender"), _GENDER_ABBR)
        if gender:
            bits.append(gender)
        aspect = _abbr(info.get("aspect"), _ASPECT_ABBR)
        if aspect:
            bits.append(aspect)
        article = str(entry.get("article") or "").strip()
        if article:
            bits.append(article)
        forms = entry.get("forms") or entry.get("plural_or_forms")
        if isinstance(forms, dict):
            genitive = forms.get("genitive") or forms.get("gen.") or forms.get("родительный")
            plural = forms.get("plural") or forms.get("мн.")
            if isinstance(genitive, str) and genitive.strip():
                bits.insert(
                    0,
                    genitive.strip()
                    if genitive.strip().startswith("-")
                    else f"-{genitive.strip()}",
                )
            elif isinstance(plural, str) and plural.strip():
                bits.append(f"мн. {plural.strip()}")
        elif isinstance(forms, str) and forms.strip():
            bits.append(forms.strip())
        cefr = str(entry.get("cefr") or "").strip()
        if cefr:
            bits.append(cefr)

    if not bits:
        return ""
    if len(bits) == 1:
        return bits[0]
    return f"{bits[0]}; " + "; ".join(bits[1:])


def _format_lexicon_entries(value, target_language: str = "") -> list[dict]:
    """Flatten vocabulary JSON into dictionary-style entry dicts."""
    if isinstance(value, dict):
        raw_items = [
            dict(item, term=key) if isinstance(item, dict) else {"term": key, "meaning": item}
            for key, item in value.items()
        ]
    elif isinstance(value, list):
        raw_items = value
    else:
        return []

    entries = []
    for detail in raw_items:
        if not isinstance(detail, dict):
            entries.append({
                "headword": "",
                "grammar": "",
                "ipa": "",
                "multi_sense": False,
                "senses": [{
                    "definition": "",
                    "translation": "",
                    "example": str(detail),
                    "collocations": [],
                }],
                "synonyms": [],
                "antonyms": [],
                "phraseology": [],
                "note": "",
            })
            continue

        pos_raw = str(detail.get("part_of_speech") or "").strip()
        pos = _pos_for_language(pos_raw, target_language)
        senses = detail.get("senses")
        if not isinstance(senses, list) or not senses:
            senses = [{
                "definition": detail.get("meaning") or detail.get("definition") or "",
                "translation": detail.get("translation") or detail.get("meaning") or "",
                "example": detail.get("example") or "",
                "collocations": detail.get("collocations") or [],
            }]
        clean_senses = []
        for sense in senses:
            if not isinstance(sense, dict):
                continue
            cols = sense.get("collocations")
            if isinstance(cols, str):
                cols = [cols] if cols.strip() else []
            elif not isinstance(cols, list):
                cols = []
            clean_senses.append({
                "definition": str(sense.get("definition") or "").strip(),
                "translation": str(sense.get("translation") or "").strip(),
                "example": str(sense.get("example") or "").strip(),
                "collocations": [str(c).strip() for c in cols if str(c).strip()],
            })
        ipa = ""
        pron = detail.get("pronunciation") or detail.get("ipa")
        if isinstance(pron, dict):
            ipa = str(pron.get("ipa") or "").strip()
        elif isinstance(detail.get("ipa"), str):
            ipa = detail["ipa"].strip()
        note = detail.get("usage_note") or detail.get("note") or ""
        entries.append({
            "headword": _headword(detail),
            "grammar": _grammar_tagline(detail, pos, target_language),
            "ipa": ipa,
            "multi_sense": len(clean_senses) > 1,
            "senses": clean_senses,
            "synonyms": _as_text_list(detail.get("synonyms")),
            "antonyms": _as_text_list(detail.get("antonyms")),
            "phraseology": _as_text_list(detail.get("phraseology")),
            "note": str(note).strip() if note is not None else "",
        })
    return entries


def _phrase_pairs(value) -> list[dict]:
    """Normalize [{phrase, translation}] or bullet strings into pair dicts."""
    out = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                phrase = str(
                    item.get("phrase") or item.get("example") or item.get("sentence") or ""
                ).strip()
                if phrase:
                    out.append({
                        "phrase": phrase,
                        "translation": str(item.get("translation") or "").strip(),
                    })
            elif isinstance(item, str) and item.strip():
                phrase, translation = _split_phrase_gloss(item.strip())
                out.append({"phrase": phrase, "translation": translation})
    elif isinstance(value, str) and value.strip():
        for line in value.splitlines():
            line = line.strip().lstrip("•◆-–— ").strip()
            if not line:
                continue
            phrase, translation = _split_phrase_gloss(line)
            out.append({"phrase": phrase, "translation": translation})
    return out


def _split_phrase_gloss(text: str) -> tuple[str, str]:
    for sep in (" — ", " – ", " - ", "：", ": ", "（", "("):
        if sep in text:
            left, right = text.split(sep, 1)
            right = right.rstrip("）)").strip()
            return left.strip(" «»\"'"), right.strip(" «»\"'")
    return text.strip(" «»\"'"), ""


def _forms_lines(value) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        lines = []
        for line in value.splitlines():
            line = line.strip().lstrip("•◆-–— ").strip()
            if line:
                lines.append(line)
        return lines
    return []


def _parse_legacy_grammar_blob(text: str) -> dict:
    """Split old wall-of-text explanation with 【…】 headings into structured parts."""
    if not text or "【" not in text:
        return {"overview": (text or "").strip()}
    chunks = re.split(r"(?=【[^】]+】)", text)
    overview = ""
    sections: dict[str, str] = {}
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        match = re.match(r"【([^】]+)】\s*(.*)", chunk, flags=re.S)
        if match:
            sections[match.group(1).strip()] = match.group(2).strip()
        else:
            overview = chunk
    collocations = []
    forms = []
    model = {"sentence": "", "translation": ""}
    note = ""
    for title, body in sections.items():
        key = title.lower()
        if any(token in title for token in ("搭配", "collocation", "рекция", "управление")):
            collocations = _phrase_pairs(body)
        elif any(token in title for token in ("结尾", "速查", "形态", "变格", "变位", "forms", "endings")):
            forms = _forms_lines(body)
        elif any(token in title for token in ("例句", "example", "model")):
            sentence, translation = "", ""
            cleaned = " ".join(body.split()).strip()
            m = re.search(r"[«「\"](.+?)[»」\"]\s*[.!]?\s*[（(](.+?)[）)]\s*$", cleaned)
            if m:
                sentence, translation = m.group(1).strip(), m.group(2).strip()
            else:
                m = re.search(r"[«「\"](.+?)[»」\"]", cleaned)
                if m:
                    sentence = m.group(1).strip()
                    rest = cleaned[m.end():].strip(" .（()）")
                    translation = rest
                else:
                    sentence, translation = _split_phrase_gloss(cleaned)
            model = {
                "sentence": sentence.strip(" «»「」\"'"),
                "translation": translation.strip(" （）()"),
            }
        elif any(token in title for token in ("注意", "note", "hinweis", "caveat")):
            note = body
        else:
            # Unknown section: keep as overview appendix only if overview empty.
            if not overview:
                overview = f"{title}：{body}"
    return {
        "overview": overview,
        "collocations": collocations,
        "forms": forms,
        "model": model,
        "note": note,
    }


def _listening_type_label(kind: str) -> str:
    labels = {
        "true_false": _("True / False"),
        "multiple_choice": _("Multiple choice"),
        "fill_in_the_blank": _("Fill in the blank"),
    }
    if kind in labels:
        return labels[kind]
    return kind.replace("_", " ").title() if kind else ""



def _format_listening_tasks(value) -> list[dict]:
    """Normalize listening_tasks into display cards (supports structured + legacy)."""
    if not isinstance(value, list):
        return []
    out = []
    for task in value:
        if not isinstance(task, dict):
            continue
        # Legacy: {question, answer}
        if str(task.get("question") or "").strip() and "items" not in task:
            out.append({
                "kind": "legacy",
                "type_label": "",
                "instruction": "",
                "items": [{
                    "prompt": str(task.get("question") or "").strip(),
                    "options": [],
                    "answer": str(task.get("answer") or "").strip(),
                }],
            })
            continue
        kind = str(task.get("type") or "").strip().lower()
        items_out = []
        for item in task.get("items") or []:
            if not isinstance(item, dict):
                continue
            prompt = str(
                item.get("statement")
                or item.get("question")
                or item.get("sentence")
                or item.get("prompt")
                or ""
            ).strip()
            options = item.get("options") if isinstance(item.get("options"), list) else []
            options = [str(o).strip() for o in options if str(o).strip()]
            answer = str(item.get("answer") or "").strip()
            if prompt or answer:
                items_out.append({
                    "prompt": prompt,
                    "options": options,
                    "answer": answer,
                })
        if not items_out and not str(task.get("instruction") or "").strip():
            continue
        out.append({
            "kind": kind or "generic",
            "type_label": _listening_type_label(kind),
            "instruction": str(task.get("instruction") or "").strip(),
            "items": items_out,
        })
    return out


def _format_comprehension_qa(questions, answers) -> list[dict]:
    """Zip open comprehension questions with matching answers for one column."""
    q_list = questions if isinstance(questions, list) else []
    a_list = answers if isinstance(answers, list) else []
    out = []
    n = max(len(q_list), len(a_list))
    for i in range(n):
        q = str(q_list[i]).strip() if i < len(q_list) and q_list[i] is not None else ""
        a = str(a_list[i]).strip() if i < len(a_list) and a_list[i] is not None else ""
        if q or a:
            out.append({"question": q, "answer": a})
    return out


def _str_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        parts = re.split(r"[,;，、]|\n", value)
        return [p.strip(" .;；") for p in parts if p.strip(" .;；")]
    return []


def _format_production_task(value) -> dict:
    """Normalize speaking/writing task to prompt + lists (supports legacy string)."""
    empty = {
        "prompt": "",
        "meta": "",
        "useful_language": [],
        "checklist": [],
        "support_phrases": [],
        "sample_answer": "",
    }
    if isinstance(value, dict):
        return {
            "prompt": str(value.get("prompt") or value.get("task") or "").strip(),
            "meta": str(value.get("duration") or value.get("length") or value.get("meta") or "").strip(),
            "useful_language": _str_list(value.get("useful_language") or value.get("keywords")),
            "checklist": _str_list(value.get("checklist") or value.get("requirements")),
            "support_phrases": _str_list(value.get("support_phrases") or value.get("phrases")),
            "sample_answer": str(
                value.get("sample_answer")
                or value.get("model_answer")
                or value.get("answer")
                or ""
            ).strip(),
        }
    if not isinstance(value, str) or not value.strip():
        return empty
    text = value.strip()
    useful, checklist, support = [], [], []
    prompt = text
    # Legacy Russian blobs often embed lists after fixed cues.
    m = re.search(
        r"(Используйте следующ\w*[^:]*:|например:)\s*(.+?)(?:\.\s*(?:В своём|В эссе|В конце)|$)",
        text,
        flags=re.I | re.S,
    )
    if m:
        useful = _str_list(m.group(2))
        prompt = (text[: m.start()] + text[m.end():]).strip(" .")
    m2 = re.search(
        r"(?:В своём ответе[^.]*:|В эссе\b[^.]*:|В конце\b)\s*(.+)$",
        prompt,
        flags=re.I | re.S,
    )
    if m2:
        tail = m2.group(1).strip()
        prompt = prompt[: m2.start()].strip(" .")
        m3 = re.search(r"вводные конструкции:\s*(.+)$", tail, flags=re.I)
        if m3:
            support = _str_list(m3.group(1))
            tail = tail[: m3.start()].strip(" .;")
        parts = re.split(r"\s*\d+\)\s*", tail)
        checklist = [p.strip(" .;") for p in parts if p.strip(" .;")]
        if not checklist and tail:
            checklist = [tail]
    return {
        "prompt": prompt,
        "meta": "",
        "useful_language": useful,
        "checklist": checklist,
        "support_phrases": support,
        "sample_answer": "",
    }


def _format_review_items(value) -> list[dict]:
    out = []
    if not isinstance(value, list):
        return out
    for item in value:
        if isinstance(item, dict):
            term = str(item.get("term") or item.get("word") or "").strip()
            translation = str(item.get("translation") or item.get("gloss") or "").strip()
            if term or translation:
                out.append({"term": term, "translation": translation})
        elif isinstance(item, str) and item.strip():
            term, translation = _split_phrase_gloss(item.strip())
            out.append({"term": term, "translation": translation})
    return out


def _format_expression_section(reply: dict) -> dict:
    speaking = _format_production_task(reply.get("speaking_task"))
    writing = _format_production_task(reply.get("writing_task"))
    review = _format_review_items(reply.get("review"))
    return {
        "speaking": speaking,
        "writing": writing,
        "review": review,
        "has_content": bool(
            speaking["prompt"] or writing["prompt"] or review
        ),
    }


def _format_grammar_entries(value) -> list[dict]:
    """Normalize grammar JSON into clean textbook cards for the template."""
    if isinstance(value, dict):
        raw_items = [
            dict(item, pattern=key) if isinstance(item, dict) else {"pattern": key, "explanation": item}
            for key, item in value.items()
        ]
    elif isinstance(value, list):
        raw_items = value
    else:
        return []
    entries = []
    for detail in raw_items:
        if not isinstance(detail, dict):
            entries.append({
                "pattern": "",
                "meaning": "",
                "overview": str(detail),
                "collocations": [],
                "forms": [],
                "model": {"sentence": "", "translation": ""},
                "note": "",
                "examples": [],
                "practice_instruction": "",
                "practice_items": [],
                "practice": "",
            })
            continue

        legacy = _parse_legacy_grammar_blob(str(detail.get("explanation") or ""))
        overview = str(detail.get("overview") or "").strip() or legacy.get("overview", "")
        # If overview still contains section markers, strip them via legacy parser.
        if "【" in overview:
            legacy2 = _parse_legacy_grammar_blob(overview)
            overview = legacy2.get("overview", "")
            for key in ("collocations", "forms", "model", "note"):
                if not detail.get(key) and legacy2.get(key):
                    legacy[key] = legacy2[key]

        collocations = _phrase_pairs(detail.get("collocations")) or legacy.get("collocations") or []
        forms = _forms_lines(detail.get("forms")) or legacy.get("forms") or []

        model = detail.get("model") if isinstance(detail.get("model"), dict) else {}
        model_sentence = str(
            model.get("sentence") or model.get("phrase") or detail.get("example") or ""
        ).strip().strip("«»「」\"'")
        model_translation = str(model.get("translation") or "").strip().strip("（）()")
        if not model_sentence and legacy.get("model"):
            model_sentence = str(legacy["model"].get("sentence", "")).strip().strip("«»「」\"'")
            model_translation = str(legacy["model"].get("translation", "")).strip().strip("（）()")
        # Fix common OCR-ish leftovers from mega-blob parsing.
        if model_sentence.endswith("»"):
            model_sentence = model_sentence[:-1].rstrip()
        if model_sentence.endswith("»."):
            model_sentence = model_sentence[:-2].rstrip() + "."

        examples = _phrase_pairs(detail.get("examples"))
        note = str(detail.get("note") or legacy.get("note") or "").strip()

        practice = detail.get("practice")
        practice_instruction = ""
        practice_items: list[dict] = []
        practice_legacy = ""
        if isinstance(practice, dict):
            practice_instruction = str(practice.get("instruction") or "").strip()
            items = practice.get("items")
            if isinstance(items, list):
                for row in items:
                    if isinstance(row, dict):
                        prompt = str(
                            row.get("prompt") or row.get("question") or row.get("item") or ""
                        ).strip()
                        answer = str(row.get("answer") or row.get("key") or "").strip()
                        if prompt or answer:
                            practice_items.append({"prompt": prompt, "answer": answer})
                    elif isinstance(row, str) and row.strip():
                        practice_items.append({"prompt": row.strip(), "answer": ""})
        elif isinstance(practice, str) and practice.strip():
            practice_legacy = practice.strip()

        entries.append({
            "pattern": str(detail.get("pattern") or detail.get("term") or "").strip(),
            "meaning": str(detail.get("meaning") or "").strip(),
            "overview": overview,
            "collocations": collocations,
            "forms": forms,
            "model": {"sentence": model_sentence, "translation": model_translation},
            "note": note,
            "examples": examples,
            "practice_instruction": practice_instruction,
            "practice_items": practice_items,
            "practice": practice_legacy,
        })
    return entries
