"""Resolve target-language aliases to a language pack."""

from __future__ import annotations

from types import ModuleType

from . import base, english, german, russian

TARGET_LANGUAGE_ALIASES = {
    "russian": "russian",
    "русский": "russian",
    "ru": "russian",
    "俄语": "russian",
    "english": "english",
    "英语": "english",
    "en": "english",
    "german": "german",
    "德语": "german",
    "de": "german",
}

_PACKS: dict[str, ModuleType] = {
    "russian": russian,
    "english": english,
    "german": german,
}


def canonical_target_language(target_language: str) -> str:
    return TARGET_LANGUAGE_ALIASES.get(str(target_language or "").strip().lower(), "")


def get_language_pack(target_language: str) -> ModuleType:
    """Return the language pack module (russian / english / german / base)."""
    key = canonical_target_language(target_language)
    return _PACKS.get(key, base)
