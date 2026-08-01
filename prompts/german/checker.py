"""German-specific Checker quality bar."""

from __future__ import annotations

_MODULE_CRITERIA: dict[str, str] = {
    "words": (
        "words: Duden-style GERMAN entries. part_of_speech in German (Substantiv, Verb, "
        "Adjektiv, Adverb, etc.) — not Russian сущ. Nouns need article (der/die/das) and "
        "gender; plural_or_forms when known. pronunciation required. Each sense: German "
        "definition, native translation, German example."
    ),
    "grammar": (
        "grammar: DaF textbook card; separate fields; cases/articles/endings in forms; "
        "practice answers in German."
    ),
    "listening": (
        "listening: German statements/questions/answers; true_false answers wahr/falsch "
        "or richtig/falsch; grounded in source."
    ),
    "expression": (
        "expression: prompt, useful_language, checklist, sample_answer in German."
    ),
    "translation": (
        'translation: {"translation": {timestamp: native-language caption}} only. '
        "Adjacent timestamps MAY be merged if the translation covers all source content; "
        "do NOT reject for missing individual keys when content is present under a nearby key."
    ),
    "core": (
        "core: lesson_title in German; realistic CEFR; can_do/warm_up grounded in source."
    ),
}


def criteria(module: str) -> str:
    return _MODULE_CRITERIA.get(module, "")
