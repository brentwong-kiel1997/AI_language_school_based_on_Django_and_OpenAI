"""``mmx quota`` helper."""

from __future__ import annotations

from .client import MiniMaxClient


def render_quota(client: MiniMaxClient) -> str:
    """Return a human-friendly quota summary."""
    try:
        data = client.quota()
    except Exception as exc:
        return f"(unable to fetch quota: {exc})"
    total = data.get("total_granted") or data.get("total") or 0
    used = data.get("total_used") or data.get("used") or 0
    remain = max(0, (total or 0) - (used or 0))
    lines = [
        "Token Plan 余额",
        f"  total : {total}",
        f"  used  : {used}",
        f"  remain: {remain}",
    ]
    # Surface any sub-balances the platform returns.
    buckets = data.get("buckets") or data.get("credits") or []
    if isinstance(buckets, list) and buckets:
        lines.append("")
        lines.append("细分余额:")
        for b in buckets:
            if isinstance(b, dict):
                name = b.get("name") or b.get("type", "bucket")
                amt = b.get("remain") or b.get("remaining") or b.get("amount") or 0
                lines.append(f"  - {name}: {amt}")
    return "\n".join(lines)
