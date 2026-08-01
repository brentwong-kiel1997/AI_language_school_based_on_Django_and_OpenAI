"""Russian-specific Checker quality bar."""

from __future__ import annotations

_MODULE_CRITERIA: dict[str, str] = {
    "words": (
        "words: Ozhegov/俄汉-style RUSSIAN entries. Headword with acute stress in "
        "pronunciation.stress_marked; part_of_speech as сущ./глаг./прил.; nouns need "
        "grammatical_info.gender; genitive ending when known. Each sense: Russian "
        "definition, native translation, Russian example."
    ),
    "grammar": (
        "grammar: 俄语语法 card; separate fields; case labels; practice answers in "
        "Russian; meaning in learner native language."
    ),
    "listening": (
        "listening: Russian statements/questions/answers; true_false answers В/Н; "
        "grounded in source."
    ),
    "expression": (
        "expression: prompt, useful_language, checklist, sample_answer in Russian."
    ),
    "translation": (
        'translation: {"translation": {timestamp: native-language caption}} only. '
        "Adjacent timestamps MAY be merged if the translation covers all source content; "
        "do NOT reject for missing individual keys when content is present under a nearby key."
    ),
    "core": (
        "core: lesson_title in Russian; realistic CEFR; can_do/warm_up grounded in source."
    ),
}


def criteria(module: str) -> str:
    return _MODULE_CRITERIA.get(module, "")
