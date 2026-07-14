import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

@dataclass
class Config:
    api_key: Optional[str] = None
    base_url: str = "https://api.minimaxi.com"
    text_model: str = "MiniMax-M3"
    context_window_tokens: int = 1_000_000
    max_tokens: int = 131072
    timeout_seconds: float = 120
    quota_endpoint: str = "/v1/coding_plan/quota"
    search_endpoint: str = "/v1/coding_plan/search"

    @classmethod
    def path(cls) -> Path:
        return Path(os.getenv("MINIMAX_CONFIG_DIR", str(Path.home() / ".mmx"))) / "config.json"

    @classmethod
    def load(cls) -> "Config":
        data: Dict[str, Any] = {}
        if cls.path().exists():
            try: data = json.loads(cls.path().read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc: raise ValueError("Invalid MiniMax config file") from exc
        values = {"api_key": data.get("api_key"), "base_url": data.get("base_url", cls.base_url), "text_model": data.get("text_model", cls.text_model), "context_window_tokens": data.get("context_window_tokens", cls.context_window_tokens), "max_tokens": data.get("max_tokens", cls.max_tokens), "timeout_seconds": data.get("timeout_seconds", cls.timeout_seconds), "quota_endpoint": data.get("quota_endpoint", cls.quota_endpoint), "search_endpoint": data.get("search_endpoint", cls.search_endpoint)}
        env = {"api_key":"MINIMAX_API_KEY", "base_url":"MINIMAX_BASE_URL", "text_model":"MINIMAX_TEXT_MODEL", "context_window_tokens":"MINIMAX_CONTEXT_WINDOW_TOKENS", "max_tokens":"MINIMAX_MAX_TOKENS", "timeout_seconds":"MINIMAX_TIMEOUT_SECONDS", "quota_endpoint":"MINIMAX_QUOTA_ENDPOINT", "search_endpoint":"MINIMAX_SEARCH_ENDPOINT"}
        for field, name in env.items():
            if name in os.environ: values[field] = os.environ[name]
        values["context_window_tokens"] = int(values["context_window_tokens"])
        values["max_tokens"] = int(values["max_tokens"])
        values["timeout_seconds"] = float(values["timeout_seconds"])
        return cls(**values)

    def save(self) -> None:
        path = self.path(); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.__dict__, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
