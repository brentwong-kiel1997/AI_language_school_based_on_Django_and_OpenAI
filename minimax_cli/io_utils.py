import base64
import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

_HEX_RE = re.compile(r"^[0-9a-fA-F]*$")


def timestamp_name(prefix: str, ext: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H-%M-%S")
    return f"{prefix}_{stamp}.{ext.lstrip('.')}"


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def hex_to_bytes(value: str) -> bytes:
    if not _HEX_RE.fullmatch(value or ""):
        raise ValueError("API returned invalid audio data (not valid hex)")
    if len(value) % 2:
        raise ValueError("API returned truncated audio data (odd-length hex)")
    return bytes.fromhex(value)


def write_bytes(path: Path, data: bytes) -> Path:
    ensure_parent(path)
    path.write_bytes(data)
    return path.resolve()


def write_hex_audio(path: Path, audio_hex: str) -> Path:
    return write_bytes(path, hex_to_bytes(audio_hex))


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https")


def local_image_to_data_uri(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    ext = path.suffix.lower()
    mime = IMAGE_MIME.get(ext) or mimetypes.guess_type(str(path))[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def resolve_image_input(image: str, *, fetched_bytes: Optional[bytes] = None, content_type: Optional[str] = None) -> str:
    if image.startswith("data:"):
        return image
    if is_url(image):
        if fetched_bytes is None:
            raise ValueError("URL image requires downloaded bytes")
        mime = (content_type or "image/jpeg").split(";")[0].strip() or "image/jpeg"
        encoded = base64.b64encode(fetched_bytes).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    return local_image_to_data_uri(Path(image).expanduser())


def file_to_base64(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return base64.b64encode(path.read_bytes()).decode("ascii")
