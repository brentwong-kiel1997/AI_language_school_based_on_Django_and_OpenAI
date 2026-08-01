"""Generic textbook-style grammar module prompt."""

from .common import build_module_prompt

STYLE = (
    "Write grammar like a clear language-course textbook with SEPARATE fields "
    "(never dump collocations/forms/model/note into one blob). "
    "Each entry needs: pattern; meaning (function in learner native language); "
    "overview (1–2 short sentences only — when to use it); "
    "collocations (typical verb/preposition patterns with native gloss); "
    "forms (ending/article quick-reference lines); "
    "model (one full target sentence + native translation); "
    "note (contrast/注意事项, optional); "
    "examples (3–6 short phrases with native translations); "
    "practice: instruction + items where EACH item is "
    "{prompt (learner native language), answer (TARGET language)}. "
    "Every practice prompt MUST have a corresponding answer. "
    "Ground in the video source; light adaptation OK. "
    "FORBIDDEN: stuffing 【典型搭配】/【结尾】/【例句】/【注意】 into overview or explanation."
)

SHAPE = (
    '{"import_grammars":[{'
    '"pattern":"structure label",'
    '"meaning":"core function in learner native language",'
    '"overview":"1-2 short sentences only",'
    '"collocations":[{"phrase":"verb + structure","translation":"native gloss"}],'
    '"forms":["ending rule 1","ending rule 2"],'
    '"model":{"sentence":"full target sentence","translation":"native gloss"},'
    '"note":"contrast / caveat (optional)",'
    '"examples":[{"phrase":"short target phrase","translation":"native gloss"}],'
    '"practice":{"instruction":"how to do the drill",'
    '"items":[{"prompt":"native prompt","answer":"target answer"}]}'
    "}]} with at least 2 entries"
)

SHAPE_HINT = (
    '{"import_grammars":[{"pattern":"...","meaning":"...","overview":"...",'
    '"collocations":[{"phrase":"...","translation":"..."}],'
    '"forms":["..."],'
    '"model":{"sentence":"...","translation":"..."},'
    '"note":"...",'
    '"examples":[{"phrase":"...","translation":"..."}],'
    '"practice":{"instruction":"...",'
    '"items":[{"prompt":"...","answer":"..."}]}}]}'
)


def build(target_language: str, native_language: str, source: str) -> str:
    return build_module_prompt(
        target_language=target_language,
        native_language=native_language,
        source=source,
        style=STYLE,
        shape=SHAPE,
        extra=(
            "practice.items must be objects with prompt + answer. "
            "Never omit answers."
        ),
    )
