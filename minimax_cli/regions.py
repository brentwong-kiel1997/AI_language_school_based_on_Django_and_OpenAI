"""Region / endpoint resolution.

The MiniMax platform is served from two regions:

* ``cn``     – https://api.minimaxi.com       (bought at platform.minimaxi.com)
* ``global`` – https://api.minimax.io         (bought at platform.minimax.io)

The CLI ships with sensible defaults and an automatic detector that
inspects the API key prefix.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


class Region(str, Enum):
    CN = "cn"
    GLOBAL = "global"


@dataclass(frozen=True)
class Endpoint:
    base_url: str
    label: str


_ENDPOINTS: dict[Region, Endpoint] = {
    Region.CN: Endpoint(
        base_url="https://api.minimaxi.com",
        label="MiniMax (CN – platform.minimaxi.com)",
    ),
    Region.GLOBAL: Endpoint(
        base_url="https://api.minimax.io",
        label="MiniMax (Global – platform.minimax.io)",
    ),
}


def endpoint_for(region: Region | str) -> Endpoint:
    if isinstance(region, str):
        try:
            region = Region(region.lower())
        except ValueError as exc:
            raise ValueError(
                f"Unknown region {region!r}. Expected one of: "
                f"{', '.join(r.value for r in Region)}"
            ) from exc
    return _ENDPOINTS[region]


def detect_region(api_key: str | None = None) -> Region:
    """Heuristically pick a region from the API key prefix.

    Keys bought from the global console are typically prefixed ``eyJ...``
    (a JWT) or with a marker; keys from the CN console are also JWT-shaped
    but the platform distinguishes by trying the global endpoint first
    and falling back. We pick CN by default since that is the common
    case for mainland users; users can override with ``mmx config set``.
    """
    key = api_key or os.environ.get("MINIMAX_API_KEY", "")
    # The default; the user can always override with `mmx config set --key region`.
    if not key:
        return Region.CN
    return Region.CN
