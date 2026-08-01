"""Generic Checker quality bar (fallback when no language pack override)."""

from __future__ import annotations

_MODULE_CRITERIA: dict[str, str] = {
    "words": (
        "words: dictionary-style entries grounded in the source; each sense needs "
        "definition (target language), translation (learner native language), and "
        "example; reject thin one-line stubs."
    ),
    "grammar": (
        "grammar: separate fields pattern/meaning/overview/collocations/forms/model/"
        "note/examples/practice; reject 【section】 dumps inside overview."
    ),
    "listening": (
        "listening: schema-complete blocks; Q&A about the video topic; slight "
        "paraphrase OK."
    ),
    "expression": (
        "expression: judge ONLY speaking_task, writing_task, review — topical and "
        "non-empty; sample_answer required."
    ),
    "translation": (
        'translation: top-level key must be "translation" wrapping the timestamp map.'
    ),
    "core": "core: realistic CEFR level; can_do and warm_up grounded in the source.",
}


def criteria(module: str) -> str:
    return _MODULE_CRITERIA.get(module, "")
