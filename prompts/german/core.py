"""German lesson frame module prompt."""

from prompts.base.common import build_module_prompt

STYLE = (
    "Build the lesson frame for a GERMAN (DaF) course from the source only.\n"
    "- lesson_title: concise German title reflecting the video topic.\n"
    "- level: realistic CEFR A1–C2.\n"
    "- can_do: 3–5 Kann-do statements in German (functional ability, e.g. "
    "\"Ich kann die Hauptthese des Berichts zusammenfassen.\").\n"
    "- warm_up: 3–5 discussion questions in German, grounded in the video.\n"
    "Do not invent facts absent from the source."
)

SHAPE = (
    '{"lesson_title": string, "level": "A1"|"A2"|"B1"|"B2"|"C1"|"C2", '
    '"can_do": [string, ...], "warm_up": [string, ...]}'
)

SHAPE_HINT = (
    '{"lesson_title":"Handel und Sanktionen","level":"B2",'
    '"can_do":["Ich kann die Hauptpunkte des Videos nennen"],'
    '"warm_up":["Worüber berichtet das Video hauptsächlich?"]}'
)


def build(target_language: str, native_language: str, source: str) -> str:
    return build_module_prompt(
        target_language=target_language,
        native_language=native_language,
        source=source,
        style=STYLE,
        shape=SHAPE,
    )
