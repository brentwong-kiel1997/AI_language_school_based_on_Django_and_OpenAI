"""Seed ASR 2.0 Agent Plan websocket protocol client."""
from __future__ import annotations
import asyncio, gzip, json, os, struct, uuid, wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import aiohttp

DEFAULT_WS_URL = "wss://openspeech.bytedance.com/api/v3/plan/sauc/bigmodel_nostream"
DEFAULT_RESOURCE_ID = "volc.seedasr.sauc.duration"
CLIENT_FULL_REQUEST, CLIENT_AUDIO_ONLY_REQUEST = 0x1, 0x2
SERVER_FULL_RESPONSE, SERVER_ERROR_RESPONSE = 0x9, 0xF
NO_SEQUENCE, POS_SEQUENCE, NEG_SEQUENCE, NEG_WITH_SEQUENCE = 0, 1, 2, 3
JSON, GZIP = 1, 1

class SeedASRError(RuntimeError):
    """Seed ASR protocol, transport, or service error."""

@dataclass(frozen=True)
class Frame:
    message_type: int
    flags: int
    sequence: int | None
    payload: Any
    error_code: int | None = None

def build_frame(message_type: int, payload: bytes | dict, *, flags: int = NO_SEQUENCE,
                sequence: int | None = None, serialization: int = JSON,
                compression: int = GZIP) -> bytes:
    if isinstance(payload, dict):
        payload = json.dumps(payload, ensure_ascii=False).encode()
    if compression == GZIP:
        payload = gzip.compress(payload)
    header = bytes((0x11, (message_type << 4) | flags,
                    (serialization << 4) | compression, 0))
    seq = b""
    if flags in (POS_SEQUENCE, NEG_SEQUENCE, NEG_WITH_SEQUENCE):
        if sequence is None:
            raise ValueError("A sequence is required by the selected frame flags")
        seq = struct.pack(">i", sequence)
    return header + seq + struct.pack(">I", len(payload)) + payload

def parse_frame(data: bytes) -> Frame:
    if len(data) < 8:
        raise SeedASRError("Seed ASR returned a truncated frame")
    version, words = data[0] >> 4, data[0] & 15
    if version != 1 or words < 1:
        raise SeedASRError("Seed ASR returned an unsupported frame header")
    message_type, flags = data[1] >> 4, data[1] & 15
    serialization, compression = data[2] >> 4, data[2] & 15
    offset, sequence = words * 4, None
    if flags in (POS_SEQUENCE, NEG_SEQUENCE, NEG_WITH_SEQUENCE):
        if len(data) < offset + 4:
            raise SeedASRError("Seed ASR response omitted its sequence")
        sequence = struct.unpack_from(">i", data, offset)[0]; offset += 4
    error_code = None
    if message_type == SERVER_ERROR_RESPONSE:
        if len(data) < offset + 8:
            raise SeedASRError("Seed ASR returned a truncated error frame")
        error_code = struct.unpack_from(">I", data, offset)[0]; offset += 4
    if len(data) < offset + 4:
        raise SeedASRError("Seed ASR response omitted its payload size")
    size = struct.unpack_from(">I", data, offset)[0]; offset += 4
    payload = data[offset:offset + size]
    if len(payload) != size:
        raise SeedASRError("Seed ASR returned a truncated payload")
    if compression == GZIP and payload:
        try: payload = gzip.decompress(payload)
        except (OSError, EOFError) as exc: raise SeedASRError("Seed ASR returned invalid gzip data") from exc
    if serialization == JSON and payload:
        try: payload = json.loads(payload.decode())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise SeedASRError("Seed ASR returned invalid JSON") from exc
    elif not payload: payload = {}
    return Frame(message_type, flags, sequence, payload, error_code)

def _setting_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try: value = int(os.environ.get(name, default))
    except (TypeError, ValueError): return default
    return value if minimum <= value <= maximum else default

def _request_payload(request_id: str, *, language: str | None = None) -> dict:
    audio = {"format": "wav", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1}
    if language:
        audio["language"] = language
    return {"user": {"uid": request_id},
            "audio": audio,
            "request": {"model_name": "bigmodel", "enable_itn": True, "enable_punc": True,
                        "enable_ddc": True, "enable_nonstream": True, "enable_lid": True,
                        "show_utterances": True, "result_type": "full"}}

def _check_frame(frame: Frame) -> None:
    if frame.message_type == SERVER_ERROR_RESPONSE:
        detail = frame.payload
        if isinstance(detail, dict): detail = detail.get("message") or detail.get("error") or detail
        raise SeedASRError(f"Seed ASR error {frame.error_code}: {detail}")
    if frame.message_type != SERVER_FULL_RESPONSE:
        raise SeedASRError(f"Seed ASR returned unexpected frame type 0x{frame.message_type:x}")

async def transcribe_wav_async(wav_path: str | Path, *, api_key: str | None = None,
                               ws_url: str | None = None, resource_id: str | None = None,
                               segment_ms: int | None = None, timeout: int | None = None,
                               language: str | None = None) -> dict:
    api_key = api_key if api_key is not None else os.environ.get("ARK_API_KEY", "")
    if not api_key: raise SeedASRError("ARK_API_KEY is required for Seed ASR")
    ws_url = ws_url or os.environ.get("SEED_ASR_WS_URL", DEFAULT_WS_URL)
    resource_id = resource_id or os.environ.get("SEED_ASR_RESOURCE_ID", DEFAULT_RESOURCE_ID)
    segment_ms = segment_ms or _setting_int("SEED_ASR_SEGMENT_MS", 200, 100, 1000)
    timeout = timeout or _setting_int("SEED_ASR_TIMEOUT_SECONDS", 120, 1, 3600)
    request_id = str(uuid.uuid4())
    headers = {"X-Api-Key": api_key, "X-Api-Resource-Id": resource_id,
               "X-Api-Request-Id": request_id, "X-Api-Connect-Id": request_id, "X-Api-Sequence": "-1"}
    try: wav = wave.open(str(wav_path), "rb")
    except (OSError, wave.Error) as exc: raise SeedASRError(f"Unable to read ASR WAV file: {exc}") from exc
    with wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
            raise SeedASRError("Seed ASR requires a 16 kHz mono pcm_s16le WAV")
        audio_duration = wav.getnframes() / wav.getframerate()
    # The service's WAV decoder needs the RIFF header in the first audio frame.
    wav_bytes = Path(wav_path).read_bytes()
    chunk_size = max(1, 16000 * 2 * segment_ms // 1000)
    chunks = [wav_bytes[offset:offset + chunk_size]
              for offset in range(0, len(wav_bytes), chunk_size)] or [b""]
    result = {}
    try:
        # Audio is streamed in real time, so a fixed total timeout cannot work
        # for recordings longer than that timeout. Use it as connection and
        # post-audio processing allowance instead.
        client_timeout = aiohttp.ClientTimeout(
            total=None, connect=timeout, sock_connect=timeout, sock_read=None
        )
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.ws_connect(ws_url, headers=headers, heartbeat=30) as ws:
                payload_language = language if "bigmodel_nostream" in ws_url and language else None
                await ws.send_bytes(build_frame(
                    CLIENT_FULL_REQUEST,
                    _request_payload(request_id, language=payload_language),
                    flags=POS_SEQUENCE,
                    sequence=1,
                ))
                msg = await ws.receive(timeout=timeout)
                if msg.type != aiohttp.WSMsgType.BINARY: raise SeedASRError(f"Seed ASR initialization failed: {msg.type.name}")
                frame = parse_frame(msg.data); _check_frame(frame)
                if isinstance(frame.payload, dict) and isinstance(frame.payload.get("result"), dict): result = frame.payload["result"]

                async def send_audio() -> None:
                    for index, chunk in enumerate(chunks, start=2):
                        final = index == len(chunks) + 1
                        await ws.send_bytes(build_frame(
                            CLIENT_AUDIO_ONLY_REQUEST, chunk,
                            flags=NEG_WITH_SEQUENCE if final else POS_SEQUENCE,
                            sequence=-index if final else index, serialization=0,
                        ))
                        if not final:
                            await asyncio.sleep(segment_ms / 1000)

                async def receive_results() -> dict:
                    latest = result
                    while True:
                        msg = await ws.receive()
                        if msg.type != aiohttp.WSMsgType.BINARY:
                            raise SeedASRError(f"Seed ASR stream ended unexpectedly: {msg.type.name}")
                        frame = parse_frame(msg.data); _check_frame(frame)
                        if isinstance(frame.payload, dict) and isinstance(frame.payload.get("result"), dict):
                            latest = frame.payload["result"]
                        if (frame.flags in (NEG_SEQUENCE, NEG_WITH_SEQUENCE)
                                or (frame.sequence is not None and frame.sequence < 0)):
                            return latest

                sender = asyncio.create_task(send_audio(), name="seed-asr-sender")
                receiver = asyncio.create_task(receive_results(), name="seed-asr-receiver")
                try:
                    async with asyncio.timeout(audio_duration + timeout):
                        done, _ = await asyncio.wait(
                            (sender, receiver), return_when=asyncio.FIRST_COMPLETED
                        )
                        if sender in done:
                            sender.result()
                        if receiver in done:
                            result = receiver.result()
                        else:
                            result = await receiver
                finally:
                    for task in (sender, receiver):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(sender, receiver, return_exceptions=True)
    except asyncio.TimeoutError as exc: raise SeedASRError(f"Seed ASR exceeded the audio duration plus {timeout} seconds of allowance") from exc
    except aiohttp.ClientError as exc: raise SeedASRError(f"Seed ASR websocket connection failed: {exc}") from exc
    return result

def transcribe_wav(wav_path: str | Path, *, language: str | None = None, **kwargs) -> dict:
    try: asyncio.get_running_loop()
    except RuntimeError: return asyncio.run(transcribe_wav_async(wav_path, language=language, **kwargs))
    raise RuntimeError("transcribe_wav() cannot run inside an active event loop; await transcribe_wav_async() instead")
