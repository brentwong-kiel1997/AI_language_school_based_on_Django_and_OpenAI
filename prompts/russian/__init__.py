"""Russian target-language prompt pack."""

from prompts.base.summarise import build as summarise_chunk

from . import checker, core, expression, grammar, listening, translation, words

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


__all__ = ["MODULES", "checker_criteria", "module", "shape_hint", "summarise_chunk"]
