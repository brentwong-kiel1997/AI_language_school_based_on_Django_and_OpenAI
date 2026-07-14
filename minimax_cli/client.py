import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import httpx

from .config import Config
from .io_utils import (
    file_to_base64,
    hex_to_bytes,
    resolve_image_input,
    write_bytes,
    write_hex_audio,
)

class MiniMaxError(Exception):
    pass


class AuthenticationError(MiniMaxError):
    pass


class APIError(MiniMaxError):
    pass


class NetworkError(MiniMaxError):
    pass


class ValidationError(MiniMaxError):
    pass


class QuotaExceededError(APIError):
    pass


class TaskTimeoutError(MiniMaxError):
    pass


@dataclass
class ChatResponse:
    text: str
    raw: Dict[str, Any]
    usage: Any = None
    model: Optional[str] = None
    choices: Any = None

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)


@dataclass
class MediaResult:
    path: Optional[str] = None
    paths: Optional[List[str]] = None
    raw: Optional[Dict[str, Any]] = None
    text: Optional[str] = None
    task_id: Optional[str] = None
    download_url: Optional[str] = None
    size: Optional[int] = None
    audio: Optional[bytes] = None


class MiniMaxClient:
    def __init__(
        self,
        config: Optional[Config] = None,
        *,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        quota_endpoint: Optional[str] = None,
        search_endpoint: Optional[str] = None,
        vision_endpoint: Optional[str] = None,
        transport=None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.config = config or Config.load()
        self.base_url = (base_url or self.config.base_url).rstrip("/")
        self.quota_endpoint = quota_endpoint or self.config.quota_endpoint
        self.search_endpoint = search_endpoint or self.config.search_endpoint
        self.vision_endpoint = vision_endpoint or self.config.vision_endpoint
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout or self.config.timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MiniMaxClient":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def _headers(self, *, json_body: bool = True) -> Dict[str, str]:
        if not self.config.api_key:
            raise AuthenticationError("MINIMAX_API_KEY is not configured")
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code in (401, 403):
            raise AuthenticationError(response.text)
        if response.status_code == 429:
            raise QuotaExceededError(response.text)
        if response.status_code >= 400:
            raise APIError(response.text)

    def _ensure_base_resp(self, payload: Dict[str, Any]) -> None:
        base = payload.get("base_resp") or {}
        code = base.get("status_code", 0)
        if code not in (0, None):
            raise APIError(base.get("status_msg") or f"API status_code={code}")

    def _request(self, method: str, path: str, *, json_body: bool = True, **kwargs) -> httpx.Response:
        try:
            response = self._client.request(method, path, headers=self._headers(json_body=json_body), **kwargs)
        except httpx.HTTPError as exc:
            raise NetworkError(str(exc)) from exc
        self._raise_for_status(response)
        return response

    def _request_json(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        response = self._request(method, path, **kwargs)
        try:
            payload = response.json()
        except (ValueError, TypeError) as exc:
            raise APIError("Invalid JSON response") from exc
        if isinstance(payload, dict):
            self._ensure_base_resp(payload)
        return payload

    def _request_bytes(self, method: str, path: str, **kwargs) -> bytes:
        return self._request(method, path, **kwargs).content

    def _download(self, url: str, out_path: Union[str, Path]) -> MediaResult:
        path = Path(out_path).expanduser()
        try:
            response = self._client.get(url)
        except httpx.HTTPError as exc:
            raise NetworkError(str(exc)) from exc
        self._raise_for_status(response)
        write_bytes(path, response.content)
        return MediaResult(path=str(path.resolve()), size=len(response.content), download_url=url)

    def upload_file(self, file_path: Union[str, Path], purpose: str = "retrieval") -> Dict[str, Any]:
        path = Path(file_path).expanduser()
        if not path.exists():
            raise ValidationError(f"File not found: {path}")
        with path.open("rb") as handle:
            files = {"file": (path.name, handle)}
            data = {"purpose": purpose}
            return self._request_json("POST", "/v1/files", json_body=False, files=files, data=data)

    def retrieve_file(self, file_id: str) -> Dict[str, Any]:
        return self._request_json("GET", f"/v1/files/retrieve?file_id={file_id}")

    def list_files(self) -> Dict[str, Any]:
        return self._request_json("GET", "/v1/files/list")

    def delete_file(self, file_id: Union[str, int]) -> Dict[str, Any]:
        return self._request_json("POST", "/v1/files/delete", json={"file_id": int(file_id)})

    @staticmethod
    def _response(payload: Dict[str, Any], text: str = "") -> ChatResponse:
        choices = payload.get("choices") or []
        if not text and choices:
            item = choices[0]
            message = item.get("message", {}) or {}
            text = message.get("content", item.get("text", "")) or ""
        return ChatResponse(text, payload, payload.get("usage"), payload.get("model"), choices)

    def text_chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
        stream: bool = False,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> ChatResponse:
        if not isinstance(messages, list) or not messages:
            raise ValidationError("messages must be non-empty list")
        outgoing = list(messages)
        if json_mode:
            outgoing.insert(0, {"role": "system", "content": "Respond with valid JSON only. Do not include markdown fences."})
        body = {
            "model": model or self.config.text_model,
            "messages": outgoing,
            "temperature": temperature,
            "stream": stream,
            "max_tokens": self.config.max_tokens if max_tokens is None else max_tokens,
        }
        response = self._request("POST", "/v1/text/chatcompletion_v2", json=body)
        if not stream:
            try:
                return self._response(response.json())
            except (ValueError, TypeError) as exc:
                raise APIError("Invalid JSON response") from exc
        text = ""
        events: List[Dict[str, Any]] = []
        for line in response.iter_lines():
            if isinstance(line, bytes):
                line = line.decode("utf-8", "replace")
            if not line.startswith("data:"):
                continue
            value = line[5:].strip()
            if not value or value == "[DONE]":
                continue
            try:
                event = json.loads(value)
            except ValueError:
                continue
            events.append(event)
            choices = event.get("choices") or [{}]
            delta = choices[0].get("delta", {}).get("content", "") or event.get("delta", "") or event.get("content", "")
            if delta:
                text += delta
                if on_delta:
                    on_delta(delta)
        return self._response(events[-1] if events else {}, text)

    def search_query(self, query: str, model: Optional[str] = None) -> Dict[str, Any]:
        if not query:
            raise ValidationError("query must not be empty")
        body: Dict[str, Any] = {"query": query}
        if model:
            body["model"] = model
        return self._request_json("POST", self.search_endpoint, json=body)

    def quota(self) -> Dict[str, Any]:
        return self._request_json("GET", self.quota_endpoint)

    def speech_synthesize(
        self,
        text: str,
        *,
        model: Optional[str] = None,
        voice_id: str = "English_expressive_narrator",
        speed: Optional[float] = None,
        volume: Optional[float] = None,
        pitch: Optional[float] = None,
        audio_format: str = "mp3",
        sample_rate: int = 32000,
        bitrate: int = 128000,
        channel: int = 1,
        language_boost: Optional[str] = None,
        subtitle_enable: bool = False,
        stream: bool = False,
        out: Optional[Union[str, Path]] = None,
        on_chunk: Optional[Callable[[bytes], None]] = None,
    ) -> MediaResult:
        if not text:
            raise ValidationError("text is required")
        voice_setting: Dict[str, Any] = {"voice_id": voice_id}
        if speed is not None:
            voice_setting["speed"] = speed
        if volume is not None:
            voice_setting["vol"] = volume
        if pitch is not None:
            voice_setting["pitch"] = pitch
        body: Dict[str, Any] = {
            "model": model or self.config.speech_model,
            "text": text,
            "stream": stream,
            "voice_setting": voice_setting,
            "audio_setting": {
                "format": audio_format,
                "sample_rate": sample_rate,
                "bitrate": bitrate,
                "channel": channel,
            },
            "output_format": "hex",
            "subtitle_enable": subtitle_enable,
        }
        if language_boost:
            body["language_boost"] = language_boost

        if stream:
            response = self._request("POST", "/v1/t2a_v2", json=body)
            audio_parts: List[bytes] = []
            last_payload: Dict[str, Any] = {}
            for line in response.iter_lines():
                if isinstance(line, bytes):
                    line = line.decode("utf-8", "replace")
                if not line.startswith("data:"):
                    continue
                value = line[5:].strip()
                if not value or value == "[DONE]":
                    continue
                try:
                    event = json.loads(value)
                except ValueError:
                    continue
                last_payload = event
                if isinstance(event, dict):
                    self._ensure_base_resp(event)
                audio_hex = ((event.get("data") or {}).get("audio")) or ""
                if audio_hex:
                    chunk = hex_to_bytes(audio_hex)
                    audio_parts.append(chunk)
                    if on_chunk:
                        on_chunk(chunk)
            audio = b"".join(audio_parts)
            path = None
            if out:
                path = str(write_bytes(Path(out).expanduser(), audio))
            return MediaResult(path=path, raw=last_payload, audio=audio, size=len(audio))

        payload = self._request_json("POST", "/v1/t2a_v2", json=body)
        audio_hex = ((payload.get("data") or {}).get("audio")) or ""
        if not audio_hex:
            raise APIError("API response missing audio data")
        audio = hex_to_bytes(audio_hex)
        path = None
        if out:
            path = str(write_hex_audio(Path(out).expanduser(), audio_hex))
        return MediaResult(path=path, raw=payload, audio=audio, size=len(audio))

    def speech_voices(self, language: Optional[str] = None) -> List[Dict[str, Any]]:
        payload = self._request_json("POST", "/v1/get_voice", json={"voice_type": "system"})
        voices = list(payload.get("system_voice") or [])
        if not language:
            return voices
        needle = language.lower()
        filtered = []
        for voice in voices:
            blob = " ".join(
                [
                    str(voice.get("voice_id", "")),
                    str(voice.get("voice_name", "")),
                    " ".join(voice.get("description") or []),
                ]
            ).lower()
            if needle in blob:
                filtered.append(voice)
        return filtered

    def image_generate(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        n: int = 1,
        aspect_ratio: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        seed: Optional[int] = None,
        prompt_optimizer: Optional[bool] = None,
        response_format: str = "url",
        out: Optional[Union[str, Path]] = None,
        out_dir: Optional[Union[str, Path]] = None,
    ) -> MediaResult:
        if not prompt:
            raise ValidationError("prompt is required")
        if (width is None) ^ (height is None):
            raise ValidationError("Both width and height must be provided")
        if width is not None and height is not None:
            for name, val in (("width", width), ("height", height)):
                if val < 512 or val > 2048:
                    raise ValidationError(f"{name} must be between 512 and 2048")
                if val % 8:
                    raise ValidationError(f"{name} must be a multiple of 8")
        body: Dict[str, Any] = {
            "model": model or self.config.image_model,
            "prompt": prompt,
            "n": n,
            "response_format": response_format,
        }
        if width is not None and height is not None:
            body["width"] = width
            body["height"] = height
        elif aspect_ratio:
            body["aspect_ratio"] = aspect_ratio
        if seed is not None:
            body["seed"] = seed
        if prompt_optimizer is not None:
            body["prompt_optimizer"] = prompt_optimizer

        payload = self._request_json("POST", "/v1/image_generation", json=body)
        data = payload.get("data") or {}
        saved: List[str] = []
        directory = Path(out_dir or self.config.output_dir or ".").expanduser()
        if out and n > 1:
            raise ValidationError("Cannot use out with multiple images; use out_dir")

        if response_format == "base64":
            images = data.get("image_base64") or []
            if out:
                import base64

                dest = Path(out).expanduser()
                write_bytes(dest, base64.b64decode(images[0]))
                saved.append(str(dest.resolve()))
            else:
                import base64

                for idx, image in enumerate(images, start=1):
                    dest = directory / f"image_{idx:03d}.jpg"
                    write_bytes(dest, base64.b64decode(image))
                    saved.append(str(dest.resolve()))
        else:
            urls = data.get("image_urls") or []
            if out:
                result = self._download(urls[0], out)
                saved.append(result.path or "")
            else:
                for idx, url in enumerate(urls, start=1):
                    dest = directory / f"image_{idx:03d}.jpg"
                    result = self._download(url, dest)
                    saved.append(result.path or "")
        return MediaResult(path=saved[0] if len(saved) == 1 else None, paths=saved, raw=payload)

    def _image_to_data_uri(self, image: str) -> str:
        if image.startswith("data:"):
            return image
        if image.startswith("http://") or image.startswith("https://"):
            try:
                response = self._client.get(image)
            except httpx.HTTPError as exc:
                raise NetworkError(str(exc)) from exc
            self._raise_for_status(response)
            return resolve_image_input(
                image,
                fetched_bytes=response.content,
                content_type=response.headers.get("content-type"),
            )
        return resolve_image_input(image)

    def vision_describe(
        self,
        *,
        image: Optional[str] = None,
        file_id: Optional[str] = None,
        prompt: Optional[str] = None,
        model: Optional[str] = None,
    ) -> MediaResult:
        if bool(image) == bool(file_id):
            raise ValidationError("Provide exactly one of image or file_id")
        body: Dict[str, Any] = {"prompt": prompt or "Describe the image."}
        if model:
            body["model"] = model
        if file_id:
            body["file_id"] = file_id
        else:
            body["image_url"] = self._image_to_data_uri(image or "")
        payload = self._request_json("POST", self.vision_endpoint, json=body)
        content = payload.get("content") or payload.get("text") or ""
        if not content and isinstance(payload.get("data"), dict):
            content = payload["data"].get("content") or payload["data"].get("text") or ""
        return MediaResult(text=content, raw=payload)

    def video_generate(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        first_frame_image: Optional[str] = None,
        last_frame_image: Optional[str] = None,
        subject_reference: Optional[List[Dict[str, Any]]] = None,
        callback_url: Optional[str] = None,
        async_mode: bool = False,
        poll_interval: Optional[float] = None,
        timeout: Optional[float] = None,
        download: Optional[Union[str, Path]] = None,
    ) -> MediaResult:
        if not prompt:
            raise ValidationError("prompt is required")
        if last_frame_image and not first_frame_image:
            raise ValidationError("last_frame_image requires first_frame_image")
        if last_frame_image and subject_reference:
            raise ValidationError("last_frame_image and subject_reference cannot be used together")
        if model is None:
            if last_frame_image:
                model = "MiniMax-Hailuo-02"
            elif subject_reference:
                model = "S2V-01"
            else:
                model = self.config.video_model
        if model == "MiniMax-Hailuo-2.3-Fast" and not first_frame_image:
            raise ValidationError("MiniMax-Hailuo-2.3-Fast requires first_frame_image")
        body: Dict[str, Any] = {"model": model, "prompt": prompt}
        if first_frame_image:
            body["first_frame_image"] = self._image_to_data_uri(first_frame_image)
        if last_frame_image:
            body["last_frame_image"] = self._image_to_data_uri(last_frame_image)
        if subject_reference:
            body["subject_reference"] = subject_reference
        if callback_url:
            body["callback_url"] = callback_url
        payload = self._request_json("POST", "/v1/video_generation", json=body)
        task_id = payload.get("task_id")
        if not task_id:
            raise APIError("API response missing task_id")
        if async_mode:
            return MediaResult(task_id=task_id, raw=payload)
        task = self.video_poll_task(
            task_id,
            poll_interval=poll_interval,
            timeout=timeout,
        )
        result = MediaResult(task_id=task_id, raw=task)
        file_id = task.get("file_id")
        if download and file_id:
            downloaded = self.video_download(str(file_id), download)
            result.path = downloaded.path
            result.download_url = downloaded.download_url
            result.size = downloaded.size
        return result

    def video_get_task(self, task_id: str) -> Dict[str, Any]:
        if not task_id:
            raise ValidationError("task_id is required")
        return self._request_json("GET", f"/v1/query/video_generation?task_id={task_id}")

    def video_poll_task(
        self,
        task_id: str,
        *,
        poll_interval: Optional[float] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        interval = poll_interval if poll_interval is not None else self.config.poll_interval_seconds
        deadline = time.monotonic() + (timeout if timeout is not None else self.config.video_timeout_seconds)
        while True:
            task = self.video_get_task(task_id)
            status = task.get("status")
            if status == "Success":
                return task
            if status == "Failed":
                base = task.get("base_resp") or {}
                raise APIError(base.get("status_msg") or f"Video task failed: {task_id}")
            if time.monotonic() >= deadline:
                raise TaskTimeoutError(f"Polling timed out for task {task_id}")
            self._sleep(interval)

    def video_download(self, file_id: str, out: Union[str, Path]) -> MediaResult:
        if not file_id:
            raise ValidationError("file_id is required")
        info = self.retrieve_file(file_id)
        download_url = ((info.get("file") or {}).get("download_url")) or ""
        if not download_url:
            raise APIError("No download URL available for this file")
        return self._download(download_url, out)

    def music_generate(
        self,
        *,
        prompt: Optional[str] = None,
        lyrics: Optional[str] = None,
        model: Optional[str] = None,
        lyrics_optimizer: bool = False,
        instrumental: bool = False,
        stream: bool = False,
        out: Optional[Union[str, Path]] = None,
        audio_format: str = "mp3",
        sample_rate: int = 44100,
        bitrate: int = 256000,
        channel: Optional[int] = None,
        seed: Optional[int] = None,
        on_chunk: Optional[Callable[[bytes], None]] = None,
        **structured: Any,
    ) -> MediaResult:
        if instrumental and lyrics:
            raise ValidationError("Cannot use instrumental with lyrics")
        if lyrics_optimizer and (lyrics or instrumental):
            raise ValidationError("Cannot use lyrics_optimizer with lyrics or instrumental")
        if not prompt and not lyrics and not instrumental and not lyrics_optimizer:
            raise ValidationError("At least one of prompt, lyrics, instrumental, or lyrics_optimizer is required")
        if not instrumental and not lyrics_optimizer and not (lyrics or "").strip():
            raise ValidationError("lyrics is required unless instrumental or lyrics_optimizer is set")

        structured_parts = []
        mapping = {
            "vocals": "Vocals",
            "genre": "Genre",
            "mood": "Mood",
            "instruments": "Instruments",
            "tempo": "Tempo",
            "bpm": "BPM",
            "key": "Key",
            "avoid": "Avoid",
            "use_case": "Use case",
            "structure": "Structure",
            "references": "References",
            "extra": "Extra",
        }
        for key, label in mapping.items():
            if structured.get(key) is not None:
                structured_parts.append(f"{label}: {structured[key]}")
        target_lyrics = lyrics
        target_prompt = prompt
        if instrumental or not target_lyrics or target_lyrics in ("无歌词", "no lyrics"):
            target_lyrics = "[intro] [outro]"
            structured_parts.append("Style: instrumental, no vocals, pure music")
        if structured_parts:
            joined = ". ".join(structured_parts)
            target_prompt = f"{target_prompt}. {joined}" if target_prompt else joined

        body: Dict[str, Any] = {
            "model": model or self.config.music_model,
            "prompt": target_prompt,
            "lyrics": target_lyrics,
            "is_instrumental": instrumental,
            "lyrics_optimizer": lyrics_optimizer,
            "audio_setting": {
                "format": audio_format,
                "sample_rate": sample_rate,
                "bitrate": bitrate,
            },
            "output_format": "hex",
            "stream": stream,
        }
        if channel is not None:
            body["audio_setting"]["channel"] = channel
        if seed is not None:
            body["seed"] = seed

        if stream:
            response = self._request("POST", "/v1/music_generation", json=body)
            chunks: List[bytes] = []
            for chunk in response.iter_bytes():
                if not chunk:
                    continue
                chunks.append(chunk)
                if on_chunk:
                    on_chunk(chunk)
            audio = b"".join(chunks)
            path = None
            if out:
                path = str(write_bytes(Path(out).expanduser(), audio))
            return MediaResult(path=path, audio=audio, size=len(audio), raw={"stream": True})

        payload = self._request_json("POST", "/v1/music_generation", json=body)
        audio_hex = ((payload.get("data") or {}).get("audio")) or ""
        audio_url = ((payload.get("data") or {}).get("audio_url")) or ""
        path = None
        audio = None
        if audio_hex:
            audio = hex_to_bytes(audio_hex)
            if out:
                path = str(write_hex_audio(Path(out).expanduser(), audio_hex))
        elif audio_url:
            if out:
                downloaded = self._download(audio_url, out)
                path = downloaded.path
                audio = Path(path).read_bytes() if path else None
        else:
            raise APIError("API response missing audio data")
        return MediaResult(path=path, raw=payload, audio=audio, size=len(audio or b""), download_url=audio_url or None)

    def music_cover(
        self,
        prompt: str,
        *,
        audio_url: Optional[str] = None,
        audio_file: Optional[Union[str, Path]] = None,
        lyrics: Optional[str] = None,
        model: str = "music-cover",
        out: Optional[Union[str, Path]] = None,
        audio_format: str = "mp3",
        sample_rate: int = 44100,
        bitrate: int = 256000,
        channel: Optional[int] = None,
        seed: Optional[int] = None,
        stream: bool = False,
        on_chunk: Optional[Callable[[bytes], None]] = None,
    ) -> MediaResult:
        if not prompt:
            raise ValidationError("prompt is required")
        if bool(audio_url) == bool(audio_file):
            raise ValidationError("Provide exactly one of audio_url or audio_file")
        body: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "lyrics": lyrics,
            "audio_setting": {
                "format": audio_format,
                "sample_rate": sample_rate,
                "bitrate": bitrate,
            },
            "output_format": "hex",
            "stream": stream,
        }
        if channel is not None:
            body["audio_setting"]["channel"] = channel
        if seed is not None:
            body["seed"] = seed
        if audio_url:
            body["audio_url"] = audio_url
        else:
            body["audio_base64"] = file_to_base64(Path(audio_file).expanduser())  # type: ignore[arg-type]

        if stream:
            response = self._request("POST", "/v1/music_generation", json=body)
            chunks: List[bytes] = []
            for chunk in response.iter_bytes():
                if chunk:
                    chunks.append(chunk)
                    if on_chunk:
                        on_chunk(chunk)
            audio = b"".join(chunks)
            path = str(write_bytes(Path(out).expanduser(), audio)) if out else None
            return MediaResult(path=path, audio=audio, size=len(audio), raw={"stream": True})

        payload = self._request_json("POST", "/v1/music_generation", json=body)
        audio_hex = ((payload.get("data") or {}).get("audio")) or ""
        if not audio_hex:
            raise APIError("API response missing audio data")
        audio = hex_to_bytes(audio_hex)
        path = str(write_hex_audio(Path(out).expanduser(), audio_hex)) if out else None
        return MediaResult(path=path, raw=payload, audio=audio, size=len(audio))
