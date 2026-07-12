"""Persistent configuration store for minimax_cli.

The store lives in ``~/.mmx/config.json`` and mirrors the upstream
``mmx config show/set`` behaviour:

* ``api_key``   – the bearer token (stored in plain text; we rely on
                  OS file permissions to keep it private, just like the
                  upstream CLI does).
* ``region``    – ``"cn"`` or ``"global"``.
* ``default_model`` – preferred model id for text chat.
* ``output_dir``   – where generated artefacts are written.
* ``stream``       – default streaming behaviour for chat / speech.

A small ``Config`` dataclass is also exposed so library users (e.g. the
Django views in this very project) can pull values directly:

    from minimax_cli import Config
    cfg = Config.load()
    client = MiniMaxClient(api_key=cfg.api_key, region=cfg.region)
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .exceptions import ValidationError
from .regions import Region, detect_region

DEFAULT_CONFIG_DIR = Path.home() / ".mmx"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.json"
DEFAULT_OUTPUT_DIRNAME = "minimax-output"


@dataclass
class Config:
    api_key: str = ""
    region: str = Region.CN.value
    # Latest chat model exposed by the platform's /v1/models endpoint.
    # The /v1/models listing is the source of truth – run `mmx models list`
    # to see all available ids; this default is just the newest one.
    default_model: str = "MiniMax-M3"
    output_dir: str = DEFAULT_OUTPUT_DIRNAME
    stream: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    # ---- (de)serialisation --------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Don't persist an empty key
        if not d.get("api_key"):
            d.pop("api_key", None)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        known = {f for f in cls.__dataclass_fields__ if f != "extra"}
        clean = {k: v for k, v in data.items() if k in known}
        extra = {k: v for k, v in data.items() if k not in known}
        cfg = cls(**clean)
        cfg.extra = extra
        # Validate region.
        try:
            Region(cfg.region)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        return cfg

    # ---- persistence --------------------------------------------------------
    @classmethod
    def path(cls) -> Path:
        return DEFAULT_CONFIG_PATH

    @classmethod
    def load(cls) -> "Config":
        path = cls.path()
        if not path.exists():
            return cls(api_key=os.environ.get("MINIMAX_API_KEY", ""))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return cls(api_key=os.environ.get("MINIMAX_API_KEY", ""))
        cfg = cls.from_dict(data)
        # Allow the env var to override what's on disk.
        env_key = os.environ.get("MINIMAX_API_KEY")
        if env_key:
            cfg.api_key = env_key
        return cfg

    def save(self) -> None:
        path = self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            # Windows / restricted FS – not fatal.
            pass

    # ---- helpers ------------------------------------------------------------
    def get(self, key: str) -> Any:
        if key in self.extra:
            return self.extra[key]
        return getattr(self, key, None)

    def set(self, key: str, value: Any) -> None:
        if key == "region":
            try:
                Region(str(value))
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
        if key in {f for f in self.__dataclass_fields__ if f != "extra"}:
            setattr(self, key, value)
        else:
            self.extra[key] = value

    def ensure_output_dir(self) -> Path:
        out = Path(self.output_dir).expanduser().resolve()
        out.mkdir(parents=True, exist_ok=True)
        return out
