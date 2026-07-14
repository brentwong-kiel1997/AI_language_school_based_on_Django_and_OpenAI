"""Ark / Seed ASR configuration helpers."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

DEFAULT_ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/plan/v3"
DEFAULT_ARK_MODEL = "doubao-seed-2.0-lite"
DEFAULT_ARK_TIMEOUT_SECONDS = 300.0
MIN_ARK_TIMEOUT_SECONDS = 1.0
DEFAULT_ARK_MAX_TOKENS = 32768
MIN_ARK_MAX_TOKENS = 256
MAX_ARK_MAX_TOKENS = 131072

DEFAULT_SEED_ASR_WS_URL = "wss://openspeech.bytedance.com/api/v3/plan/sauc/bigmodel_nostream"
DEFAULT_SEED_ASR_RESOURCE_ID = "volc.seedasr.sauc.duration"
DEFAULT_SEED_ASR_SEGMENT_MS = 200
DEFAULT_SEED_ASR_TIMEOUT_SECONDS = 120


def load_dotenv(paths: Optional[Iterable[Path]] = None) -> None:
    """Load .env files with setdefault (never override existing OS env)."""
    if paths is None:
        cwd = Path.cwd()
        paths = (
            cwd / ".env",
            cwd.parent / ".env",
            Path(__file__).resolve().parents[1] / ".env",
            Path(__file__).resolve().parents[1] / "bals" / ".env",
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


def env_float(name: str, default: float, minimum: float) -> float:
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


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    return value if minimum <= value <= maximum else default


@dataclass
class Config:
    api_key: str = ""
    base_url: str = DEFAULT_ARK_BASE_URL
    model: str = DEFAULT_ARK_MODEL
    timeout_seconds: float = DEFAULT_ARK_TIMEOUT_SECONDS
    max_tokens: int = DEFAULT_ARK_MAX_TOKENS
    seed_asr_ws_url: str = DEFAULT_SEED_ASR_WS_URL
    seed_asr_resource_id: str = DEFAULT_SEED_ASR_RESOURCE_ID
    seed_asr_segment_ms: int = DEFAULT_SEED_ASR_SEGMENT_MS
    seed_asr_timeout_seconds: int = DEFAULT_SEED_ASR_TIMEOUT_SECONDS

    @classmethod
    def load(cls) -> "Config":
        return cls(
            api_key=os.environ.get("ARK_API_KEY", ""),
            base_url=os.environ.get("ARK_BASE_URL", DEFAULT_ARK_BASE_URL),
            model=os.environ.get("ARK_MODEL", DEFAULT_ARK_MODEL),
            timeout_seconds=env_float(
                "ARK_TIMEOUT_SECONDS",
                DEFAULT_ARK_TIMEOUT_SECONDS,
                MIN_ARK_TIMEOUT_SECONDS,
            ),
            max_tokens=env_int(
                "ARK_MAX_TOKENS",
                DEFAULT_ARK_MAX_TOKENS,
                MIN_ARK_MAX_TOKENS,
                MAX_ARK_MAX_TOKENS,
            ),
            seed_asr_ws_url=os.environ.get("SEED_ASR_WS_URL", DEFAULT_SEED_ASR_WS_URL),
            seed_asr_resource_id=os.environ.get(
                "SEED_ASR_RESOURCE_ID", DEFAULT_SEED_ASR_RESOURCE_ID
            ),
            seed_asr_segment_ms=env_int(
                "SEED_ASR_SEGMENT_MS", DEFAULT_SEED_ASR_SEGMENT_MS, 100, 1000
            ),
            seed_asr_timeout_seconds=env_int(
                "SEED_ASR_TIMEOUT_SECONDS",
                DEFAULT_SEED_ASR_TIMEOUT_SECONDS,
                1,
                3600,
            ),
        )

    def redacted(self) -> dict:
        data = {
            "api_key": "***" if self.api_key else None,
            "base_url": self.base_url,
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "max_tokens": self.max_tokens,
            "seed_asr_ws_url": self.seed_asr_ws_url,
            "seed_asr_resource_id": self.seed_asr_resource_id,
            "seed_asr_segment_ms": self.seed_asr_segment_ms,
            "seed_asr_timeout_seconds": self.seed_asr_timeout_seconds,
        }
        return data
