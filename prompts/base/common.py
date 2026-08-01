"""Shared helpers for assembling module prompts."""

from __future__ import annotations

SCHEMA_RULES = (
    "Return one JSON object only. No markdown fences, no commentary. "
    "Use exactly the required top-level keys for this module."
)

MODULE_NAMES = ("core", "words", "grammar", "listening", "expression", "translation")


def lesson_context(target_language: str, native_language: str, source: str) -> str:
    return (
        f"Learner native language: {native_language}; "
        f"target language: {target_language}.\n"
        f"Source:\n{source}"
    )


def build_module_prompt(
    *,
    target_language: str,
    native_language: str,
    source: str,
    style: str,
    shape: str,
    extra: str = "",
) -> str:
    parts = [
        lesson_context(target_language, native_language, source),
        style.strip(),
        SCHEMA_RULES,
        f"Required shape: {shape.strip()}",
    ]
    if extra.strip():
        parts.append(extra.strip())
    return "\n".join(parts)
