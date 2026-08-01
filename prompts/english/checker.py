"""English-specific Checker quality bar."""

from __future__ import annotations

_MODULE_CRITERIA: dict[str, str] = {
    "words": (
        "words: Cambridge/OALD-style ENGLISH entries. part_of_speech MUST be English "
        "(noun, verb, adjective, adverb, preposition, etc.) — NEVER Russian сущ./глаг./прил. "
        "or German Substantiv. ipa required (IPA slashes). cefr required (A1–C2). "
        "Each sense: definition in English, translation in learner native language, "
        "natural English example from/adapted from source. Reject study-card stubs."
    ),
    "grammar": (
        "grammar: English learner textbook card with separate fields; overview 1–2 "
        "sentences; practice.items answers in English; meaning/overview may use "
        "learner native language."
    ),
    "listening": (
        "listening: English statements/questions/answers; true_false answers true/false "
        "(not В/Н); grounded in source."
    ),
    "expression": (
        "expression: prompts, useful_language, checklist, sample_answer in English; "
        "review.term in English."
    ),
    "translation": (
        'translation: {"translation": {timestamp: native-language caption}} only. '
        "Adjacent timestamps MAY be merged if the translation covers all source content; "
        "do NOT reject for missing individual keys when content is present under a nearby key."
    ),
    "core": (
        "core: lesson_title in English; CEFR level fits source difficulty; warm_up "
        "questions in English or bilingual as appropriate."
    ),
}


def criteria(module: str) -> str:
    return _MODULE_CRITERIA.get(module, "")
