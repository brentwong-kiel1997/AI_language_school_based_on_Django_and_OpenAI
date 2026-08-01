"""Fallback prompts when no language-specific pack is registered."""

from . import checker, core, expression, grammar, listening, translation, words
from .common import MODULE_NAMES
from .summarise import build as summarise_chunk

MODULES = {
    "core": core,
    "words": words,
    "grammar": grammar,
    "listening": listening,
    "expression": expression,
    "translation": translation,
}


def module(name: str, target_language: str, native_language: str, source: str) -> str:
    return MODULES[name].build(target_language, native_language, source)


def shape_hint(name: str) -> str:
    return MODULES[name].SHAPE_HINT


def checker_criteria(name: str) -> str:
    return checker.criteria(name)


__all__ = ["MODULES", "MODULE_NAMES", "checker_criteria", "module", "shape_hint", "summarise_chunk"]
