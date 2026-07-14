import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Dict, Optional

REGION_BASE_URLS = {
    "cn": "https://api.minimaxi.com",
    "global": "https://api.minimax.io",
}

_INT_FIELDS = {"context_window_tokens", "max_tokens"}
_FLOAT_FIELDS = {"timeout_seconds", "video_timeout_seconds", "poll_interval_seconds"}


@dataclass
class Config:
    api_key: Optional[str] = None
    region: str = "cn"
    base_url: str = REGION_BASE_URLS["cn"]
    text_model: str = "MiniMax-M3"
    image_model: str = "image-01"
    speech_model: str = "speech-2.8-hd"
    video_model: str = "MiniMax-Hailuo-2.3"
    music_model: str = "music-2.6"
    vision_model: str = "MiniMax-VL"
    context_window_tokens: int = 1_000_000
    max_tokens: int = 131072
    timeout_seconds: float = 120
    video_timeout_seconds: float = 600
    poll_interval_seconds: float = 5
    output_dir: str = "."
    quota_endpoint: str = "/v1/coding_plan/quota"
    search_endpoint: str = "/v1/coding_plan/search"
    vision_endpoint: str = "/v1/coding_plan/vlm"

    @classmethod
    def path(cls) -> Path:
        return Path(os.getenv("MINIMAX_CONFIG_DIR", str(Path.home() / ".mmx"))) / "config.json"

    @classmethod
    def known_keys(cls) -> set[str]:
        return {f.name for f in fields(cls)}

    @classmethod
    def load(cls) -> "Config":
        data: Dict[str, Any] = {}
        if cls.path().exists():
            try:
                data = json.loads(cls.path().read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError("Invalid MiniMax config file") from exc

        defaults = cls()
        values: Dict[str, Any] = {f.name: data.get(f.name, getattr(defaults, f.name)) for f in fields(cls)}

        env_map = {
            "api_key": "MINIMAX_API_KEY",
            "region": "MINIMAX_REGION",
            "base_url": "MINIMAX_BASE_URL",
            "text_model": "MINIMAX_TEXT_MODEL",
            "image_model": "MINIMAX_IMAGE_MODEL",
            "speech_model": "MINIMAX_SPEECH_MODEL",
            "video_model": "MINIMAX_VIDEO_MODEL",
            "music_model": "MINIMAX_MUSIC_MODEL",
            "vision_model": "MINIMAX_VISION_MODEL",
            "context_window_tokens": "MINIMAX_CONTEXT_WINDOW_TOKENS",
            "max_tokens": "MINIMAX_MAX_TOKENS",
            "timeout_seconds": "MINIMAX_TIMEOUT_SECONDS",
            "video_timeout_seconds": "MINIMAX_VIDEO_TIMEOUT_SECONDS",
            "poll_interval_seconds": "MINIMAX_POLL_INTERVAL_SECONDS",
            "output_dir": "MINIMAX_OUTPUT_DIR",
            "quota_endpoint": "MINIMAX_QUOTA_ENDPOINT",
            "search_endpoint": "MINIMAX_SEARCH_ENDPOINT",
            "vision_endpoint": "MINIMAX_VISION_ENDPOINT",
        }
        for field, name in env_map.items():
            if name in os.environ:
                values[field] = os.environ[name]

        region = str(values["region"] or "cn").lower()
        if region not in REGION_BASE_URLS:
            raise ValueError("region must be 'cn' or 'global'")
        values["region"] = region

        # Env/base_url wins; otherwise derive from region when file still has mismatched default.
        if "MINIMAX_BASE_URL" not in os.environ:
            file_base = data.get("base_url")
            if not file_base or file_base in REGION_BASE_URLS.values():
                values["base_url"] = REGION_BASE_URLS[region]

        for key in _INT_FIELDS:
            values[key] = int(values[key])
        for key in _FLOAT_FIELDS:
            values[key] = float(values[key])

        return cls(**values)

    def save(self) -> None:
        path = self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def set_value(self, key: str, value: str) -> None:
        if key not in self.known_keys():
            raise ValueError(f"unknown config key: {key}")
        if key == "region":
            region = value.lower()
            if region not in REGION_BASE_URLS:
                raise ValueError("region must be 'cn' or 'global'")
            self.region = region
            self.base_url = REGION_BASE_URLS[region]
            return
        if key in _INT_FIELDS:
            setattr(self, key, int(value))
        elif key in _FLOAT_FIELDS:
            setattr(self, key, float(value))
        else:
            setattr(self, key, value)
        if key == "base_url":
            for region, url in REGION_BASE_URLS.items():
                if value.rstrip("/") == url:
                    self.region = region
                    break

    def redacted(self) -> Dict[str, Any]:
        data = asdict(self)
        data["api_key"] = "***" if self.api_key else None
        return data
