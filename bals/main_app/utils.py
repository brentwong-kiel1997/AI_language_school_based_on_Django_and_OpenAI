"""Utility helpers for the YouTube → learning-material pipeline.

Lesson generation uses standalone ``minimax_cli`` (text chat).
Module prompts live in standalone ``prompts`` (per-language packs).
Captions / yt-dlp stay here.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

import httpx
import yt_dlp as youtube_dl
from minimax_cli import APIError, Config as MiniMaxConfig, MiniMaxClient, NetworkError
from prompts import canonical_target_language, get_language_pack

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 2
MAX_MAX_RETRIES = 10
DEFAULT_MAX_TOKENS = 131072
MIN_MAX_TOKENS = 256
MAX_MAX_TOKENS = 131072
DEFAULT_TEXT_MODEL = "MiniMax-M3"


def _load_dotenv(paths: Optional[Iterable[Path]] = None) -> None:
    """Load .env files with setdefault (never override existing OS env)."""
    if paths is None:
        cwd = Path.cwd()
        paths = (
            cwd / ".env",
            cwd.parent / ".env",
            Path(__file__).resolve().parents[2] / ".env",
            Path(__file__).resolve().parents[1] / ".env",
        )
    seen: set[Path] = set()
    for path in paths:
        path = path.resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
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


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    return value if minimum <= value <= maximum else default


_load_dotenv(
    (
        Path(__file__).resolve().parents[2] / ".env",
        Path(__file__).resolve().parents[1] / ".env",
    )
)

TEXT_MODEL = os.environ.get("MINIMAX_TEXT_MODEL", DEFAULT_TEXT_MODEL)

_CLIENT: Optional["LessonChatClient"] = None


class LessonChatClient:
    """Adapter: ``chat(...) -> str`` over MiniMax ``text_chat`` (JSON mode)."""

    def __init__(self, client: MiniMaxClient):
        self._client = client

    def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> str:
        return self._client.text_chat(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
        ).text

    def close(self) -> None:
        self._client.close()


def get_client() -> LessonChatClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = LessonChatClient(MiniMaxClient(MiniMaxConfig.load()))
    return _CLIENT


def reset_client() -> None:
    global _CLIENT
    if _CLIENT is not None:
        _CLIENT.close()
    _CLIENT = None


_get_client = get_client


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


def _text_with_timestamps(segments: list[dict]) -> dict[str, str]:
    """Combine segment text sharing the same whole-second timestamp."""
    output: dict[str, str] = {}
    for segment in segments:
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        stamp = str(timedelta(seconds=int(segment.get("start", 0)))).split(".")[0]
        output[stamp] = f"{output[stamp]} {text}".strip() if stamp in output else text
    return output


def _caption_selection(info: dict) -> tuple[str, list[dict]] | None:
    """Select manual captions first, then automatic captions."""
    for collection_name in ("subtitles", "automatic_captions"):
        captions = info.get(collection_name) or {}
        original = next(((code, tracks) for code, tracks in captions.items()
                         if code.endswith("-orig") and tracks), None)
        selected = original or next(((code, tracks) for code, tracks in captions.items() if tracks), None)
        if selected:
            return selected
    return None


# Broadcast / professional caption dumps often embed HH:MM:SS:FF (or .mmm)
# cue markers inside the utf8 text. Strip/split those — do not send to an LLM.
_EMBEDDED_TIMECODE_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}[:.]\d{2,3})\s+(?P<end>\d{2}:\d{2}:\d{2}[:.]\d{2,3})"
)
_ORPHAN_TIMECODE_RE = re.compile(r"\b\d{2}:\d{2}:\d{2}[:.]\d{2,3}\b")


def _timecode_to_seconds(value: str) -> float:
    """Parse HH:MM:SS:FF (frames ~25fps) or HH:MM:SS.mmm into seconds."""
    parts = re.split(r"[:.]", value.strip())
    if len(parts) < 3:
        return 0.0
    hours, minutes, seconds = (int(parts[0]), int(parts[1]), int(parts[2]))
    frac = parts[3] if len(parts) > 3 else "0"
    if len(frac) <= 2:
        return hours * 3600 + minutes * 60 + seconds + int(frac or 0) / 25.0
    return hours * 3600 + minutes * 60 + seconds + int(frac) / (10 ** len(frac))


def _clean_caption_text(text: str) -> str:
    cleaned = _ORPHAN_TIMECODE_RE.sub(" ", text.lstrip("\ufeff"))
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned).strip()
    return cleaned


def _segments_from_embedded_timecodes(text: str) -> list[dict] | None:
    """If caption text is a dump of start/end timecodes + body, split into cues."""
    raw = text.lstrip("\ufeff").strip()
    matches = list(_EMBEDDED_TIMECODE_RE.finditer(raw))
    if len(matches) < 1:
        return None
    # Require the first cue near the start (allow BOM/whitespace only before it).
    if matches[0].start() > 2:
        return None
    segments = []
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        body = _clean_caption_text(raw[body_start:body_end])
        if not body:
            continue
        start = _timecode_to_seconds(match.group("start"))
        end = _timecode_to_seconds(match.group("end"))
        if end <= start:
            end = start + 0.01
        segments.append({"start": start, "end": end, "text": body.replace("\n", " ").strip()})
    return segments or None


def _parse_caption_payload(payload: dict) -> list[dict]:
    segments = []
    for event in payload.get("events", []):
        text = "".join(part.get("utf8", "") for part in event.get("segs", [])).strip()
        if not text or text == "\n":
            continue
        embedded = _segments_from_embedded_timecodes(text)
        if embedded:
            segments.extend(embedded)
            continue
        cleaned = _clean_caption_text(text)
        if not cleaned:
            continue
        start = event.get("tStartMs", 0) / 1000
        segments.append({
            "start": start,
            "end": start + event.get("dDurationMs", 0) / 1000,
            "text": cleaned.replace("\n", " ").strip(),
        })
    return segments


class Transcribe:
    """Use YouTube captions to build a timestamped transcript."""

    def __init__(self, url: str):
        self.url = url

    @staticmethod
    def _cookie_file_path() -> Optional[Path]:
        """Return the configured cookie file path if it exists, else None.

        Relative paths are resolved against the current working directory first,
        then against ``settings.BASE_DIR``, so the same ``.env`` value works no
        matter which directory the server process was launched from.
        """
        cookie_file = os.environ.get("YOUTUBE_COOKIE_FILE", "").strip()
        if not cookie_file:
            return None
        p = Path(cookie_file).expanduser()
        if p.is_file():
            return p
        if not p.is_absolute():
            try:
                from django.conf import settings
                base_candidate = Path(settings.BASE_DIR) / p
                if base_candidate.is_file():
                    return base_candidate
            except Exception:  # noqa: BLE001 - settings may be unavailable in some contexts
                pass
        return None

    @staticmethod
    def _yt_dlp_base_opts(*, with_cookies: bool = False) -> dict:
        """Build yt-dlp options with anti-bot countermeasures.

        Cookie resolution order (only when ``with_cookies`` is True):
        1. ``YOUTUBE_COOKIE_FILE`` — a Netscape-format cookie file. This is the
           **only** method that works on a headless server and never prompts for
           a password (no browser / no OS keychain involved). Preferred for deploys.
        2. ``YOUTUBE_COOKIES_FROM_BROWSER`` — read a live browser profile. Only
           used as a local-dev fallback when no cookie file is configured; on a
           server this typically fails or prompts for a keychain password, so we
           deliberately skip it whenever a cookie file is present.
        """
        opts = {"skip_download": True, "quiet": True, "no_warnings": True,
                # We only need caption tracks, never video formats. Without this
                # yt-dlp aborts with "No video formats found" on some bot-walled
                # videos even when subtitles are present.
                "ignore_no_formats_error": True}

        # NOTE: a custom ``player_client`` list suppresses caption tracks on many
        # videos, so we only apply it on the *cookie-less* bare attempt (where it
        # helps dodge bot detection). When cookies are in play they already clear
        # the bot wall, and the default client returns the full subtitle set.
        if not with_cookies:
            opts["extractor_args"] = {
                "youtube": {"player_client": ["web", "web_safari", "mweb"]},
            }

        if with_cookies:
            cookie_path = Transcribe._cookie_file_path()
            if cookie_path is not None:
                opts["cookiefile"] = str(cookie_path)
                logger.info("Using YouTube cookie file: %s", cookie_path)
            else:
                cookie_browser = os.environ.get("YOUTUBE_COOKIES_FROM_BROWSER", "").strip().lower()
                if cookie_browser:
                    opts["cookiesfrombrowser"] = (cookie_browser,)
                    logger.info(
                        "No cookie file found; falling back to live browser cookies: %s "
                        "(this may prompt for a password and does not work on headless servers)",
                        cookie_browser,
                    )

        return opts

    def _extract_info(self, opts: dict) -> dict:
        """Run yt-dlp extract_info with the given options."""
        with youtube_dl.YoutubeDL(opts) as ydl:
            return ydl.extract_info(self.url, download=False)

    def _process_captions(self, info_dict: dict, max_duration: int) -> None:
        """Extract caption data from info_dict into self.* attributes."""
        self.duration = info_dict["duration"]
        self.title, self.id = info_dict["title"], info_dict["id"]
        if self.duration > max_duration:
            raise ValueError("Video duration exceeds 10 minutes.")
        selection = _caption_selection(info_dict)
        segments = []
        if selection:
            language_code, tracks = selection
            track = next((item for item in tracks if item.get("ext") == "json3"), tracks[0])
            try:
                response = httpx.get(track["url"], timeout=60, follow_redirects=True)
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(f"Unable to fetch or parse the YouTube caption track: {exc}") from exc
            segments = _parse_caption_payload(payload)
        if segments:
            self.language = language_code.removesuffix("-orig")
            self.text_with_ts = _text_with_timestamps(segments)
            self.transcript = {"language": self.language, "duration": self.duration,
                              "text": " ".join(item["text"] for item in segments),
                              "segments": segments, "source": "youtube_captions"}
        else:
            raise RuntimeError(
                "This video has no captions available. "
                "Please choose a video with subtitles (manual or auto-generated)."
            )

    def _is_bot_block(self, exc: youtube_dl.utils.DownloadError) -> bool:
        lowered = str(exc).lower()
        # Genuine login/consent wall. Exclude the "confirm you are on the latest
        # version" footer that yt-dlp appends to unrelated network/SSL errors.
        return (
            ("sign in" in lowered and "confirm your" not in lowered)
            or "bot" in lowered
            or "login" in lowered
            or "consent" in lowered
        )

    def _raise_non_bot_errors(self, exc: youtube_dl.utils.DownloadError) -> None:
        """Re-raise terminal errors; return silently for a genuine bot block."""
        lowered = str(exc).lower()
        if "javascript runtime" in lowered or "no supported javascript" in lowered:
            raise RuntimeError(_yt_dlp_runtime_help()) from exc
        if "video unavailable" in lowered or "private video" in lowered:
            raise ValueError("This YouTube video is unavailable.") from exc
        if not self._is_bot_block(exc):
            # Network / SSL / geo errors — cookies cannot fix these, so surface now.
            raise RuntimeError(
                "Could not reach YouTube (network/SSL error). "
                "Check the server's internet access / proxy and retry."
            ) from exc

    def _stamp_upload_date(self, info_dict: dict) -> None:
        raw_date = (info_dict or {}).get("upload_date")
        try:
            self.upload_date = (
                datetime.strptime(raw_date, "%Y%m%d").date().isoformat()
                if raw_date else None
            )
        except (ValueError, TypeError):
            self.upload_date = None

    def audio2text(self, output_path: str | Path = "./download", max_duration: int = 600) -> None:
        output_path = Path(output_path); output_path.mkdir(parents=True, exist_ok=True)
        self.audio_file_path = None

        cookie_file = self._cookie_file_path() is not None
        browser = os.environ.get("YOUTUBE_COOKIES_FROM_BROWSER", "").strip()

        # Attempt 1: cookie file if configured (server-friendly, instant, no prompt),
        # otherwise a bare request. A cookie-file read never hangs, so no timeout.
        try:
            info_dict = self._extract_info(self._yt_dlp_base_opts(with_cookies=cookie_file))
            self._process_captions(info_dict, max_duration)
            self._stamp_upload_date(info_dict)
            return
        except youtube_dl.utils.DownloadError as exc:
            self._raise_non_bot_errors(exc)  # re-raises unless it's a bot block
            logger.warning("YouTube bot detection hit on first attempt")

        # If we already sent a cookie file and were still blocked, the cookies are
        # expired — a live browser won't help on a server, so fail fast & clearly.
        if cookie_file:
            raise RuntimeError(
                "YouTube rejected the cookie file (still asks to sign in) — the "
                "cookies are probably expired. Re-export from a logged-in browser:\n"
                "  python manage.py youtube_cookies export --from-browser chrome cookies.txt\n"
                "  python manage.py youtube_cookies install cookies.txt"
            )

        # Attempt 2: live browser cookies (local dev only; may prompt / hang).
        if not browser:
            raise RuntimeError(
                "YouTube is blocking automated access and no cookie file is set.\n"
                "On a server: export cookies once and set YOUTUBE_COOKIE_FILE "
                "(see `python manage.py youtube_cookies --help`).\n"
                "Locally: set YOUTUBE_COOKIES_FROM_BROWSER=chrome (close the browser first)."
            )

        import concurrent.futures
        cookie_timeout = _env_int("YOUTUBE_COOKIE_TIMEOUT", 30, 5, 120)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    self._extract_info, self._yt_dlp_base_opts(with_cookies=True)
                )
                info_dict = future.result(timeout=cookie_timeout)
            self._process_captions(info_dict, max_duration)
            self._stamp_upload_date(info_dict)
        except concurrent.futures.TimeoutError:
            raise RuntimeError(
                f"Reading browser cookies timed out after {cookie_timeout}s. "
                "Close the browser completely, or use a cookie file "
                "(YOUTUBE_COOKIE_FILE) which never hangs."
            )
        except youtube_dl.utils.DownloadError as exc:
            raise RuntimeError(
                "YouTube still blocks access with browser cookies. "
                "Ensure you are logged into YouTube and the browser is closed."
            ) from exc


# ---------------------------------------------------------------------------
# Learning material generation
# ---------------------------------------------------------------------------


# Back-compat alias used inside validation.
_canonical_target_language = canonical_target_language


class LearningMaterialValidationError(ValueError):
    """Raised when MiniMax cannot produce a valid learning-material JSON."""


# Shared constants / helpers used by _validate_lesson_json and Generator._validate_module.
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
            if not isinstance(item, dict) or not isinstance(item.get("term"), str) or not item["term"].strip():
                errors.append(
                    f"import_words[{index}].term must be a non-empty "
                    "target-language word or phrase"
                )
            if not isinstance(item, dict) or not isinstance(item.get("part_of_speech"), str) or not item["part_of_speech"].strip():
                errors.append(f"import_words[{index}].part_of_speech must be a non-empty string")
            senses = item.get("senses") if isinstance(item, dict) else None
            if not isinstance(senses, list) or not senses:
                errors.append(f"import_words[{index}].senses must be a non-empty list")
            else:
                for sense_index, sense in enumerate(senses):
                    if not isinstance(sense, dict):
                        errors.append(f"import_words[{index}].senses[{sense_index}] must be an object")
                        continue
                    if not isinstance(sense.get("definition"), str) or not sense["definition"].strip():
                        errors.append(f"import_words[{index}].senses[{sense_index}].definition is required")
                    if not isinstance(sense.get("example"), str) or not sense["example"].strip():
                        errors.append(f"import_words[{index}].senses[{sense_index}].example is required")
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


def _checker_errors_are_off_module(name: str, errors: list[str]) -> bool:
    """True when Checker complaints are about other modules (e.g. stress on expression)."""
    if not errors:
        return False
    joined = " ".join(errors).lower()
    off_topic = (
        "stress", "stress_marked", "import_words", "headword", "граммат",
        "gender", "collocation", "part_of_speech", "баражир", "противовозд",
    )
    on_topic = {
        "expression": ("speaking_task", "writing_task", "review", "speak", "write"),
        "core": ("lesson_title", "level", "can_do", "warm_up"),
    }.get(name, ())
    if on_topic and any(token in joined for token in on_topic):
        return False
    return any(token in joined for token in off_topic)


class Generator:
    """Build learning material with a Writer agent + Checker agent loop.

    Flow per module: Writer → local schema gate → Checker → Writer revision
    (up to ``MINIMAX_VALIDATION_RETRIES`` rounds). Independent modules run in
    parallel (``MINIMAX_MODULE_WORKERS``, default 6).
    """

    def __init__(self, target_language: str, native_language: str, text):
        self.target_language = target_language
        self.native_language = native_language
        self.text = str(text)
        self.prompts = get_language_pack(target_language)
        self.prompt = self._lesson_prompt(self.text)
        self.message_history: list[dict] = []
        self._history_lock = threading.Lock()
        self.reply = ""

    def _append_history(self, *messages: dict) -> None:
        with self._history_lock:
            self.message_history.extend(messages)

    def _lesson_prompt(self, source: str) -> str:
        return (
            f"Learner native language: {self.native_language}; "
            f"target language: {self.target_language}.\nSource:\n{source}"
        )

    @staticmethod
    def _response_text(response) -> str:
        return response if isinstance(response, str) else str(response)

    def _request(self, client, prompt: str, model: str, *, label: str = "request") -> str:
        max_retries = _env_int(
            "MINIMAX_MAX_RETRIES",
            _env_int("MINIMAX_MAX_RETRIES", DEFAULT_MAX_RETRIES, 0, MAX_MAX_RETRIES),
            0,
            MAX_MAX_RETRIES,
        )
        max_tokens = _env_int(
            "MINIMAX_MAX_TOKENS",
            _env_int("MINIMAX_MAX_TOKENS", DEFAULT_MAX_TOKENS, MIN_MAX_TOKENS, MAX_MAX_TOKENS),
            MIN_MAX_TOKENS,
            MAX_MAX_TOKENS,
        )
        for attempt in range(max_retries + 1):
            started = time.perf_counter()
            try:
                response = client.chat(
                    messages=[{"role": "user", "content": prompt}],
                    model=model,
                    temperature=0,
                    max_tokens=max_tokens,
                )
                text = self._response_text(response)
                logger.warning(
                    "MiniMax %s ok in %.1fs (prompt=%s chars, reply=%s chars, max_tokens=%s, attempt=%s)",
                    label,
                    time.perf_counter() - started,
                    len(prompt),
                    len(text),
                    max_tokens,
                    attempt + 1,
                )
                return text
            except (httpx.RequestError, NetworkError, APIError) as exc:
                logger.warning(
                    "MiniMax %s failed in %.1fs (%s): %s",
                    label,
                    time.perf_counter() - started,
                    type(exc).__name__,
                    str(exc)[:200],
                )
                overloaded = isinstance(exc, APIError) and (
                    "overloaded" in str(exc).lower() or "529" in str(exc)
                )
                retryable = isinstance(exc, (httpx.RequestError, NetworkError)) or overloaded
                if not retryable or attempt >= max_retries:
                    raise
                delay = (15 * (2 ** attempt)) if overloaded else (2 ** attempt)
                logger.warning(
                    "MiniMax request failed (%s); retrying in %s seconds (attempt %s/%s)",
                    type(exc).__name__,
                    delay,
                    attempt + 2,
                    max_retries + 1,
                )
                time.sleep(delay)
        raise RuntimeError("unreachable")

    def _summarise_long_transcript(self, client, model: str) -> str:
        chunk_size = max(
            2000,
            _env_int(
                "MINIMAX_AGENT_CHUNK_CHARS",
                _env_int("MINIMAX_AGENT_CHUNK_CHARS", 6000, 2000, 1_000_000),
                2000,
                1_000_000,
            ),
        )
        summaries = []
        for index in range(0, len(self.text), chunk_size):
            chunk = self.text[index:index + chunk_size]
            prompt = self.prompts.summarise_chunk(chunk)
            raw = self._request(client, prompt, model, label=f"summarise[{index}]")
            try:
                parsed = json.loads(raw)
            except (TypeError, json.JSONDecodeError) as exc:
                raise LearningMaterialValidationError(f"Transcript summary was invalid JSON: {exc}") from exc
            if not isinstance(parsed, dict):
                raise LearningMaterialValidationError("Transcript summary must be a JSON object")
            summaries.append(parsed)
        return json.dumps(summaries, ensure_ascii=False)

    def _module_prompt(self, name: str, source: str) -> str:
        return self.prompts.module(
            name, self.target_language, self.native_language, source
        )

    @staticmethod
    def _parse_json_object(raw: str) -> tuple[dict, list[str]]:
        text = Generator._response_text(raw).strip()
        if not text:
            return {}, ["response is empty"]
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
            if text.lower().startswith("json"):
                text = text[4:].lstrip()
        try:
            data = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            # Attempt truncated-JSON recovery: close open brackets/braces.
            recovered = Generator._try_recover_truncated_json(text)
            if recovered is not None:
                data = recovered
            else:
                return {}, [f"response is not valid JSON (truncated or malformed)"]
        if not isinstance(data, dict):
            return {}, ["top-level JSON must be an object"]
        return data, []

    @staticmethod
    def _try_recover_truncated_json(text: str) -> dict | None:
        """Try to salvage a truncated JSON object by closing open brackets."""
        if not text or not text.strip().startswith("{"):
            return None
        # Walk the string tracking nesting; stop at last complete value.
        depth_brace = 0
        depth_bracket = 0
        in_string = False
        escape = False
        last_good = -1
        for i, ch in enumerate(text):
            if escape:
                escape = False
                continue
            if ch == '\\' and in_string:
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                depth_brace += 1
            elif ch == '}':
                depth_brace -= 1
                if depth_brace == 0:
                    last_good = i
            elif ch == '[':
                depth_bracket += 1
            elif ch == ']':
                depth_bracket -= 1
        # If we found a complete top-level object, use it.
        if last_good > 0:
            try:
                return json.loads(text[:last_good + 1])
            except (json.JSONDecodeError, TypeError):
                pass
        # Otherwise try progressively closing from the end.
        for trim in range(min(len(text), 200)):
            candidate = text[:len(text) - trim].rstrip().rstrip(',')
            # Close any open arrays then objects.
            suffix = ']' * max(0, depth_bracket) + '}' * max(0, depth_brace)
            try:
                data = json.loads(candidate + suffix)
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, TypeError):
                pass
        return None

    def _validate_module(
        self,
        name: str,
        raw: str,
        *,
        words_count_range: tuple[int, int] | None = None,
    ) -> tuple[dict, list[str]]:
        data, errors = Generator._parse_json_object(raw)
        if errors:
            return data, errors
        if name == "words":
            try:
                items = _normalise_collection(data.get("import_words"), "import_words")
            except (TypeError, AttributeError) as exc:
                return data, [str(exc)]
            data["import_words"] = items
            lo, hi = words_count_range or (8, 20)
            if not lo <= len(items) <= hi:
                errors.append(f"import_words must contain {lo}-{hi} items (got {len(items)})")
            is_russian = _canonical_target_language(self.target_language) == "russian"
            is_english = _canonical_target_language(self.target_language) == "english"
            is_german = _canonical_target_language(self.target_language) == "german"
            for i, item in enumerate(items):
                if not isinstance(item, dict) or not str(item.get("term", "")).strip():
                    errors.append(f"import_words[{i}].term is required")
                    continue
                if not str(item.get("part_of_speech", "")).strip():
                    errors.append(f"import_words[{i}].part_of_speech is required")
                pos_l = str(item.get("part_of_speech") or "").lower()
                if is_english and any(tok in pos_l for tok in ("сущ", "глаг", "прил", "substantiv")):
                    errors.append(
                        f"import_words[{i}].part_of_speech must be English "
                        f"(noun/verb/adjective), not {item.get('part_of_speech')!r}"
                    )
                if is_english:
                    ipa = str(item.get("ipa") or "").strip()
                    if not ipa:
                        pron = item.get("pronunciation")
                        if isinstance(pron, dict):
                            ipa = str(pron.get("ipa") or "").strip()
                    if not ipa:
                        errors.append(f"import_words[{i}].ipa is required for English entries")
                    cefr = str(item.get("cefr") or "").strip().upper()
                    if cefr not in _LEVELS:
                        errors.append(
                            f"import_words[{i}].cefr must be one of {_LEVELS}; got {item.get('cefr')!r}"
                        )
                if is_german and any(tok in pos_l for tok in ("сущ", "глаг", "прил")):
                    errors.append(
                        f"import_words[{i}].part_of_speech must be German "
                        f"(Substantiv/Verb/Adjektiv), not {item.get('part_of_speech')!r}"
                    )
                if is_german:
                    pron = item.get("pronunciation")
                    pronunciation = ""
                    if isinstance(pron, str):
                        pronunciation = pron.strip()
                    elif isinstance(pron, dict):
                        pronunciation = str(pron.get("ipa") or pron.get("phonetic") or "").strip()
                    if not pronunciation and not str(item.get("ipa") or "").strip():
                        errors.append(f"import_words[{i}].pronunciation is required for German entries")
                    if "substantiv" in pos_l or pos_l in {"noun", "n.", "n", "subst.", "subst"}:
                        article = str(item.get("article") or "").strip().lower()
                        if article not in {"der", "die", "das"}:
                            errors.append(
                                f"import_words[{i}].article (der/die/das) is required for nouns"
                            )
                        info = item.get("grammatical_info") if isinstance(item.get("grammatical_info"), dict) else {}
                        gender = str((info or {}).get("gender") or item.get("gender") or "").strip().lower()
                        if gender not in {
                            "masculine", "feminine", "neuter", "m", "f", "n",
                            "masc", "fem", "neut", "maskulin", "feminin", "neutral",
                        } and not gender.startswith(("masc", "fem", "neut")):
                            errors.append(
                                f"import_words[{i}].gender is required for German nouns"
                            )
                if is_russian:
                    pron = item.get("pronunciation")
                    marked = ""
                    if isinstance(pron, dict):
                        marked = str(pron.get("stress_marked") or "").strip()
                    elif isinstance(pron, str):
                        marked = pron.strip()
                    if not marked or "\u0301" not in marked:
                        errors.append(
                            f"import_words[{i}].pronunciation.stress_marked is required "
                            f"(Russian headword with acute stress, e.g. сотрудни́чество)"
                        )
                    pos_l = str(item.get("part_of_speech") or "").lower()
                    if "сущ" in pos_l or pos_l in {"noun", "n.", "n", "substantive"}:
                        info = item.get("grammatical_info") if isinstance(item.get("grammatical_info"), dict) else {}
                        gender = str(
                            (info or {}).get("gender") or item.get("gender") or ""
                        ).strip().lower().rstrip(".")
                        gender_ok = gender in {
                            "masculine", "feminine", "neuter",
                            "m", "f", "n", "м", "ж", "с", "ср",
                            "мужской", "женский", "средний",
                            "м.р", "ж.р", "с.р", "ср.р",
                            "муж", "жен", "средн",
                        } or gender.startswith(("masc", "fem", "neut", "муж", "жен", "сред"))
                        if not gender_ok:
                            errors.append(
                                f"import_words[{i}].grammatical_info.gender is required "
                                f"for nouns (masculine/feminine/neuter); term="
                                f"{item.get('term')!r}"
                            )
                senses = item.get("senses")
                if not isinstance(senses, list) or not senses:
                    errors.append(f"import_words[{i}].senses is required")
                    continue
                for j, sense in enumerate(senses):
                    if not isinstance(sense, dict) or not str(sense.get("definition", "")).strip():
                        errors.append(f"import_words[{i}].senses[{j}].definition is required")
                    if not isinstance(sense, dict) or not str(sense.get("translation", "")).strip():
                        errors.append(
                            f"import_words[{i}].senses[{j}].translation is required "
                            f"(learner native-language gloss)"
                        )
                    if not isinstance(sense, dict) or not str(sense.get("example", "")).strip():
                        errors.append(f"import_words[{i}].senses[{j}].example is required")
        elif name == "grammar":
            items = data.get("import_grammars")
            if not isinstance(items, list) or len(items) < 2:
                errors.append("import_grammars must contain at least 2 items")
            else:
                for i, item in enumerate(items):
                    if not isinstance(item, dict):
                        errors.append(f"import_grammars[{i}] must be an object")
                        continue
                    if not str(item.get("pattern") or "").strip():
                        errors.append(f"import_grammars[{i}].pattern is required")
                    if not str(item.get("meaning") or "").strip():
                        errors.append(f"import_grammars[{i}].meaning is required")
                    overview = str(item.get("overview") or item.get("explanation") or "").strip()
                    if not overview:
                        errors.append(
                            f"import_grammars[{i}].overview is required "
                            f"(short intro only; not a dump of collocations/forms)"
                        )
                    elif "【" in overview and not item.get("collocations"):
                        errors.append(
                            f"import_grammars[{i}].overview must not contain 【section】 dumps; "
                            f"put collocations/forms/model/note in their own fields"
                        )
                    cols = item.get("collocations")
                    if not isinstance(cols, list) or not cols:
                        # Allow legacy blob only when explanation still carries sections.
                        if "【" not in str(item.get("explanation") or ""):
                            errors.append(f"import_grammars[{i}].collocations must be a non-empty list")
                    model = item.get("model")
                    has_model = isinstance(model, dict) and str(
                        model.get("sentence") or model.get("phrase") or ""
                    ).strip()
                    if not has_model and not str(item.get("example") or "").strip():
                        if "【" not in str(item.get("explanation") or ""):
                            errors.append(f"import_grammars[{i}].model.sentence is required")
                    examples = item.get("examples")
                    has_examples = isinstance(examples, list) and any(
                        isinstance(ex, dict) and str(ex.get("phrase") or "").strip()
                        for ex in examples
                    )
                    if not has_examples and not str(item.get("example") or "").strip():
                        errors.append(f"import_grammars[{i}].examples is required")
                    practice = item.get("practice")
                    if isinstance(practice, dict):
                        items_p = practice.get("items")
                        if not isinstance(items_p, list) or not items_p:
                            errors.append(
                                f"import_grammars[{i}].practice.items must be a non-empty list"
                            )
                        else:
                            for j, row in enumerate(items_p):
                                if isinstance(row, str) and row.strip():
                                    errors.append(
                                        f"import_grammars[{i}].practice.items[{j}] must be "
                                        f'{{"prompt":"...","answer":"..."}} with a target-language answer'
                                    )
                                    continue
                                if not isinstance(row, dict):
                                    errors.append(
                                        f"import_grammars[{i}].practice.items[{j}] must be an object"
                                    )
                                    continue
                                if not str(row.get("prompt") or "").strip():
                                    errors.append(
                                        f"import_grammars[{i}].practice.items[{j}].prompt is required"
                                    )
                                if not str(row.get("answer") or "").strip():
                                    errors.append(
                                        f"import_grammars[{i}].practice.items[{j}].answer is required"
                                    )
                    elif not str(practice or "").strip():
                        errors.append(f"import_grammars[{i}].practice is required")
        elif name == "listening":
            for key in ("listening_tasks", "questions", "answers"):
                if not isinstance(data.get(key), list) or not data[key]:
                    errors.append(f"{key} must be a non-empty list")
            tasks = data.get("listening_tasks") or []
            for i, task in enumerate(tasks):
                if not isinstance(task, dict):
                    errors.append(f"listening_tasks[{i}] must be an object")
                    continue
                # Legacy flat Q/A is still accepted for older fixtures.
                if str(task.get("question") or "").strip() and str(task.get("answer") or "").strip():
                    continue
                kind = str(task.get("type") or "").strip().lower()
                if kind not in {"true_false", "multiple_choice", "fill_in_the_blank"}:
                    errors.append(
                        f"listening_tasks[{i}].type must be true_false, "
                        f"multiple_choice, or fill_in_the_blank"
                    )
                if not str(task.get("instruction") or "").strip():
                    errors.append(f"listening_tasks[{i}].instruction is required")
                items = task.get("items")
                if not isinstance(items, list) or not items:
                    errors.append(f"listening_tasks[{i}].items must be a non-empty list")
                    continue
                for j, item in enumerate(items):
                    if not isinstance(item, dict):
                        errors.append(f"listening_tasks[{i}].items[{j}] must be an object")
                        continue
                    if not str(item.get("answer") or "").strip():
                        errors.append(f"listening_tasks[{i}].items[{j}].answer is required")
                    if kind == "true_false" and not str(item.get("statement") or "").strip():
                        errors.append(f"listening_tasks[{i}].items[{j}].statement is required")
                    if kind == "multiple_choice":
                        if not str(item.get("question") or "").strip():
                            errors.append(f"listening_tasks[{i}].items[{j}].question is required")
                        opts = item.get("options")
                        if not isinstance(opts, list) or len(opts) < 2:
                            errors.append(
                                f"listening_tasks[{i}].items[{j}].options needs at least 2 choices"
                            )
                    if kind == "fill_in_the_blank" and not str(item.get("sentence") or "").strip():
                        errors.append(f"listening_tasks[{i}].items[{j}].sentence is required")
        elif name == "expression":
            for key in ("speaking_task", "writing_task"):
                value = data.get(key)
                if isinstance(value, dict):
                    if not str(value.get("prompt") or "").strip():
                        errors.append(f"{key}.prompt is required")
                    words = value.get("useful_language")
                    if not isinstance(words, list) or not any(str(x).strip() for x in words):
                        errors.append(f"{key}.useful_language must be a non-empty list")
                    checks = value.get("checklist")
                    if not isinstance(checks, list) or not any(str(x).strip() for x in checks):
                        errors.append(f"{key}.checklist must be a non-empty list")
                    if not str(
                        value.get("sample_answer")
                        or value.get("model_answer")
                        or value.get("answer")
                        or ""
                    ).strip():
                        errors.append(f"{key}.sample_answer is required")
                elif not (isinstance(value, str) and value.strip()):
                    errors.append(f"{key} must be an object or non-empty string")
            review = data.get("review")
            if not isinstance(review, list) or not review:
                errors.append("review must be a non-empty list")
        elif name == "translation":
            if "translation" not in data:
                errors.append(
                    'top-level key "translation" is required '
                    '(got a bare map or other keys; wrap as {"translation": {...}})'
                )
            elif not isinstance(data.get("translation"), dict) or not data["translation"]:
                errors.append("translation must be a non-empty object")
        elif name == "core":
            if not str(data.get("lesson_title", "")).strip():
                errors.append("lesson_title is required")
            if data.get("level") not in _LEVELS:
                errors.append("level must be one of A1/A2/B1/B2/C1/C2")
            for key in ("can_do", "warm_up"):
                if not isinstance(data.get(key), list) or not data[key]:
                    errors.append(f"{key} must be a non-empty list")
        return data, errors

    def _shape_hint(self, name: str) -> str:
        return self.prompts.shape_hint(name)

    def _writer_prompt(
        self,
        name: str,
        source: str,
        *,
        extra: str = "",
    ) -> str:
        body = (
            "You are the Writer agent for a language-learning lesson.\n"
            f"{self._module_prompt(name, source)}"
        )
        if extra.strip():
            body = f"{body}\n{extra.strip()}"
        return body

    def _words_batch_instruction(
        self,
        batch_index: int,
        batch_count: int,
        per_batch: int,
        avoid_terms: list[str] | None = None,
    ) -> str:
        focuses = (
            "Prioritize nouns, noun phrases, and topic-carrying content terms from the source.",
            "Prioritize verbs, adjectives, adverbs, and multi-word expressions; skip lemmas "
            "another batch is likely to take as plain nouns.",
            "Prioritize remaining high-value items: collocation-rich phrases, technical terms, "
            "and anything essential still uncovered.",
        )
        focus = focuses[min(batch_index, len(focuses) - 1)]
        avoid = ""
        if avoid_terms:
            listed = ", ".join(avoid_terms[:40])
            avoid = f" Do NOT repeat these lemmas already covered: {listed}."
        return (
            f"VOCABULARY BATCH {batch_index + 1} of {batch_count}. "
            f"Return EXACTLY {per_batch} full dictionary entries in import_words "
            f"(count must be {per_batch}; ±0). "
            "Do NOT lower quality: every entry needs the same required fields as a complete "
            "lesson vocabulary list (POS, pronunciation/IPA/stress as required for this "
            "target language, CEFR when English, senses with definition + native translation "
            "+ example + collocations). "
            f"{focus} "
            "Choose DISTINCT high-value lemmas grounded in the source; no padding, "
            f"no near-duplicate stubs, no invented morphology.{avoid}"
        )

    @staticmethod
    def _merge_word_batches(batches: list[dict]) -> dict:
        """Deduplicate by normalized lemma; keep first full entry; cap at 20."""
        seen: set[str] = set()
        merged: list[dict] = []
        for data in batches:
            for item in data.get("import_words") or []:
                if not isinstance(item, dict):
                    continue
                term = str(item.get("term") or "").strip()
                key = term.casefold()
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                if len(merged) >= 20:
                    return {"import_words": merged}
        return {"import_words": merged}

    def _writer_repair_prompt(self, name: str, source: str, raw: str, errors: list[str]) -> str:
        return (
            "You are the Writer agent. Revise ONLY this module so it satisfies the Checker "
            "and schema. Return one JSON object only. No markdown fences.\n"
            f"Module: {name}\n"
            f"Required shape example: {self._shape_hint(name)}\n"
            f"Issues to fix: {json.dumps(errors, ensure_ascii=False)}\n"
            f"Previous module response: {raw}\n"
            f"Context:\n{self._lesson_prompt(source)[:6000]}"
        )

    def _checker_prompt(self, name: str, source: str, data: dict) -> str:
        lang_bar = ""
        if hasattr(self.prompts, "checker_criteria"):
            lang_bar = self.prompts.checker_criteria(name).strip()
        module_bar = lang_bar or (
            "- Exact required top-level keys for this module.\n"
            "- Grounded in the source; no invented video facts."
        )
        return (
            "You are the Checker agent. Another Writer agent produced a lesson module. "
            "Judge it strictly; do not invent new lesson content beyond citing defects.\n"
            f"Module: {name}\n"
            f"Learner native language: {self.native_language}; target language: {self.target_language}\n"
            f"Required shape example: {self._shape_hint(name)}\n"
            "Quality bar:\n"
            f"{module_bar}\n"
            "- grammar: separate fields pattern/meaning/overview/collocations/forms/model/"
            "note/examples/practice; reject 【section】 dumps inside overview; lightly "
            "adapted examples OK; ignore pedantic morphology side-notes.\n"
            "- expression: judge ONLY speaking_task, writing_task, and review — topical and "
            "non-empty. Do NOT audit dictionary stress marks, gender, or side example lines "
            "embedded in task wording.\n"
            "- Prefer ok=true when schema-complete and pedagogically usable; reject only for "
            "missing keys, empty required fields, or clear false claims about the video.\n"
            f"- Scope: judge ONLY the {name} module fields shown in the candidate JSON.\n"
            f"Source (full when short):\n{source[:20000]}\n"
            f"Candidate JSON:\n{json.dumps(data, ensure_ascii=False)}\n"
            'Return JSON only: {"ok": true} or {"ok": false, "errors": ["concrete defect", ...]}.'
        )

    def _run_checker(self, client, model: str, name: str, source: str, data: dict) -> list[str]:
        """Return empty list if Checker accepts; otherwise defect strings."""
        prompt = self._checker_prompt(name, source, data)
        raw = self._request(client, prompt, model, label=f"checker[{name}]")
        self._append_history(
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": raw},
        )
        verdict, parse_errors = self._parse_json_object(raw)
        if parse_errors:
            return [f"Checker response invalid: {parse_errors[0]}"]
        if verdict.get("ok") is True:
            return []
        errors = verdict.get("errors")
        if isinstance(errors, list) and errors:
            return [str(item) for item in errors if str(item).strip()]
        if verdict.get("ok") is False:
            return ["Checker rejected the module without specific errors"]
        return ["Checker response missing ok=true"]

    def _run_module(
        self,
        client,
        model: str,
        name: str,
        source: str,
        *,
        writer_extra: str = "",
        words_count_range: tuple[int, int] | None = None,
        label: str | None = None,
    ) -> dict:
        """Writer produces; local schema gate; Checker reviews; Writer revises on fail."""
        module_started = time.perf_counter()
        tag = label or name
        retries = _env_int(
            "MINIMAX_VALIDATION_RETRIES",
            _env_int("MINIMAX_VALIDATION_RETRIES", 1, 0, 3),
            0,
            3,
        )
        prompt = self._writer_prompt(name, source, extra=writer_extra)
        last_errors: list[str] = []
        last_raw = ""
        for attempt in range(retries + 1):
            raw = self._request(
                client, prompt, model, label=f"writer[{tag}]#{attempt + 1}"
            )
            last_raw = raw
            self._append_history(
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": raw},
            )
            data, structural = self._validate_module(
                name, raw, words_count_range=words_count_range
            )
            if structural:
                last_errors = structural
                if attempt >= retries:
                    break
                prompt = self._writer_repair_prompt(name, source, raw, structural)
                if writer_extra.strip():
                    prompt = f"{prompt}\n{writer_extra.strip()}"
                continue

            checker_errors = self._run_checker(client, model, name, source, data)
            if not checker_errors:
                logger.warning(
                    "Module %s done in %.1fs (ok)",
                    tag,
                    time.perf_counter() - module_started,
                )
                return data
            # Soft-accept when Checker drifts into off-module audits or when
            # local schema validation already guarantees structural quality.
            # translation often gets false positives from Checker auditing
            # merged timestamps; expression gets false positives from embedded vocab.
            if _checker_errors_are_off_module(name, checker_errors) or name == "translation":
                logger.warning(
                    "Checker soft-accept on %s: %s",
                    name,
                    "; ".join(checker_errors[:3]),
                )
                logger.warning(
                    "Module %s done in %.1fs (soft-accept)",
                    tag,
                    time.perf_counter() - module_started,
                )
                return data
            last_errors = checker_errors
            if attempt >= retries:
                break
            prompt = self._writer_repair_prompt(name, source, raw, checker_errors)
            if writer_extra.strip():
                prompt = f"{prompt}\n{writer_extra.strip()}"

        raise LearningMaterialValidationError(
            f"MiniMax module {tag} invalid after Writer/Checker loop: "
            + "; ".join(last_errors or ["unknown error"])
            + (f" | last_raw={last_raw[:240]}" if last_raw else "")
        )

    def _run_words_module(self, client, model: str, source: str) -> dict:
        """Generate vocabulary in parallel batches, then merge without quality loss."""
        started = time.perf_counter()
        batches = _env_int("MINIMAX_WORDS_BATCHES", 2, 1, 4)
        if batches <= 1:
            return self._run_module(client, model, "words", source)

        # Target ~16 full entries across batches (still within final 8–20).
        target_total = 16
        per_batch = max(4, min(10, (target_total + batches - 1) // batches))
        count_range = (per_batch, per_batch)
        logger.warning(
            "Words split into %s parallel batches (%s entries each, full dictionary quality)",
            batches,
            per_batch,
        )

        def _one(batch_index: int) -> dict:
            extra = self._words_batch_instruction(batch_index, batches, per_batch)
            return self._run_module(
                client,
                model,
                "words",
                source,
                writer_extra=extra,
                words_count_range=count_range,
                label=f"words-b{batch_index + 1}/{batches}",
            )

        parts: list[dict | None] = [None] * batches
        failures: list[BaseException] = []
        with ThreadPoolExecutor(max_workers=batches) as pool:
            futures = {pool.submit(_one, i): i for i in range(batches)}
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    parts[idx] = future.result()
                except BaseException as exc:
                    failures.append(exc)
                    logger.exception("Words batch %s/%s failed", idx + 1, batches)
                    for pending in futures:
                        pending.cancel()
        if failures:
            raise failures[0]

        merged = self._merge_word_batches([p for p in parts if p is not None])
        items = merged["import_words"]
        if len(items) < 8:
            need = 8 - len(items)
            avoid = [str(x.get("term") or "") for x in items]
            fill_n = max(need, min(8, need + 2))
            extra = self._words_batch_instruction(
                batches, batches + 1, fill_n, avoid_terms=avoid
            )
            extra += (
                f" This is a FILL batch: add {fill_n} NEW lemmas only; "
                "keep the same full dictionary quality."
            )
            fill = self._run_module(
                client,
                model,
                "words",
                source,
                writer_extra=extra,
                words_count_range=(need, fill_n),
                label="words-fill",
            )
            merged = self._merge_word_batches([merged, fill])
            items = merged["import_words"]

        if not 8 <= len(items) <= 20:
            raise LearningMaterialValidationError(
                f"Merged import_words must contain 8-20 items (got {len(items)})"
            )

        checker_errors = self._run_checker(client, model, "words", source, merged)
        if checker_errors:
            prompt = self._writer_repair_prompt(
                "words",
                source,
                json.dumps(merged, ensure_ascii=False),
                checker_errors,
            )
            prompt += (
                "\nKeep ALL existing high-quality entries when possible; "
                "fix defects without shrinking below 8 items or inventing thin stubs."
            )
            raw = self._request(client, prompt, model, label="writer[words-merge-repair]#1")
            repaired, structural = self._validate_module("words", raw)
            if structural:
                raise LearningMaterialValidationError(
                    "Merged words failed repair: " + "; ".join(structural)
                )
            merged = repaired
            checker_errors = self._run_checker(client, model, "words", source, merged)
            if checker_errors:
                raise LearningMaterialValidationError(
                    "Merged words rejected by Checker: " + "; ".join(checker_errors)
                )

        logger.warning(
            "Module words done in %.1fs (merged %s entries from %s batches)",
            time.perf_counter() - started,
            len(merged["import_words"]),
            batches,
        )
        return merged

    def chatbox(self, model: str = TEXT_MODEL) -> None:
        client = _get_client()
        total_started = time.perf_counter()
        threshold = max(
            4000,
            _env_int(
                "MINIMAX_AGENT_PROMPT_CHARS",
                _env_int("MINIMAX_AGENT_PROMPT_CHARS", 18000, 4000, 10_000_000),
                4000,
                10_000_000,
            ),
        )
        source = self.text
        if len(self.prompt) > threshold:
            source = "Structured transcript summaries:\n" + self._summarise_long_transcript(client, model)
        self.message_history = []
        lesson = {}
        workers = _env_int("MINIMAX_MODULE_WORKERS", 6, 1, len(_LESSON_MODULES))
        logger.warning(
            "Lesson generation start: workers=%s model=%s source_chars=%s target=%s native=%s",
            workers,
            model,
            len(source),
            self.target_language,
            self.native_language,
        )
        if workers <= 1:
            for name in _LESSON_MODULES:
                if name == "words":
                    lesson.update(self._run_words_module(client, model, source))
                else:
                    lesson.update(self._run_module(client, model, name, source))
        else:
            logger.warning(
                "Generating %s lesson modules in parallel (workers=%s)",
                len(_LESSON_MODULES),
                workers,
            )

            def _run_one(name: str) -> tuple[str, dict]:
                if name == "words":
                    return name, self._run_words_module(client, model, source)
                return name, self._run_module(client, model, name, source)

            results: dict[str, dict] = {}
            failures: list[BaseException] = []
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_run_one, name): name for name in _LESSON_MODULES}
                for future in as_completed(futures):
                    name = futures[future]
                    try:
                        module_name, data = future.result()
                        results[module_name] = data
                    except BaseException as exc:
                        failures.append(exc)
                        logger.exception("Lesson module %s failed in parallel run", name)
                        for pending in futures:
                            pending.cancel()
            if failures:
                raise failures[0]
            for name in _LESSON_MODULES:
                lesson.update(results[name])
        data, merge_errors = _validate_lesson_json(json.dumps(lesson, ensure_ascii=False))
        if merge_errors:
            raise LearningMaterialValidationError(
                "Merged learning material invalid: " + "; ".join(merge_errors)
            )
        self.reply = json.dumps(data, ensure_ascii=False)
        logger.warning(
            "Lesson generation finished in %.1fs (reply=%s chars)",
            time.perf_counter() - total_started,
            len(self.reply),
        )


# ---------------------------------------------------------------------------
# Background job runner
# ---------------------------------------------------------------------------
#
# ``wait_view`` used to call ``Transcribe.audio2text()`` synchronously in
# the HTTP request thread, which meant the browser sat on a blank loading
# screen for the full YouTube-download + LLM round trip (often
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
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Callable

from django.db import close_old_connections

# Module order for merge / display; all six are independent given the same source.
_LESSON_MODULES = ("core", "words", "grammar", "listening", "expression", "translation")


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

