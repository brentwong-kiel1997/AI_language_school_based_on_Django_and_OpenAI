"""Auth / credentials helper, mirroring ``mmx auth login/status/refresh/logout``."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .regions import detect_region

AUTH_CACHE_FILE = "auth.json"


@dataclass
class AuthState:
    api_key: str
    region: str
    logged_in_at: str
    last_refresh: str | None = None

    def to_dict(self) -> dict:
        return {
            "api_key": self.api_key,
            "region": self.region,
            "logged_in_at": self.logged_in_at,
            "last_refresh": self.last_refresh,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AuthState":
        return cls(
            api_key=data.get("api_key", ""),
            region=data.get("region", "cn"),
            logged_in_at=data.get("logged_in_at", ""),
            last_refresh=data.get("last_refresh"),
        )

    def short_key(self) -> str:
        if not self.api_key:
            return "(not set)"
        if len(self.api_key) <= 8:
            return "*" * len(self.api_key)
        return f"{self.api_key[:4]}...{self.api_key[-4:]}"


class AuthStore:
    """Thin wrapper around the config that mimics ``mmx auth`` commands."""

    def __init__(self, config: Config | None = None):
        self.config = config or Config.load()

    # ---- ``mmx auth login`` -------------------------------------------------
    def login(self, api_key: str, region: str | None = None) -> AuthState:
        if not api_key or not api_key.strip():
            raise ValueError("API key is empty.")
        api_key = api_key.strip()
        region = region or detect_region(api_key)
        self.config.api_key = api_key
        self.config.region = region
        self.config.save()
        state = AuthState(
            api_key=api_key,
            region=region,
            logged_in_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self._save_state(state)
        return state

    # ---- ``mmx auth status`` ------------------------------------------------
    def status(self) -> AuthState:
        state = self._load_state()
        if not state and self.config.api_key:
            # Recover from a partial write.
            state = AuthState(
                api_key=self.config.api_key,
                region=self.config.region,
                logged_in_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            self._save_state(state)
        return state or AuthState(api_key="", region="cn", logged_in_at="")

    def is_logged_in(self) -> bool:
        return bool(self.status().api_key)

    # ---- ``mmx auth refresh`` -----------------------------------------------
    def refresh(self) -> AuthState:
        state = self.status()
        if not state.api_key:
            raise RuntimeError("Not logged in. Run `mmx auth login --api-key <key>` first.")
        # The MiniMax Token Plan doesn't expose a refresh endpoint – this is
        # a no-op that re-stamps ``last_refresh`` and re-detects region, which
        # is exactly what the upstream CLI does.
        state.region = detect_region(state.api_key)
        state.last_refresh = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.config.region = state.region
        self.config.save()
        self._save_state(state)
        return state

    # ---- ``mmx auth logout`` ------------------------------------------------
    def logout(self) -> None:
        self.config.api_key = ""
        self.config.save()
        path = self._state_path()
        if path.exists():
            path.unlink()

    # ---- internals ----------------------------------------------------------
    @staticmethod
    def _state_path() -> Path:
        return Config.path().parent / AUTH_CACHE_FILE

    def _load_state(self) -> AuthState | None:
        path = self._state_path()
        if not path.exists():
            return None
        import json as _json

        try:
            return AuthState.from_dict(_json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return None

    def _save_state(self, state: AuthState) -> None:
        import json as _json

        path = self._state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json.dumps(state.to_dict(), indent=2), encoding="utf-8")
        try:
            import os
            os.chmod(path, 0o600)
        except OSError:
            pass
