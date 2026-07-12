"""HTTP client for the MiniMax multimodal platform.

This module is a *from-scratch* pure-Python implementation of the API
surface exposed by the official mmx-cli. It depends only on ``httpx``
(already required by the project's existing requirements.txt).

All endpoints follow the public docs at
https://platform.minimaxi.com/docs/api-reference/api-overview.

We do not import or shell-out to the upstream ``mmx-cli`` Node tool –
this is the reason the package exists.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterable, Iterator

import httpx

from .auth import AuthStore
from .config import Config
from .exceptions import (
    APIError,
    AuthenticationError,
    FileTooLargeError,
    NetworkError,
    QuotaExceededError,
    ValidationError,
)
from .regions import Region, endpoint_for


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


def _strip_code_fence(text: str) -> str:
    r"""Remove a leading ```json (or ````) and trailing ````."""
    import re
    # ```json\n ... \n```
    m = re.match(
        r"^\s*```(?:json)?\s*\n?(.*?)\n?```\s*$", text, flags=re.DOTALL | re.IGNORECASE
    )
    if m:
        return m.group(1).strip()
    # Sometimes the model forgets the closing fence; strip the leading one.
    if text.startswith("```"):
        return text.lstrip("`").lstrip("json").lstrip().rstrip("`").strip()
    return text


@dataclass
class ChatMessage:
    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}

    @classmethod
    def system(cls, content: str) -> "ChatMessage":
        return cls("system", content)

    @classmethod
    def user(cls, content: str) -> "ChatMessage":
        return cls("user", content)

    @classmethod
    def assistant(cls, content: str) -> "ChatMessage":
        return cls("assistant", content)


@dataclass
class ChatChoice:
    index: int
    message: ChatMessage
    finish_reason: str | None = None


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ChatResponse:
    id: str
    model: str
    choices: list[ChatChoice]
    usage: Usage
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        if not self.choices:
            return ""
        return self.choices[0].message.content

    def to_json(self) -> str:
        r"""Return the response as a strict JSON string (parses as a dict).

        If the model returned free-form text that isn't valid JSON, we wrap it
        in ``{"text": "..."}`` so callers always get something they can
        ``json.loads`` on. Markdown triple-backtick fences are
        stripped automatically.
        """
        if len(self.choices) == 1:
            content = self.choices[0].message.content.strip()
            stripped = _strip_code_fence(content)
            try:
                json.loads(stripped)
                return stripped
            except (ValueError, TypeError):
                pass
        return json.dumps(
            {
                "id": self.id,
                "model": self.model,
                "text": self.text,
                "usage": {
                    "prompt_tokens": self.usage.prompt_tokens,
                    "completion_tokens": self.usage.completion_tokens,
                    "total_tokens": self.usage.total_tokens,
                },
            },
            ensure_ascii=False,
        )


@dataclass
class TranscriptionSegment:
    start: float
    end: float
    text: str


@dataclass
class TranscriptionResult:
    language: str | None
    duration: float | None
    text: str
    segments: list[TranscriptionSegment] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def text_with_ts(self) -> dict[str, str]:
        """Format identical to what the OpenAI Whisper output used to be:
        ``{"HH:MM:SS": "sentence", ...}``. The Django views rely on it.
        """
        from datetime import timedelta

        out: dict[str, str] = {}
        for seg in self.segments:
            ts = str(timedelta(seconds=int(seg.start))).split(".")[0]
            out[ts] = seg.text
        return out


@dataclass
class ImageResult:
    file_id: str
    url: str
    b64: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class VideoTask:
    task_id: str
    status: str  # "queued" | "processing" | "succeeded" | "failed"
    file_id: str | None = None
    url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class MiniMaxClient:
    """Synchronous client for the MiniMax multimodal platform.

    Examples
    --------

    >>> from minimax_cli import MiniMaxClient, ChatMessage
    >>> client = MiniMaxClient(api_key="sk-cp-xxx", region="cn")
    >>> resp = client.text_chat(
    ...     model="MiniMax-Text-01",
    ...     messages=[ChatMessage.user("Hello!")],
    ... )
    >>> print(resp.text)
    """

    DEFAULT_TIMEOUT = 120.0
    UPLOAD_TIMEOUT = 600.0

    def __init__(
        self,
        api_key: str | None = None,
        region: str | Region = Region.CN,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        config: Config | None = None,
        auth: AuthStore | None = None,
    ):
        self.config = config or Config.load()
        self.auth = auth or AuthStore(self.config)
        self.api_key = (
            api_key
            or self.config.api_key
            or os.environ.get("MINIMAX_API_KEY", "")
        )
        if not self.api_key:
            raise AuthenticationError(
                "No API key. Run `mmx auth login --api-key <key>` "
                "or set MINIMAX_API_KEY in your environment."
            )
        if isinstance(region, str):
            region = Region(region.lower())
        self.region = region
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            self.base_url = endpoint_for(self.region).base_url
        self.timeout = timeout
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": f"minimax_cli/0.1.0 (+https://platform.minimaxi.com)",
            },
        )

    # ---- lifecycle ----------------------------------------------------------
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "MiniMaxClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- low-level HTTP -----------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        params: dict | None = None,
        timeout: float | None = None,
    ) -> Any:
        try:
            r = self._http.request(
                method,
                path,
                json=json_body,
                params=params,
                timeout=timeout or self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise NetworkError(f"Request to {path} timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise NetworkError(f"Network error on {path}: {exc}") from exc
        return self._parse(r, path)

    def _parse(self, r: httpx.Response, path: str) -> Any:
        if r.status_code == 401:
            raise AuthenticationError(
                f"401 Unauthorized calling {path}. Check that your API key is "
                f"valid and the region matches the platform you bought the "
                f"key on. Run `mmx auth status` to inspect; use "
                f"`mmx config set --key region --value cn|global` to switch."
            )
        if r.status_code == 402 or r.status_code == 429:
            raise QuotaExceededError(
                f"Quota exhausted calling {path} (HTTP {r.status_code})."
            )
        if r.status_code >= 400:
            try:
                payload = r.json()
                msg = (
                    payload.get("base_resp", {}).get("status_msg")
                    or payload.get("error", {}).get("message")
                    or payload.get("message")
                    or r.text
                )
            except Exception:
                payload, msg = {"raw": r.text}, r.text
            if r.status_code == 413:
                raise FileTooLargeError(r.status_code, msg, payload)
            raise APIError(r.status_code, msg, payload)
        if not r.content:
            return {}
        try:
            return r.json()
        except json.JSONDecodeError:
            return {"_raw": r.text}

    # =====================================================================
    # text
    # =====================================================================
    def text_chat(
        self,
        messages: list[ChatMessage] | list[dict],
        model: str = "MiniMax-M3",
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        top_p: float = 1.0,
        stream: bool = False,
        json_mode: bool = False,
        system_prompt: str | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> ChatResponse:
        r"""Synchronous chat completion.

        If ``stream=True`` and ``on_delta`` is provided, partial tokens are
        forwarded to ``on_delta`` as they arrive. The returned
        :class:`ChatResponse` always contains the full reconstructed reply.

        .. note::
           ``json_mode=True`` does **not** set ``response_format`` (the
           MiniMax chat endpoint rejects that field with error 2013).
           Instead we inject a system-prompt instruction asking the model
           to return strict JSON, and :meth:`ChatResponse.to_json` strips
           any triple-backtick JSON wrapper on the way out.
        """
        if not messages:
            raise ValidationError("messages must not be empty.")
        if isinstance(messages[0], dict):
            payload_messages = list(messages)
        else:
            payload_messages = [m.to_dict() if isinstance(m, ChatMessage) else m for m in messages]

        # json_mode: inject a system prompt that explicitly asks for strict JSON
        # output.  We do NOT send OpenAI's ``response_format`` field because the
        # MiniMax endpoint returns ``invalid params, unknown response_format
        # type 'json_object'`` (status 2013) when we do.
        if json_mode:
            existing_system = next(
                (m for m in payload_messages if m.get("role") == "system"), None
            )
            json_directive = (
                "You MUST respond with a single valid JSON object and nothing else. "
                "Do not include any prose, code fences, or explanations – only the "
                "raw JSON. Make sure the JSON parses with ``json.loads``."
            )
            if existing_system:
                existing_system["content"] = (
                    existing_system["content"].rstrip() + "\n\n" + json_directive
                )
            else:
                payload_messages.insert(0, {"role": "system", "content": json_directive})

        if system_prompt and not any(m.get("role") == "system" for m in payload_messages):
            payload_messages.insert(0, {"role": "system", "content": system_prompt})

        body: dict[str, Any] = {
            "model": model,
            "messages": payload_messages,
            "temperature": temperature,
            "top_p": top_p,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        # NOTE: ``response_format`` is intentionally omitted – the MiniMax
        # API rejects it.  See the json_mode branch above for how we steer
        # JSON output via the system prompt instead.

        if stream and on_delta is not None:
            return self._text_chat_stream(body, on_delta)
        data = self._request("POST", "/v1/text/chatcompletion_v2", json_body=body)
        return self._parse_chat_response(data)

    def _text_chat_stream(
        self, body: dict[str, Any], on_delta: Callable[[str], None]
    ) -> ChatResponse:
        body = {**body, "stream": True}
        url = self.base_url + "/v1/text/chatcompletion_v2"
        collected: list[str] = []
        completion_id = ""
        completion_model = body.get("model", "MiniMax-M3")
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        try:
            with self._http.stream(
                "POST", url, json=body, timeout=self.timeout
            ) as r:
                if r.status_code == 401:
                    raise AuthenticationError(
                        "401 Unauthorized. Run `mmx auth status` to check region."
                    )
                if r.status_code >= 400:
                    raise APIError(r.status_code, r.read().decode("utf-8", "ignore"))
                for line in r.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        evt = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    choice = (evt.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    token = delta.get("content") or ""
                    if token:
                        collected.append(token)
                        on_delta(token)
                    completion_id = completion_id or evt.get("id", "")
                    completion_model = completion_model or evt.get("model", "")
                    usage = evt.get("usage") or {}
                    prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                    completion_tokens = usage.get("completion_tokens", completion_tokens)
                    total_tokens = usage.get("total_tokens", total_tokens)
        except httpx.HTTPError as exc:
            raise NetworkError(f"Streaming failed: {exc}") from exc
        full = "".join(collected)
        return ChatResponse(
            id=completion_id or f"chatcmpl-{int(time.time() * 1000)}",
            model=completion_model,
            choices=[ChatChoice(0, ChatMessage("assistant", full), "stop")],
            usage=Usage(prompt_tokens, completion_tokens, total_tokens),
        )

    def _parse_chat_response(self, data: dict) -> ChatResponse:
        choices_raw = data.get("choices") or []
        choices: list[ChatChoice] = []
        for c in choices_raw:
            msg = c.get("message") or {}
            choices.append(
                ChatChoice(
                    index=c.get("index", 0),
                    message=ChatMessage(
                        role=msg.get("role", "assistant"),
                        content=msg.get("content", ""),
                    ),
                    finish_reason=c.get("finish_reason"),
                )
            )
        usage_raw = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
        )
        return ChatResponse(
            id=data.get("id", ""),
            model=data.get("model", ""),
            choices=choices,
            usage=usage,
            raw=data,
        )

    # =====================================================================
    # audio (Whisper replacement)
    # =====================================================================
    def audio_transcribe(
        self,
        file: str | Path | BinaryIO,
        *,
        model: str = "MiniMax-ASR-01",
        language: str | None = None,
        response_format: str = "verbose_json",
        timestamp_granularities: Iterable[str] = ("segment",),
    ) -> TranscriptionResult:
        path_obj: Path | None = None
        fh: BinaryIO
        close_after = False
        if isinstance(file, (str, Path)):
            path_obj = Path(file)
            if not path_obj.exists():
                raise ValidationError(f"Audio file not found: {file}")
            if path_obj.stat().st_size > 200 * 1024 * 1024:
                raise FileTooLargeError(
                    413, f"Audio file too large: {path_obj.stat().st_size} bytes"
                )
            fh = path_obj.open("rb")
            close_after = True
        else:
            fh = file  # type: ignore[assignment]

        try:
            files = {"file": (path_obj.name if path_obj else "audio.mp3", fh)}
            data: dict[str, str] = {
                "model": model,
                "response_format": response_format,
            }
            if language:
                data["language"] = language
            for g in timestamp_granularities:
                # The MiniMax endpoint accepts a single value; send the first
                # and append the rest as a comma-list.
                data["timestamp_granularities[]"] = g
            r = self._http.post(
                "/v1/audio/transcriptions",
                files=files,
                data=data,
                timeout=self.UPLOAD_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            raise NetworkError(f"Audio upload failed: {exc}") from exc
        finally:
            if close_after:
                fh.close()
        payload = self._parse(r, "/v1/audio/transcriptions")

        segments: list[TranscriptionSegment] = []
        for s in payload.get("segments", []) or []:
            segments.append(
                TranscriptionSegment(
                    start=float(s.get("start", 0.0)),
                    end=float(s.get("end", 0.0)),
                    text=str(s.get("text", "")),
                )
            )
        return TranscriptionResult(
            language=payload.get("language"),
            duration=payload.get("duration"),
            text=payload.get("text", ""),
            segments=segments,
            raw=payload,
        )

    # =====================================================================
    # image
    # =====================================================================
    def image_generate(
        self,
        prompt: str,
        *,
        model: str = "MiniMax-Image-01",
        n: int = 1,
        aspect_ratio: str = "1:1",
        out_dir: str | Path | None = None,
    ) -> list[ImageResult]:
        if not prompt:
            raise ValidationError("prompt is required")
        body = {
            "model": model,
            "prompt": prompt,
            "n": n,
            "aspect_ratio": aspect_ratio,
        }
        data = self._request("POST", "/v1/image/generation", json_body=body)
        results: list[ImageResult] = []
        urls: list[str] = []
        for item in data.get("data", []) or []:
            url = item.get("url")
            b64 = item.get("b64_json")
            file_id = item.get("file_id", "")
            if url:
                urls.append(url)
            results.append(ImageResult(file_id=file_id, url=url or "", b64=b64, raw=item))
        # Optionally persist a copy in out_dir.
        if out_dir is not None and urls:
            self._download_to_dir(urls, Path(out_dir))
        return results

    # =====================================================================
    # video
    # =====================================================================
    def video_generate(
        self,
        prompt: str,
        *,
        model: str = "MiniMax-Hailuo-2.3",
        out_dir: str | Path | None = None,
        wait: bool = True,
        poll_interval: float = 5.0,
        timeout: float = 1800.0,
    ) -> VideoTask:
        body = {"model": model, "prompt": prompt}
        data = self._request("POST", "/v1/video/generation", json_body=body)
        task_id = data.get("task_id") or data.get("id", "")
        task = VideoTask(task_id=task_id, status="queued", raw=data)
        if not wait:
            return task
        return self._poll_video(task, poll_interval=poll_interval, timeout=timeout, out_dir=out_dir)

    def video_query(self, task_id: str) -> VideoTask:
        data = self._request("GET", f"/v1/video/generation/{task_id}")
        return VideoTask(
            task_id=task_id,
            status=data.get("status", "unknown"),
            file_id=data.get("file_id"),
            url=data.get("url") or (data.get("file") or {}).get("url"),
            raw=data,
        )

    def _poll_video(
        self,
        task: VideoTask,
        poll_interval: float,
        timeout: float,
        out_dir: str | Path | None,
    ) -> VideoTask:
        deadline = time.time() + timeout
        while time.time() < deadline:
            cur = self.video_query(task.task_id)
            if cur.status in {"succeeded", "failed", "cancelled"}:
                if out_dir is not None and cur.url:
                    self._download_to_dir([cur.url], Path(out_dir))
                return cur
            time.sleep(poll_interval)
        raise NetworkError(f"Video task {task.task_id} did not finish within {timeout}s")

    # =====================================================================
    # speech
    # =====================================================================
    def speech_synthesize(
        self,
        text: str,
        *,
        voice: str = "female-shaonv",
        model: str = "MiniMax-Speech-2.8",
        out: str | Path | None = None,
        stream: bool = False,
        audio_format: str = "mp3",
        sample_rate: int = 32000,
        speed: float = 1.0,
        vol: float = 1.0,
        pitch: int = 0,
    ) -> bytes:
        if not text:
            raise ValidationError("text is required")
        body = {
            "model": model,
            "text": text,
            "voice": voice,
            "audio_setting": {
                "format": audio_format,
                "sample_rate": sample_rate,
                "speed": speed,
                "vol": vol,
                "pitch": pitch,
            },
            "stream": stream,
        }
        r = self._http.post(
            "/v1/t2a_v2",
            json=body,
            timeout=self.UPLOAD_TIMEOUT,
        )
        if r.status_code == 401:
            raise AuthenticationError("401 Unauthorized – check API key/region.")
        if r.status_code >= 400:
            try:
                payload = r.json()
                msg = payload.get("base_resp", {}).get("status_msg") or r.text
            except Exception:
                msg = r.text
            raise APIError(r.status_code, msg)
        ctype = r.headers.get("content-type", "")
        if "application/json" in ctype:
            data = r.json()
            audio_hex = (data.get("data") or {}).get("audio") or ""
            if not audio_hex:
                raise APIError(500, "Empty audio in response", data)
            try:
                audio_bytes = bytes.fromhex(audio_hex)
            except ValueError as exc:
                raise APIError(500, f"Bad audio hex: {exc}", data) from exc
        else:
            audio_bytes = r.content
        if out is not None:
            Path(out).write_bytes(audio_bytes)
        return audio_bytes

    # =====================================================================
    # music
    # =====================================================================
    def music_generate(
        self,
        prompt: str,
        *,
        lyrics: str | None = None,
        model: str = "MiniMax-Music-2.6",
        out: str | Path | None = None,
        audio_format: str = "mp3",
        sample_rate: int = 44100,
    ) -> Path:
        if not prompt:
            raise ValidationError("prompt is required")
        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "audio_setting": {"format": audio_format, "sample_rate": sample_rate},
        }
        if lyrics:
            body["lyrics"] = lyrics
        data = self._request("POST", "/v1/music_generation", json_body=body)
        audio_hex = (data.get("data") or {}).get("audio") or ""
        if not audio_hex:
            raise APIError(500, "Empty music payload", data)
        try:
            audio_bytes = bytes.fromhex(audio_hex)
        except ValueError as exc:
            raise APIError(500, f"Bad music hex: {exc}", data) from exc
        if out is None:
            out = self.config.ensure_output_dir() / f"music-{int(time.time())}.{audio_format}"
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(audio_bytes)
        return out_path

    # =====================================================================
    # vision
    # =====================================================================
    def vision_describe(
        self,
        source: str | Path | bytes,
        prompt: str = "Describe this image in detail.",
        *,
        model: str = "MiniMax-Vision-01",
    ) -> ChatResponse:
        """Describe an image from a local path, a URL, a file id, or raw bytes."""
        if isinstance(source, (str, Path)):
            source_str = str(source)
            if source_str.startswith("http://") or source_str.startswith("https://"):
                image_payload = {"type": "url", "url": source_str}
            elif Path(source_str).exists():
                # Base64-encode small files; for large files we would upload
                # to the file API first and pass file_id.
                b = Path(source_str).read_bytes()
                if len(b) > 5 * 1024 * 1024:
                    raise FileTooLargeError(
                        413,
                        "Local images >5MB must be uploaded via files API first; "
                        "use `mmx vision describe --file-id <id>` workflow.",
                    )
                import base64
                image_payload = {
                    "type": "base64",
                    "data": base64.b64encode(b).decode("ascii"),
                }
            else:
                # Treat as file_id.
                image_payload = {"type": "file_id", "file_id": source_str}
        elif isinstance(source, bytes):
            import base64
            if len(source) > 5 * 1024 * 1024:
                raise FileTooLargeError(413, "Image bytes too large")
            image_payload = {
                "type": "base64",
                "data": base64.b64encode(source).decode("ascii"),
            }
        else:
            raise ValidationError("Unsupported image source type")

        body = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": image_payload},
                    ],
                }
            ],
        }
        data = self._request("POST", "/v1/vision/text-understanding", json_body=body)
        return self._parse_chat_response(data)

    # =====================================================================
    # search
    # =====================================================================
    def search_query(self, query: str, *, top_k: int = 5) -> list[dict]:
        if not query:
            raise ValidationError("query is required")
        data = self._request(
            "POST",
            "/v1/search/query",
            json_body={"query": query, "top_k": top_k},
        )
        return list(data.get("results") or data.get("data") or [])

    # =====================================================================
    # quota
    # =====================================================================
    def quota(self) -> dict:
        return self._request("GET", "/v1/dashboard/billing/credit_grants")

    # =====================================================================
    # helpers
    # =====================================================================
    def _download_to_dir(self, urls: list[str], out_dir: Path) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        for i, url in enumerate(urls):
            try:
                with self._http.stream("GET", url, timeout=self.timeout) as r:
                    r.raise_for_status()
                    ext = ".bin"
                    ctype = r.headers.get("content-type", "")
                    if "image/png" in ctype:
                        ext = ".png"
                    elif "image/jpeg" in ctype:
                        ext = ".jpg"
                    elif "video/mp4" in ctype:
                        ext = ".mp4"
                    target = out_dir / f"asset-{int(time.time())}-{i}{ext}"
                    with target.open("wb") as f:
                        for chunk in r.iter_bytes():
                            f.write(chunk)
                    saved.append(target)
            except httpx.HTTPError as exc:
                raise NetworkError(f"Failed to download {url}: {exc}") from exc
        return saved
