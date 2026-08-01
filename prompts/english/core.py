"""English lesson frame (title / level / can-do / warm-up) module prompt."""

from prompts.base.common import build_module_prompt

STYLE = (
    "Build the lesson frame for an ENGLISH course from the source only.\n"
    "- lesson_title: concise English title reflecting the video topic.\n"
    "- level: realistic CEFR A1–C2 for the vocabulary and grammar in this clip.\n"
    "- can_do: 3–5 can-do statements in English (or bilingual if the learner is "
    "beginner — English target skill + optional native gloss in parentheses).\n"
    "- warm_up: 3–5 discussion/thinking questions grounded in the video; write prompts "
    "in English. They may briefly use the learner native language only for instructions "
    f"when level is A1/A2.\n"
    "Do not invent people, dates, or events absent from the source."
)

SHAPE = (
    '{"lesson_title": string, "level": "A1"|"A2"|"B1"|"B2"|"C1"|"C2", '
    '"can_do": [string, ...], "warm_up": [string, ...]}'
)

SHAPE_HINT = (
    '{"lesson_title":"How sanctions affect trade","level":"B2",'
    '"can_do":["I can summarise the main argument","I can use trade vocabulary"],'
    '"warm_up":["What is the central claim of the report?","Who are the main actors?"]}'
)


def build(target_language: str, native_language: str, source: str) -> str:
    return build_module_prompt(
        target_language=target_language,
        native_language=native_language,
        source=source,
        style=STYLE,
        shape=SHAPE,
    )
