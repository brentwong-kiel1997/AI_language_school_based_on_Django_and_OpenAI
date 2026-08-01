"""Generic dictionary / vocabulary module prompt."""

from .common import build_module_prompt

STYLE = (
    "Use a careful dictionary-entry structure: term, pronunciation when known, "
    "part_of_speech, grammatical information/forms, numbered senses, definition, "
    "translation, example, collocations, register, synonyms/antonyms, and usage_note. "
    "Do not invent anything; unsupported fields must be null or []. "
    "Ensure target-language accuracy. "
    "Every sense MUST include translation in the learner native language; "
    "definition stays in the target language. "
    "Prefer conventional part_of_speech abbreviations when they exist."
)

SHAPE = (
    '{"import_words":[{"term":string,"part_of_speech":string,'
    '"senses":[{"definition":string,"translation":string,"example":string}]}]} '
    "with 8-20 entries"
)

SHAPE_HINT = (
    '{"import_words":[{"term":"...","part_of_speech":"...",'
    '"senses":[{"definition":"...","translation":"...","example":"..."}]}]}'
)


def build(target_language: str, native_language: str, source: str) -> str:
    return build_module_prompt(
        target_language=target_language,
        native_language=native_language,
        source=source,
        style=STYLE,
        shape=SHAPE,
        extra="translation is mandatory in the learner native language.",
    )
