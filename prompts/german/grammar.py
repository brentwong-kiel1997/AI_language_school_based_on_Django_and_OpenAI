"""German textbook-style grammar module prompt."""

from prompts.base.common import build_module_prompt

STYLE = (
    "Write GERMAN grammar like a clean DaF textbook card with SEPARATE JSON fields — "
    "never dump Kollokationen/Endungen/Beispiel/Hinweis into overview.\n"
    "At least 2 patterns from the source. Each item:\n"
    "- pattern: German label with case when relevant, e.g. \"mit + Dativ\", "
    "\"Perfekt mit haben/sein\".\n"
    "- meaning: function in learner native language.\n"
    "- overview: 1–2 short German sentences.\n"
    "- collocations: German phrases with native gloss.\n"
    "- forms: article endings / conjugation quick-reference lines.\n"
    "- model: full German sentence + native translation.\n"
    "- note: contrast/common errors (optional).\n"
    "- examples: 3–6 short German phrases with translations.\n"
    "- practice: instruction + items [{prompt (native), answer (German)}].\n"
    "Ground in the video; light adaptation OK."
)

SHAPE = (
    '{"import_grammars":[{'
    '"pattern":"mit + Dativ",'
    '"meaning":"表示「与…一起」",'
    '"overview":"mit + Dativ drückt Begleitung oder Mittel aus.",'
    '"collocations":[{"phrase":"mit Freunden","translation":"与朋友一起"}],'
    '"forms":["mit + dem/der/den (+ Dativendung)"],'
    '"model":{"sentence":"Deutschland arbeitet mit Frankreich zusammen.","translation":"德国与法国合作。"},'
    '"note":"Nicht verwechseln mit «bei».",'
    '"examples":[{"phrase":"mit der Familie","translation":"与家人"}],'
    '"practice":{"instruction":"Übersetzen Sie ins Deutsche:",'
    '"items":[{"prompt":"他与同事合作。","answer":"Er arbeitet mit seinen Kollegen zusammen."}]}'
    "}]} with at least 2 entries"
)

SHAPE_HINT = SHAPE


def build(target_language: str, native_language: str, source: str) -> str:
    return build_module_prompt(
        target_language=target_language,
        native_language=native_language,
        source=source,
        style=STYLE,
        shape=SHAPE,
        extra="practice.items need prompt + German answer. Keep overview short.",
    )
