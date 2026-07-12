"""``mmx update`` self-update helper.

We don't auto-download code from the network in the pure-Python port;
instead we just print a clear "you are up to date / new version available"
message based on a hard-coded release endpoint, and the user upgrades by
``pip install -U minimax-cli`` – which is the natural workflow for a
Python package (and matches what the upstream CLI does behind the scenes
via ``npm install -g mmx-cli@latest``).
"""

from __future__ import annotations

import importlib.metadata

import httpx

from . import __version__

PYPI_URL = "https://pypi.org/pypi/minimax-cli/json"


def check_latest(timeout: float = 5.0) -> str:
    try:
        r = httpx.get(PYPI_URL, timeout=timeout)
        r.raise_for_status()
        latest = r.json().get("info", {}).get("version", __version__)
    except Exception as exc:
        return f"无法查询最新版本 ({exc}). 当前: {__version__}"
    if _is_newer(latest, __version__):
        return (
            f"新版本可用: {latest} (当前 {__version__}).\n"
            f"升级: pip install -U minimax-cli"
        )
    return f"已是最新 ({__version__})."


def _is_newer(latest: str, current: str) -> bool:
    def parse(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in v.split(".") if x.isdigit())

    try:
        return parse(latest) > parse(current)
    except Exception:
        return False


def current_version() -> str:
    try:
        return importlib.metadata.version("minimax-cli")
    except Exception:
        return __version__
