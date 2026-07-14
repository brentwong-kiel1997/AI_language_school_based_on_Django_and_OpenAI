"""Utility helpers for the YouTube → learning-material pipeline.

Ark chat + Seed ASR live in the standalone ``ark_cli`` package. This module
keeps Django-facing orchestration: captions/yt-dlp (``Transcribe``), lesson
generation (``Generator``), and background jobs.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import yt_dlp as youtube_dl
from ark_cli import asr, get_client, reset_client
from ark_cli.config import (
    DEFAULT_ARK_MAX_TOKENS,
    DEFAULT_ARK_MODEL,
    MAX_ARK_MAX_TOKENS,
    MIN_ARK_MAX_TOKENS,
    load_dotenv,
    env_int as _env_int,
)

logger = logging.getLogger(__name__)

DEFAULT_ARK_MAX_RETRIES = 2
MAX_ARK_MAX_RETRIES = 10

load_dotenv(
    (
        Path(__file__).resolve().parents[2] / ".env",
        Path(__file__).resolve().parents[1] / ".env",
    )
)

TEXT_MODEL = os.environ.get("ARK_MODEL", DEFAULT_ARK_MODEL)

# Compat aliases for tests and older callers.
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


def _parse_caption_payload(payload: dict) -> list[dict]:
    segments = []
    for event in payload.get("events", []):
        text = "".join(part.get("utf8", "") for part in event.get("segs", [])).strip()
        if not text or text == "\n":
            continue
        start = event.get("tStartMs", 0) / 1000
        segments.append({"start": start,
                         "end": start + event.get("dDurationMs", 0) / 1000,
                         "text": text})
    return segments


def _normalise_asr_language(utterances: list[dict]) -> str:
    aliases = {"speech_mand": "zh", "speech_en": "en"}
    for utterance in utterances:
        additions = utterance.get("additions") or {}
        language = additions.get("lid_lang")
        if language:
            return aliases.get(language, language.removeprefix("speech_"))
    return "und"


def _asr_language_hint(info: dict) -> str | None:
    language_map = {
        "ru": "ru-RU", "ru-orig": "ru-RU", "en": "en-US",
        "zh": "zh-CN", "de": "de-DE", "fr": "fr-FR",
        "es": "es-ES", "ja": "ja-JP", "ko": "ko-KR",
    }
    for field in ("language", "original_language"):
        value = info.get(field)
        if isinstance(value, str) and (mapped := language_map.get(value.strip().lower())):
            return mapped
    return None


def _asr_transcript(result: dict, duration: float) -> tuple[dict, dict[str, str], str]:
    utterances = result.get("utterances") or []
    definite = [item for item in utterances if item.get("definite")]
    selected = definite or utterances
    segments = [{"start": item.get("start_time", 0) / 1000,
                 "end": item.get("end_time", item.get("start_time", 0)) / 1000,
                 "text": item.get("text", "")}
                for item in selected if str(item.get("text", "")).strip()]
    text = str(result.get("text", "")).strip()
    if not segments and text:
        segments = [{"start": 0.0, "end": duration, "text": text}]
    language = _normalise_asr_language(selected)
    transcript = {"language": language, "duration": duration,
                  "text": text or " ".join(item["text"] for item in segments),
                  "segments": segments, "source": "seed_asr_2.0"}
    return transcript, _text_with_timestamps(segments), language


class Transcribe:
    """Use YouTube captions first and Seed ASR 2.0 only as a fallback."""

    def __init__(self, url: str):
        self.url = url

    @staticmethod
    def _download_and_convert(url: str, output_path: Path, created: list[Path]) -> Path:
        runtimes = _detect_yt_dlp_runtimes()
        if not runtimes:
            raise RuntimeError(_yt_dlp_runtime_help())
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("FFmpeg is required for speech recognition. Install it and ensure `ffmpeg` is on PATH.")
        work_dir = Path(tempfile.mkdtemp(prefix="bals-asr-", dir=output_path))
        created.append(work_dir)
        source_template = work_dir / "source.%(ext)s"
        opts = {"format": "bestaudio/best", "outtmpl": str(source_template),
                "js_runtimes": {Path(rt).name: {"path": rt} for rt in runtimes},
                "retries": 3, "fragment_retries": 3, "ignoreerrors": False}
        with youtube_dl.YoutubeDL(opts) as downloader:
            downloaded = downloader.extract_info(url, download=True)
            source = Path(downloader.prepare_filename(downloaded))
        created.append(source)
        wav_path = work_dir / "audio.wav"; created.append(wav_path)
        try:
            subprocess.run([ffmpeg, "-y", "-i", str(source), "-ar", "16000", "-ac", "1",
                            "-c:a", "pcm_s16le", str(wav_path)], check=True,
                           capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"FFmpeg could not convert the downloaded audio: {exc.stderr.strip()}") from exc
        return wav_path

    def audio2text(self, output_path: str | Path = "./download", max_duration: int = 600) -> None:
        output_path = Path(output_path); output_path.mkdir(parents=True, exist_ok=True)
        self.audio_file_path = None
        created: list[Path] = []
        info_dict = None
        metadata_opts = {"skip_download": True, "quiet": True}
        try:
            with youtube_dl.YoutubeDL(metadata_opts) as ydl:
                info_dict = ydl.extract_info(self.url, download=False)
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
                    wav_path = self._download_and_convert(self.url, output_path, created)
                    self.audio_file_path = str(wav_path)
                    result = asr.transcribe_wav(
                        wav_path, language=_asr_language_hint(info_dict)
                    )
                    self.transcript, self.text_with_ts, self.language = _asr_transcript(result, self.duration)
        except youtube_dl.utils.DownloadError as exc:
            lowered = str(exc).lower()
            if "javascript runtime" in lowered or "no supported javascript" in lowered:
                raise RuntimeError(_yt_dlp_runtime_help()) from exc
            if "sign in" in lowered or "confirm" in lowered:
                raise RuntimeError("YouTube is asking for sign-in / bot confirmation.") from exc
            if "video unavailable" in lowered or "private video" in lowered:
                raise ValueError("This YouTube video is unavailable.") from exc
            raise
        finally:
            for path in reversed(created):
                try:
                    if path.is_dir(): shutil.rmtree(path)
                    else: path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Could not clean temporary ASR file %s", path, exc_info=True)
        raw_date = (info_dict or {}).get("upload_date")
        try: self.upload_date = datetime.strptime(raw_date, "%Y%m%d").date().isoformat() if raw_date else None
        except ValueError: self.upload_date = None


# ---------------------------------------------------------------------------
# Learning material generation
# ---------------------------------------------------------------------------


# Language-specific dictionary instructions keep generated entries consistent and factual.
_DICTIONARY_PROMPTS = {
    'russian': 'Use a Russian dictionary-entry structure inspired by Gramota.ru and Ozhegov: term, pronunciation, part_of_speech, grammatical_info, forms, register, numbered senses, examples, collocations, synonyms, antonyms, phraseology, and note. For nouns provide gender and declension when applicable; for verbs provide aspect, government, and conjugation when applicable. Do not invent information: unsupported fields must be null or []. Target-language Russian must be accurate. Every sense contains definition, translation, example, and collocations. Return JSON only, with import_words as an array. Complete JSON example: {\"import_words\":[{\"term\":\"дом\",\"pronunciation\":{\"stress_marked\":\"до́м\",\"ipa\":\"[dom]\"},\"part_of_speech\":\"noun\",\"grammatical_info\":{\"gender\":\"masculine\",\"declension\":\"2nd declension\"},\"forms\":{\"plural\":\"дома́\"},\"register\":\"neutral\",\"senses\":[{\"definition\":\"Здание, предназначенное для жилья.\",\"translation\":\"house\",\"example\":\"Мы живём в большом доме.\",\"collocations\":[\"жилой дом\"]}],\"synonyms\":[\"жилище\"],\"antonyms\":[],\"phraseology\":[\"дом родной\"],\"note\":null}]}',
    'english': 'Use a Cambridge Dictionary-style structure: term, IPA, part_of_speech, CEFR level, numbered senses, definitions, examples, collocations, register, synonyms, antonyms, and usage note. Do not invent information; unsupported fields must be null or []. Target-language English must be accurate. Every sense contains definition, translation, example, and collocations. Return JSON only, with import_words as an array. Complete JSON example: {\"import_words\":[{\"term\":\"reliable\",\"ipa\":\"/rɪˈlaɪ.ə.bəl/\",\"part_of_speech\":\"adjective\",\"cefr\":\"B1\",\"senses\":[{\"definition\":\"Someone or something that can be trusted.\",\"translation\":\"可靠的\",\"example\":\"She is a reliable colleague.\",\"collocations\":[\"highly reliable\"]}],\"register\":\"neutral\",\"synonyms\":[\"dependable\"],\"antonyms\":[],\"usage_note\":null}]}',
    'german': 'Use a Duden/elexiko-style German structure: term, pronunciation, part_of_speech, article, gender, plural_or_forms, numbered senses, definitions, examples, collocations, register, and usage note. Do not invent information; unsupported fields must be null or []. Target-language German must be accurate. Every sense contains definition, translation, example, and collocations. Return JSON only, with import_words as an array. Complete JSON example: {\"import_words\":[{\"term\":\"Haus\",\"pronunciation\":\"[haʊ̯s]\",\"part_of_speech\":\"Substantiv\",\"article\":\"das\",\"gender\":\"neuter\",\"plural_or_forms\":{\"plural\":\"Häuser\"},\"senses\":[{\"definition\":\"Gebäude, in dem Menschen wohnen.\",\"translation\":\"房子\",\"example\":\"Das Haus steht am See.\",\"collocations\":[\"ein großes Haus\"]}],\"register\":\"neutral\",\"usage_note\":null}]}',
}
_GENERIC_DICTIONARY_PROMPT = 'Use a careful dictionary-entry structure: term, pronunciation when known, part_of_speech, grammatical information/forms, numbered senses, definition, translation, example, collocations, register, synonyms/antonyms, and usage_note. Do not invent anything; unsupported fields must be null or []. Ensure target-language accuracy. Return JSON only, with import_words as an array. Complete JSON example: {\"import_words\":[{\"term\":\"bonjour\",\"part_of_speech\":\"interjection\",\"senses\":[{\"definition\":\"A greeting.\",\"translation\":\"你好\",\"example\":\"Bonjour !\",\"collocations\":[]}],\"usage_note\":null}]}'

def _dictionary_prompt(target_language: str, native_language: str) -> str:
    key = str(target_language or '').strip().lower()
    aliases = {'russian':'russian','русский':'russian','ru':'russian','俄语':'russian','english':'english','英语':'english','en':'english','german':'german','德语':'german','de':'german'}
    return f'Learner native language: {native_language}; target language: {target_language}.\n' + _DICTIONARY_PROMPTS.get(aliases.get(key), _GENERIC_DICTIONARY_PROMPT)

_REQUIRED_LESSON_KEYS = ("lesson_title", "level", "can_do", "warm_up", "import_words", "import_grammars", "listening_tasks", "questions", "answers", "translation", "speaking_task", "writing_task", "review")
_LEVELS = {"A1", "A2", "B1", "B2", "C1", "C2"}
_DISPLAY_FIELDS = ("meaning", "example", "note", "pattern", "explanation", "practice")
def _has_display_content(value) -> bool:
    if isinstance(value, str): return bool(value.strip())
    if isinstance(value, (list, dict)): return bool(value)
    return value is not None
def _normalise_collection(value, name: str) -> list:
    if isinstance(value, list): return value
    if isinstance(value, dict): return [dict(item, term=key) if isinstance(item, dict) else {"term": key, "meaning": item} for key, item in value.items()]
    raise TypeError(f"{name} must be a list or object")
def _validate_lesson_json(raw: str) -> tuple[dict, list[str]]:
    try: data = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc: return {}, [f"response is not valid JSON: {exc}"]
    if not isinstance(data, dict): return {}, ["top-level JSON must be an object"]
    errors = [f"missing required key: {key}" for key in _REQUIRED_LESSON_KEYS if key not in data]
    if data.get("level") not in _LEVELS: errors.append("level must be one of A1/A2/B1/B2/C1/C2")
    try:
        words = _normalise_collection(data.get("import_words"), "import_words"); data["import_words"] = words
        if not 8 <= len(words) <= 20: errors.append("import_words must contain 8-20 items")
        for index, item in enumerate(words):
            if not isinstance(item, dict) or not isinstance(item.get("term"), str) or not item["term"].strip(): errors.append(f"import_words[{index}].term must be a non-empty target-language word or phrase"); continue
            if not isinstance(item.get("part_of_speech"), str) or not item["part_of_speech"].strip(): errors.append(f"import_words[{index}].part_of_speech must be a non-empty string")
            senses = item.get("senses")
            if not isinstance(senses, list) or not senses: errors.append(f"import_words[{index}].senses must be a non-empty list"); continue
            for si, sense in enumerate(senses):
                if not isinstance(sense, dict): errors.append(f"import_words[{index}].senses[{si}] must be an object"); continue
                if not isinstance(sense.get("definition"), str) or not sense["definition"].strip(): errors.append(f"import_words[{index}].senses[{si}].definition is required")
                if not isinstance(sense.get("example"), str) or not sense["example"].strip(): errors.append(f"import_words[{index}].senses[{si}].example is required")
    except (TypeError, AttributeError) as exc: errors.append(str(exc))
    try:
        grammars = _normalise_collection(data.get("import_grammars"), "import_grammars"); data["import_grammars"] = grammars
        if len(grammars) < 2: errors.append("import_grammars must contain at least 2 items")
        for index, item in enumerate(grammars):
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
    except (TypeError, AttributeError) as exc: errors.append(str(exc))
    for key in ("questions", "answers", "listening_tasks", "review"):
        if not isinstance(data.get(key), list) or not data.get(key): errors.append(f"{key} must be a non-empty list")
    if not isinstance(data.get("translation"), dict) or not data.get("translation"): errors.append("translation must be a non-empty object")
    for key in ("speaking_task", "writing_task"):
        if not _has_display_content(data.get(key)): errors.append(f"{key} must be non-empty")
    return data, errors


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


class Generator:
    """Build and validate learning material using a local orchestration agent."""

    def __init__(self, target_language: str, native_language: str, text):
        self.target_language = target_language
        self.native_language = native_language
        self.text = str(text)
        self.dictionary_prompt = _dictionary_prompt(target_language, native_language)
        self.prompt = self._lesson_prompt(self.text)

    def _lesson_prompt(self, source: str) -> str:
        return f"Learner native language: {self.native_language}; target language: {self.target_language}.\nSource:\n{source}"

    @staticmethod
    def _response_text(response) -> str:
        return response if isinstance(response, str) else str(response)

    def _request(self, client, prompt: str, model: str) -> str:
        max_retries = _env_int("ARK_MAX_RETRIES", DEFAULT_ARK_MAX_RETRIES, 0, MAX_ARK_MAX_RETRIES)
        max_tokens = _env_int("ARK_MAX_TOKENS", DEFAULT_ARK_MAX_TOKENS,
                              MIN_ARK_MAX_TOKENS, MAX_ARK_MAX_TOKENS)
        for attempt in range(max_retries + 1):
            try:
                response = client.chat(messages=[{"role": "user", "content": prompt}],
                                       model=model, temperature=0, max_tokens=max_tokens)
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
            prompt = ("Return JSON only with keys keywords, grammar_points, question_clues, "
                      "translation_clues, level_evidence, summary. Summarise this transcript "
                      "chunk without inventing facts:\n" + chunk)
            raw = self._request(client, prompt, model)
            try:
                parsed = json.loads(raw)
            except (TypeError, json.JSONDecodeError) as exc:
                raise LearningMaterialValidationError(f"Transcript summary was invalid JSON: {exc}") from exc
            if not isinstance(parsed, dict):
                raise LearningMaterialValidationError("Transcript summary must be a JSON object")
            summaries.append(parsed)
        return json.dumps(summaries, ensure_ascii=False)

    def _module_prompt(self, name: str, source: str) -> str:
        common = self._lesson_prompt(source)
        prompts = {
            "core": f"{common}\nReturn JSON only with lesson_title, level (A1-C2), can_do (array), warm_up (array).",
            "words": f"{common}\n{self.dictionary_prompt}\nReturn JSON only with import_words: 8-20 rich entries. Each entry MUST contain term, part_of_speech, senses; each sense MUST contain definition and example (and preferably translation/collocations).",
            "grammar": f"{common}\nReturn JSON only with import_grammars: at least 2 objects, each with pattern, example, explanation, practice. Ground them in the source.",
            "listening": f"{common}\nReturn JSON only with listening_tasks, questions, answers. Each must be a non-empty array and questions/answers must address the source.",
            "expression": f"{common}\nReturn JSON only with speaking_task, writing_task, review. Review must be a non-empty array.",
            "translation": f"{common}\nReturn JSON only with translation as a non-empty object mapping source segments or timestamps to translations.",
        }
        return prompts[name]

    @staticmethod
    def _validate_module(name: str, raw: str) -> tuple[dict, list[str]]:
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            return {}, [f"response is not valid JSON: {exc}"]
        if not isinstance(data, dict):
            return {}, ["top-level JSON must be an object"]
        errors = []
        if name == "words":
            try: items = _normalise_collection(data.get("import_words"), "import_words")
            except (TypeError, AttributeError) as exc: return data, [str(exc)]
            data["import_words"] = items
            if not 8 <= len(items) <= 20: errors.append("import_words must contain 8-20 items")
            for i, item in enumerate(items):
                if not isinstance(item, dict) or not str(item.get("term", "")).strip(): errors.append(f"import_words[{i}].term is required"); continue
                if not str(item.get("part_of_speech", "")).strip(): errors.append(f"import_words[{i}].part_of_speech is required")
                senses = item.get("senses")
                if not isinstance(senses, list) or not senses: errors.append(f"import_words[{i}].senses is required"); continue
                for j, sense in enumerate(senses):
                    if not isinstance(sense, dict) or not str(sense.get("definition", "")).strip(): errors.append(f"import_words[{i}].senses[{j}].definition is required")
                    if not isinstance(sense, dict) or not str(sense.get("example", "")).strip(): errors.append(f"import_words[{i}].senses[{j}].example is required")
        elif name == "grammar":
            items = data.get("import_grammars")
            if not isinstance(items, list) or len(items) < 2: errors.append("import_grammars must contain at least 2 items")
            else:
                for i, item in enumerate(items):
                    if not isinstance(item, dict) or not any(_has_display_content(item.get(k)) for k in _DISPLAY_FIELDS): errors.append(f"import_grammars[{i}] has no displayable content")
        elif name == "listening":
            for key in ("listening_tasks", "questions", "answers"):
                if not isinstance(data.get(key), list) or not data[key]: errors.append(f"{key} must be a non-empty list")
        elif name == "expression":
            for key in ("speaking_task", "writing_task"):
                if not _has_display_content(data.get(key)): errors.append(f"{key} must be non-empty")
            if not isinstance(data.get("review"), list) or not data["review"]: errors.append("review must be a non-empty list")
        elif name == "translation":
            if not isinstance(data.get("translation"), dict) or not data["translation"]: errors.append("translation must be a non-empty object")
        elif name == "core":
            if not str(data.get("lesson_title", "")).strip(): errors.append("lesson_title is required")
            if data.get("level") not in _LEVELS: errors.append("level must be one of A1/A2/B1/B2/C1/C2")
            for key in ("can_do", "warm_up"):
                if not isinstance(data.get(key), list) or not data[key]: errors.append(f"{key} must be a non-empty list")
        return data, errors

    def _run_module(self, client, model: str, name: str, source: str) -> dict:
        prompt = self._module_prompt(name, source)
        retries = _env_int("ARK_VALIDATION_RETRIES", 1, 0, 3)
        for attempt in range(retries + 1):
            raw = self._request(client, prompt, model)
            self.message_history.extend(({"role": "user", "content": prompt}, {"role": "assistant", "content": raw}))
            data, errors = self._validate_module(name, raw)
            if not errors: return data
            if attempt >= retries:
                raise LearningMaterialValidationError(f"Ark module {name} invalid after validation: " + "; ".join(errors))
            prompt = (f"Repair only the {name} module. Return its JSON object only.\n"
                      f"Validation errors: {json.dumps(errors, ensure_ascii=False)}\n"
                      f"Previous module response: {raw}")
        raise RuntimeError("unreachable")

    def chatbox(self, model: str = TEXT_MODEL) -> None:
        client = _get_client()
        threshold = max(4000, _env_int("ARK_AGENT_PROMPT_CHARS", 18000, 4000, 10_000_000))
        source = self.text
        if len(self.prompt) > threshold:
            source = "Structured transcript summaries:\n" + self._summarise_long_transcript(client, model)
        self.message_history = []
        lesson = {}
        for name in ("core", "words", "grammar", "listening", "expression", "translation"):
            lesson.update(self._run_module(client, model, name, source))
        data, errors = _validate_lesson_json(json.dumps(lesson, ensure_ascii=False))
        if errors:
            raise LearningMaterialValidationError("Merged learning material invalid: " + "; ".join(errors))
        self.reply = json.dumps(data, ensure_ascii=False)


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

