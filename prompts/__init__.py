"""Standalone lesson-generation prompts (not part of Django).

Usage::

    from prompts import get_language_pack, canonical_target_language

    pack = get_language_pack("ru")
    text = pack.module("grammar", "ru", "Chinese", source)
"""

from .registry import canonical_target_language, get_language_pack

__all__ = ["canonical_target_language", "get_language_pack"]
