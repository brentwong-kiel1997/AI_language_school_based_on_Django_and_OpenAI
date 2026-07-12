"""Utility helpers for the YouTube → learning-material pipeline.

This module used to wrap the OpenAI Python SDK (``openai.OpenAI``) for
both audio transcription (Whisper) and the chat-completion call that
generates the learning materials. The OpenAI dependency has been
**completely removed** in favour of the in-house ``minimax_cli`` package
(MiniMax multimodal platform), which exposes the same shapes.

Public surface (unchanged from the OpenAI version so Django views need
no edits):

* :class:`Transcribe`      – downloads a YouTube video's audio, runs
                              ASR, and exposes the same ``text_with_ts``
                              dict the templates use to render captions.
* :class:`Generator`       – builds the 5-section learning-material
                              prompt and calls the chat completion API
                              in JSON mode.
"""

from __future__ import annotations

import json
import os
import shutil

import httpx
from datetime import datetime, timedelta
from pathlib import Path

import yt_dlp as youtube_dl
# ``yt_dlp`` is imported as ``youtube_dl`` to keep the historical name
# that the rest of the code (and the old git history) used.

# New unified client (replaces ``openai.OpenAI``). Falls back to the
# ``MINIMAX_API_KEY`` env var, then to the key persisted in
# ``~/.mmx/config.json`` by ``mmx auth login``.
from minimax_cli import (
    ChatMessage,
    Config,
    MiniMaxClient,
    Region,
)

# Whisper replacement. The platform doesn't publish a dedicated ASR model in
# the /v1/models list (only chat models are exposed there), so we point
# ``ASR_MODEL`` at the strongest chat model. The audio endpoint ignores
# this value – it always routes through the platform's built-in ASR – but
# we keep the kwarg to stay close to the OpenAI-shaped API. Override with
# the MINIMAX_ASR_MODEL env var.
ASR_MODEL = os.environ.get("MINIMAX_ASR_MODEL", "MiniMax-M3")

# Default chat model. The original code pinned ``gpt-3.5-turbo``; the
# current newest model exposed at GET /v1/models is ``MiniMax-M3``.
TEXT_MODEL = os.environ.get("MINIMAX_TEXT_MODEL", "MiniMax-M3")


# ---------------------------------------------------------------------------
# yt-dlp JS runtime resolution
# ---------------------------------------------------------------------------
#
# yt-dlp >= 2026.x requires a JavaScript runtime to solve YouTube's
# ``n``/``sig`` player challenges. Without one the audio download
# silently fails with ``HTTP 500`` once the postprocessor tries to write
# the chunks out. Deno is the runtime yt-dlp documents as the new default;
# we resolve it the same way yt-dlp does internally (``shutil.which``).
#
# Operators can override the search order with the ``YTDLP_JS_RUNTIMES``
# env var (colon-separated), e.g.
#
#     YTDLP_JS_RUNTIMES="node:/usr/local/bin/node:deno"
#
# If none of the resolved runtimes is present, :class:`Transcribe`
# raises a clear ``RuntimeError`` instead of a cryptic download error.

_YTDLP_RUNTIME_CANDIDATES = (
    "deno",
    "node",
    "nodejs",
    "quickjs",
    "qjs",
    "bun",
)


def _detect_yt_dlp_runtimes() -> list[str]:
    """Return the list of JS runtime executables available on PATH.

    Honours the ``YTDLP_JS_RUNTIMES`` override (which accepts
    ``RUNTIME[:PATH]`` entries, just like the ``--js-runtimes`` CLI flag).
    """
    override = os.environ.get("YTDLP_JS_RUNTIMES")
    if override:
        resolved: list[str] = []
        for token in override.split(":"):
            if not token:
                continue
            # ``RUNTIME[:PATH]`` form: prefer the explicit PATH if given.
            if os.path.sep in token or token.startswith("."):
                if os.path.isfile(token) and os.access(token, os.X_OK):
                    resolved.append(token)
                continue
            path = shutil.which(token)
            if path:
                resolved.append(path)
        if resolved:
            return resolved
    return [
        path
        for name in _YTDLP_RUNTIME_CANDIDATES
        if (path := shutil.which(name))
    ]


def _yt_dlp_runtime_help() -> str:
    """Return a human-readable install hint when no JS runtime is found."""
    return (
        "yt-dlp needs a JavaScript runtime to download YouTube audio "
        "(YouTube's player challenge solver). Install one of: "
        + ", ".join(_YTDLP_RUNTIME_CANDIDATES)
        + ". Easiest on macOS: `brew install deno`. Then re-run."
    )


# ---------------------------------------------------------------------------
# Audio transcription
# ---------------------------------------------------------------------------


class Transcribe:
    """Download audio from a URL and transcribe it with the MiniMax ASR API."""

    def __init__(self, url: str):
        self.url = url

    def audio2text(
        self,
        output_path: str | Path = "./download",
        max_duration: int = 600,
    ) -> None:
        """Download, transcribe, and populate all instance attributes.

        After this call, the following attributes are available:

        * ``id``            – the YouTube video id
        * ``title``         – video title
        * ``duration``      – video length in seconds
        * ``language``      – detected ISO language code
        * ``upload_date``   – publication date in ``YYYY-MM-DD`` format
        * ``transcript``    – raw API response (segments + text)
        * ``text_with_ts``  – ``{ "HH:MM:SS": "sentence", ... }`` dict
        * ``audio_file_path`` – the temp mp3 path (deleted on success)
        """
        output_path = Path(output_path)
        output_path.mkdir(parents=True, exist_ok=True)
        self.audio_file_path = None

        # yt-dlp 2026+ requires a JavaScript runtime to solve YouTube's
        # ``n``/``sig`` player challenges. We resolve it once here so the
        # user gets a clear install hint instead of a cryptic download
        # failure if nothing is installed.
        runtimes = _detect_yt_dlp_runtimes()
        if not runtimes:
            raise RuntimeError(_yt_dlp_runtime_help())

        ydl_opts: dict = {
            "format": "bestaudio/best",
            # Hand yt-dlp each detected runtime in priority order. We pass
            # explicit absolute paths because yt-dlp's own discovery is
            # verbose-only and silent when nothing matches.
            "js_runtimes": {Path(rt).name: {"path": rt} for rt in runtimes},
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "outtmpl": str(output_path / "%(id)s.%(ext)s"),
            # Friendlier errors than ``HTTP Error 500``.
            "retries": 3,
            "fragment_retries": 3,
            "ignoreerrors": False,
        }

        try:
            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                # Inspect metadata first so over-limit videos are rejected before download.
                info_dict = ydl.extract_info(self.url, download=False)
                self.duration = info_dict["duration"]
                if self.duration > max_duration:
                    raise ValueError("Video duration exceeds 10 minutes.")
                self.title = info_dict["title"]
                self.id = info_dict["id"]

                # MiniMax currently has no public speech-to-text endpoint. Prefer
                # YouTube's original-language caption track, then use MiniMax-M3
                # for the language-learning generation stage.
                captions = info_dict.get("subtitles") or info_dict.get("automatic_captions") or {}
                original = next(((code, tracks) for code, tracks in captions.items()
                                 if code.endswith("-orig")), None)
                selected = original or next(iter(captions.items()), None)
                if not selected:
                    raise RuntimeError(
                        "This video has no YouTube captions. MiniMax does not currently "
                        "offer a public speech-to-text API, so it cannot be transcribed."
                    )
                language_code, tracks = selected
                track = next((item for item in tracks if item.get("ext") == "json3"), tracks[0])
                payload = httpx.get(track["url"], timeout=60, follow_redirects=True).json()
                text_with_ts = {}
                segments = []
                for event in payload.get("events", []):
                    text = "".join(seg.get("utf8", "") for seg in event.get("segs", [])).strip()
                    if not text or text == "\n":
                        continue
                    start_seconds = event.get("tStartMs", 0) / 1000
                    end_seconds = start_seconds + event.get("dDurationMs", 0) / 1000
                    stamp = str(timedelta(seconds=int(start_seconds))).split(".")[0]
                    text_with_ts[stamp] = text
                    segments.append({"start": start_seconds, "end": end_seconds, "text": text})
                if not text_with_ts:
                    raise RuntimeError("The selected YouTube caption track was empty.")
                self.text_with_ts = text_with_ts
                self.language = language_code.removesuffix("-orig")
                self.transcript = {
                    "language": self.language,
                    "duration": self.duration,
                    "text": " ".join(text_with_ts.values()),
                    "segments": segments,
                    "source": "youtube_captions",
                }
        except youtube_dl.utils.DownloadError as exc:
            msg = str(exc)
            lowered = msg.lower()
            if "javascript runtime" in lowered or "no supported javascript" in lowered:
                raise RuntimeError(_yt_dlp_runtime_help()) from exc
            if "sign in" in lowered or "confirm" in lowered:
                raise RuntimeError("YouTube is asking for sign-in / bot confirmation.") from exc
            if "video unavailable" in lowered or "private video" in lowered:
                raise ValueError("This YouTube video is unavailable.") from exc
            raise

        # ``upload_date`` is YYYYMMDD in yt-dlp's info_dict. Some uploads
        # (e.g. live streams) don't carry a date, so fall back to ``None``
        # instead of crashing the whole pipeline.
        raw_upload_date = info_dict.get("upload_date")
        if raw_upload_date:
            try:
                upload_date = datetime.strptime(raw_upload_date, "%Y%m%d").date()
                self.upload_date = upload_date.strftime("%Y-%m-%d")
            except ValueError:
                self.upload_date = None
        else:
            self.upload_date = None


# ---------------------------------------------------------------------------
# Learning material generation
# ---------------------------------------------------------------------------


# A small example dictionary used to illustrate the expected JSON shape.
# Kept verbatim from the original openai version so the prompt template
# stays byte-for-byte comparable.
dic = {
    "import_words": {
        "Mann": "man", "Tempel": "temple", "Gott": "God", "Leben": "life",
        "Krieg": "war", "Albträumen": "nightmares", "traumatisiert": "traumatized",
        "russischen": "Russian", "Okaine": "Ukraine", "kümmert sich um": "take care of",
        "Tod": "death", "Verletzten": "injured", "Wunde": "wound",
        "Behandlung": "treatment", "Ananfalls": "attacks", "erschießen": "shoot",
        "fliehen": "flee", "belasten": "burden", "Arbeitslos": "unemployed",
        "Tagelöner": "day laborer",
    },
    "import_grammars": {
        "Modal verbs (werden)": {
            "Example": "Wenn eine Behandlung möglich ist, werden sie gerettet.",
            "Explanation": (
                "The modal verb 'werden' is used to express future tense, "
                "indicating that they will be saved if treatment is possible."
            ),
        },
        "Prepositions (um)": {
            "Example": (
                "Er zahlte umgerechnet rund 3000 Euro an allen russischen Vermittler."
            ),
            "Explanation": (
                "The preposition 'um' is used to indicate the amount paid "
                "(around 3000 euros) to all Russian intermediaries."
            ),
        },
        "Comparative forms (düster)": {
            "Example": "Die wirtschaftliche Lage Nepals ist düster.",
            "Explanation": (
                "The comparative form 'düster' (dark) is used to describe "
                "the economic situation of Nepal."
            ),
        },
    },
    "questions": [
        "Was hat der Mann im Tempel gemacht?",
        "Warum ist die wirtschaftliche Lage Nepals düster?",
        "Was hat die Familie des Soldaten belastet?",
    ],
    "answers": [
        "Der Mann ist in den Tempel gegangen, um Gott für das gerettete Leben im Krieg zu danken.",
        "Die wirtschaftliche Lage Nepals ist düster aufgrund hoher Arbeitslosigkeit und hoher Inflation.",
        "Die Familie des Soldaten wurde von Schulden belastet, die er einem Vermittler gezahlt hatte, um ihn nach Russland zu bringen.",
    ],
    "translation": {
        "0:00:03": "A man is in this temple to thank God for saving his life in a war, far away.",
        "0:00:10": "He suffers from nightmares deeply traumatized by what he experienced in the Russian Amel in Okaine.",
    },
}


class Generator:
    """Build the 5-section learning-material prompt and call MiniMax chat."""

    def __init__(self, target_language: str, native_language: str, text):
        self.target_language = target_language
        self.native_language = native_language
        self.text = str(text)
        self.target_language_level = "b1"

        self.prompt = f"""
You are an experienced CEFR-aligned language teacher and lesson designer.
Create a practical, learner-centred lesson from the transcript below.
The learner's native language is {self.native_language}; target language is
{self.target_language}; level is {self.target_language_level} (B1).
Use the action-oriented cycle: prepare -> understand -> study -> practise -> reflect.
Focus on useful language in context, not isolated difficult words. Do not invent
facts that are not supported by the transcript. Return one valid JSON object only.

Required JSON keys:
- lesson_title: a short title in the learner's native language
- level: "B1"
- can_do: 2-3 measurable "I can..." learning objectives
- warm_up: 2 questions to activate prior knowledge before watching
- import_words: exactly 12 useful words or phrases, each value an object with
  meaning (in {self.native_language}), example (in {self.target_language}), and note
- import_grammars: exactly 3 grammar patterns found in the transcript; each has
  pattern, example, explanation (in {self.native_language}), and practice
- listening_tasks: exactly 3 tasks: gist, detail, and inference; each has question,
  options (if suitable), and answer
- questions: exactly 3 comprehension questions in {self.target_language}
- answers: answers to those questions in {self.target_language}
- translation: timestamp-to-translation mapping in {self.native_language}
- speaking_task: one realistic role-play or discussion task with useful phrases
- writing_task: one short output task with a word limit and success criteria
- review: 5 short retrieval questions for later review, with answers

Keep the language appropriate for B1, make every activity actionable, and ensure
all JSON strings are properly escaped. Transcript:
{self.text}
"""

    def chatbox(self, model: str = TEXT_MODEL) -> None:
        """Run the prompt and store the JSON reply on ``self.reply``."""
        client = _get_client()
        response = client.text_chat(
            messages=[
                ChatMessage.user(self.prompt + self.text),
            ],
            model=model,
            temperature=0,
            json_mode=True,
        )
        self.reply = response.to_json()
        # Keep the same attribute name the views already access.
        self.message_history = [
            {"role": "user", "content": self.prompt + self.text},
            {"role": "assistant", "content": self.reply},
        ]


# ---------------------------------------------------------------------------
# Client helper
# ---------------------------------------------------------------------------


_CLIENT: MiniMaxClient | None = None


def _get_client() -> MiniMaxClient:
    """Return a process-wide :class:`MiniMaxClient`.

    The client is built lazily on first use so that import-time failures
    (e.g. during ``manage.py migrate``) don't crash the project.

    Resolution order:

    1. ``MINIMAX_API_KEY`` env var
    2. ``~/.mmx/config.json`` written by ``mmx auth login``
    """
    global _CLIENT
    if _CLIENT is None:
        cfg = Config.load()
        region = (
            os.environ.get("MINIMAX_REGION")
            or cfg.region
            or Region.CN.value
        )
        _CLIENT = MiniMaxClient(
            api_key=os.environ.get("MINIMAX_API_KEY") or cfg.api_key,
            region=region,
        )
    return _CLIENT


def reset_client() -> None:
    """Forget the cached client. Useful for tests."""
    global _CLIENT
    _CLIENT = None


# ---------------------------------------------------------------------------
# Background job runner
# ---------------------------------------------------------------------------
#
# ``wait_view`` used to call ``Transcribe.audio2text()`` synchronously in
# the HTTP request thread, which meant the browser sat on a blank loading
# screen for the full YouTube-download + ASR + LLM round trip (often
# 30 s–2 min). The user kept reporting "it always gets stuck", but the
# app was just blocking – exactly as designed (or, more accurately, as
# not-designed).
#
# To fix that without pulling in a broker like Redis/RabbitMQ + Celery we
# fire the work on a small daemon thread and reflect the outcome on the
# row itself via the ``status``/``error_message`` columns added in the
# models. The wait page polls until ``status == ready`` (or ``failed``)
# and then redirects.
#
# Caveats:
#   * Threads don't share the request thread's DB connection; they
#     close it explicitly on exit so we don't leak SQLite handles.
#   * We are single-server / single-process only. For multi-worker
#     production you'd want Celery proper.
#   * Two concurrent submits for the same ``video_id`` are coalesced by
#     the natural unique constraint on ``video_id`` plus the read of the
#     row status before launch (see ``wait_view``).
import logging
import threading
import traceback
from concurrent.futures import Future
from typing import Callable

from django.db import close_old_connections

logger = logging.getLogger(__name__)


def run_in_background(
    func: Callable[..., None],
    *args,
    thread_name: str = "bals-bg",
    **kwargs,
) -> Future:
    """Run ``func`` on a daemon thread, returning a :class:`Future`.

    The future resolves with the return value of ``func`` (typically
    ``None``) or the exception it raised. We close the calling thread's
    DB connections first inside the worker so Django can hand out a
    fresh connection.

    Usage::

        run_in_background(_do_transcription, video_id, job_id=42)

    The function ``_do_transcription`` should be self-contained: it
    will be called without any request context, so it must look up the
    row by id, update status, etc.
    """

    def _runner() -> None:
        close_old_connections()
        try:
            func(*args, **kwargs)
        except Exception:
            # We've already (hopefully) written ``error_message`` on the
            # row; if not, this log line gives operators a stack trace
            # to work with.
            logger.exception(
                "background job %s crashed", getattr(func, "__name__", repr(func))
            )
        finally:
            # ``audio2text`` is a one-shot; the row's status reflects the
            # outcome. Tear the connection down so it doesn't outlive
            # the thread.
            close_old_connections()

    fut: Future = Future()
    thread = threading.Thread(
        target=_wrapped_runner, args=(fut, _runner), name=thread_name, daemon=True
    )
    thread.start()
    return fut


def _wrapped_runner(fut: Future, runner: Callable[[], None]) -> None:
    try:
        runner()
        fut.set_result(None)
    except Exception as exc:  # pragma: no cover - defensive
        fut.set_exception(exc)

