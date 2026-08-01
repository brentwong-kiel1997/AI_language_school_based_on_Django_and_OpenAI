"""Generic core (title / level / can-do / warm-up) module prompt."""

from .common import build_module_prompt

STYLE = (
    "Build the lesson frame from the source only. Choose a realistic CEFR level. "
    "can_do and warm_up must be concrete and grounded in the video content."
)

SHAPE = (
    '{"lesson_title": string, "level": "A1"|"A2"|"B1"|"B2"|"C1"|"C2", '
    '"can_do": [string, ...], "warm_up": [string, ...]}'
)

SHAPE_HINT = '{"lesson_title":"...","level":"B1","can_do":["..."],"warm_up":["..."]}'


def build(target_language: str, native_language: str, source: str) -> str:
    return build_module_prompt(
        target_language=target_language,
        native_language=native_language,
        source=source,
        style=STYLE,
        shape=SHAPE,
    )
