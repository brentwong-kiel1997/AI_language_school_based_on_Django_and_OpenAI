"""Utility helpers for the YouTube → learning-material pipeline.

Learning materials are generated through Volcengine Ark's OpenAI-compatible chat completions API. Transcription uses YouTube captions.

Public surface (unchanged from the OpenAI version so Django views need
no edits):

* :class:`Transcribe`      – reads a YouTube video's captions, and exposes the same ``text_with_ts``
                              dict the templates use to render captions.
* :class:`Generator`       – builds the 5-section learning-material
                              prompt and calls the chat completion API
                              in JSON mode.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import yt_dlp as youtube_dl

logger = logging.getLogger(__name__)

DEFAULT_ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_ARK_MODEL = "doubao-seed-2.0-lite"
DEFAULT_ARK_TIMEOUT_SECONDS = 300.0
MIN_ARK_TIMEOUT_SECONDS = 1.0
DEFAULT_ARK_MAX_RETRIES = 2
MAX_ARK_MAX_RETRIES = 10


def _load_dotenv() -> None:
    """Load repository and Django-project .env files without overriding OS env."""
    project_dir = Path(__file__).resolve().parents[1]
    repo_root = project_dir.parent
    for path in (repo_root / ".env", project_dir / ".env"):
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if value and value[0:1] == value[-1:] and value[0] in "\"'":
                value = value[1:-1]
            if key:
                os.environ.setdefault(key, value)


_load_dotenv()


def _env_float(name: str, default: float, minimum: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return default
    if not value >= minimum or value == float("inf"):
        return default
    return value


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    return value if minimum <= value <= maximum else default


TEXT_MODEL = os.environ.get("ARK_MODEL", DEFAULT_ARK_MODEL)


class ArkChatClient:
    """Minimal client for Ark's OpenAI-compatible chat completions API."""

    def __init__(self, api_key: str, base_url: str, timeout: float):
        if not api_key:
            raise ValueError("ARK_API_KEY is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def chat(self, messages: list[dict], model: str, temperature: float = 0) -> str:
        if not model:
            raise ValueError("ARK_MODEL is required")
        body = {"model": model, "messages": messages, "temperature": temperature,
                "response_format": {"type": "json_object"}}
        response = self._post(body)
        if response.status_code == 400 and "response_format" in response.text.lower():
            body.pop("response_format", None)
            response = self._post(body)
        response.raise_for_status()
        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Ark response did not contain choices[0].message.content") from exc
        if not isinstance(content, str):
            raise ValueError("Ark response content was not text")
        return content

    def _post(self, body: dict) -> httpx.Response:
        return httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=dict(body), timeout=self.timeout,
        )


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
    """Download audio from a URL and transcribe it with the YouTube captions."""

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

                # This flow uses YouTube captions for transcription; Ark is used only
                # for the language-learning generation stage.
                captions = info_dict.get("subtitles") or info_dict.get("automatic_captions") or {}
                original = next(((code, tracks) for code, tracks in captions.items()
                                 if code.endswith("-orig")), None)
                selected = original or next(iter(captions.items()), None)
                if not selected:
                    raise RuntimeError(
                        "This video has no YouTube captions. The current flow requires YouTube "
                        "captions; configure a separate speech-to-text service to handle it."
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


class LearningMaterialValidationError(ValueError):
    """Raised when Volcengine Ark cannot produce a valid learning-material JSON."""


_REQUIRED_LESSON_KEYS = (
    "lesson_title", "level", "can_do", "warm_up", "import_words",
    "import_grammars", "listening_tasks", "questions", "answers",
    "translation", "speaking_task", "writing_task", "review",
)
_LEVELS = {"A1", "A2", "B1", "B2", "C1", "C2"}
_DISPLAY_FIELDS = ("meaning", "example", "note", "pattern", "explanation", "practice")


def _has_display_content(value) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return value is not None


def _normalise_collection(value, name: str) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [dict(item, term=key) if isinstance(item, dict) else {"term": key, "meaning": item}
                for key, item in value.items()]
    raise TypeError(f"{name} must be a list or object")


def _validate_lesson_json(raw: str) -> tuple[dict, list[str]]:
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        return {}, [f"response is not valid JSON: {exc}"]
    if not isinstance(data, dict):
        return {}, ["top-level JSON must be an object"]
    errors = [f"missing required key: {key}" for key in _REQUIRED_LESSON_KEYS if key not in data]
    if data.get("level") not in _LEVELS:
        errors.append("level must be one of A1/A2/B1/B2/C1/C2")
    try:
        words = _normalise_collection(data.get("import_words"), "import_words")
        data["import_words"] = words
        if not 8 <= len(words) <= 20:
            errors.append("import_words must contain 8-20 items")
        for index, item in enumerate(words):
            if not isinstance(item, dict) or not any(_has_display_content(item.get(k)) for k in ("meaning", "example", "note")):
                errors.append(f"import_words[{index}] has no meaning or displayable content")
    except (TypeError, AttributeError) as exc:
        errors.append(str(exc))
    try:
        grammars = _normalise_collection(data.get("import_grammars"), "import_grammars")
        data["import_grammars"] = grammars
        if len(grammars) < 2:
            errors.append("import_grammars must contain at least 2 items")
        for index, item in enumerate(grammars):
            if not isinstance(item, dict) or not any(_has_display_content(item.get(k)) for k in ("pattern", "example", "explanation", "practice")):
                errors.append(f"import_grammars[{index}] has no displayable content")
    except (TypeError, AttributeError) as exc:
        errors.append(str(exc))
    for key in ("questions", "answers", "listening_tasks", "review"):
        if not isinstance(data.get(key), list) or not data.get(key):
            errors.append(f"{key} must be a non-empty list")
    if not isinstance(data.get("translation"), dict) or not data.get("translation"):
        errors.append("translation must be a non-empty object")
    for key in ("speaking_task", "writing_task"):
        if not _has_display_content(data.get(key)):
            errors.append(f"{key} must be non-empty")
    return data, errors


class Generator:
    """Build and validate learning material using a local orchestration agent."""

    def __init__(self, target_language: str, native_language: str, text):
        self.target_language = target_language
        self.native_language = native_language
        self.text = str(text)
        self.prompt = self._lesson_prompt(self.text)

    def _lesson_prompt(self, source: str) -> str:
        return f"""You are an experienced CEFR-aligned language teacher. Return one valid JSON object only.
Learner native language: {self.native_language}; target language: {self.target_language}.
Required keys: {', '.join(_REQUIRED_LESSON_KEYS)}.
level must be exactly A1/A2/B1/B2/C1/C2. Include about 12 useful import_words (8-20), at least 2 import_grammars, and non-empty listening_tasks, questions, answers, translation, speaking_task, writing_task, and review. Each word needs meaning or useful display content; each grammar needs pattern/example/explanation/practice content. Make a practical CEFR-aligned lesson grounded only in this source:
{source}"""

    @staticmethod
    def _response_text(response) -> str:
        return response if isinstance(response, str) else str(response)

    def _request(self, client, prompt: str, model: str) -> str:
        max_retries = _env_int("ARK_MAX_RETRIES", DEFAULT_ARK_MAX_RETRIES, 0, MAX_ARK_MAX_RETRIES)
        for attempt in range(max_retries + 1):
            try:
                response = client.chat(messages=[{"role": "user", "content": prompt}], model=model, temperature=0)
                return self._response_text(response)
            except httpx.RequestError:
                if attempt >= max_retries:
                    raise
                delay = 2 ** attempt
                logger.warning("Ark network request failed; retrying in %s seconds (attempt %s/%s)", delay, attempt + 2, max_retries + 1)
                time.sleep(delay)
        raise RuntimeError("unreachable")

    def _summarise_long_transcript(self, client, model: str) -> str:
        chunk_size = max(2000, _env_int("ARK_AGENT_CHUNK_CHARS", 6000, 2000, 1_000_000))
        summaries = []
        for index in range(0, len(self.text), chunk_size):
            chunk = self.text[index:index + chunk_size]
            prompt = "Return JSON only with keys keywords, grammar_points, question_clues, translation_clues, level_evidence. Summarise this transcript chunk without inventing facts:\n" + chunk
            raw = self._request(client, prompt, model)
            try:
                parsed = json.loads(raw)
                summaries.append(parsed if isinstance(parsed, dict) else {"summary": parsed})
            except (TypeError, json.JSONDecodeError):
                summaries.append({"summary": raw})
        return json.dumps(summaries, ensure_ascii=False)

    def chatbox(self, model: str = TEXT_MODEL) -> None:
        client = _get_client()
        threshold = max(4000, _env_int("ARK_AGENT_PROMPT_CHARS", 18000, 4000, 10_000_000))
        final_prompt = self.prompt
        if len(final_prompt) > threshold:
            summaries = self._summarise_long_transcript(client, model)
            final_prompt = self._lesson_prompt("Structured transcript summaries:\n" + summaries)

        raw = self._request(client, final_prompt, model)
        history = [{"role": "user", "content": final_prompt}, {"role": "assistant", "content": raw}]
        validation_retries = _env_int("ARK_VALIDATION_RETRIES", 1, 0, 3)
        for attempt in range(validation_retries + 1):
            data, errors = _validate_lesson_json(raw)
            if not errors:
                self.reply = json.dumps(data, ensure_ascii=False)
                self.message_history = history
                return
            if attempt >= validation_retries:
                raise LearningMaterialValidationError("Ark returned invalid learning material JSON after validation: " + "; ".join(errors))
            repair_prompt = f"""The previous response failed validation.
Errors: {json.dumps(errors, ensure_ascii=False)}
Original response: {raw}
Return only the corrected complete JSON object. Do not add commentary."""
            raw = self._request(client, repair_prompt, model)
            history.extend(({"role": "user", "content": repair_prompt}, {"role": "assistant", "content": raw}))


# ---------------------------------------------------------------------------
# Client helper
# ---------------------------------------------------------------------------


_CLIENT: ArkChatClient | None = None


def _get_client() -> ArkChatClient:
    """Return a lazily constructed process-wide Ark client."""
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = ArkChatClient(
            api_key=os.environ.get("ARK_API_KEY", ""),
            base_url=os.environ.get("ARK_BASE_URL", DEFAULT_ARK_BASE_URL),
            timeout=_env_float("ARK_TIMEOUT_SECONDS", DEFAULT_ARK_TIMEOUT_SECONDS,
                               minimum=MIN_ARK_TIMEOUT_SECONDS),
        )
    return _CLIENT


def reset_client() -> None:
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
import threading
import traceback
from concurrent.futures import Future
from typing import Callable

from django.db import close_old_connections

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

