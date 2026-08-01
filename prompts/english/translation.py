"""English timed-caption translation module prompt."""

from prompts.base.common import build_module_prompt

STYLE = (
    "Translate the timed source captions into the learner native language. "
    "Preserve every timestamp key exactly. Keep names and numbers accurate. "
    "Do not invent events absent from the source. Natural fluent translation, not word-for-word."
)

SHAPE = (
    'EXACTLY {"translation": {"0:00:00": "...", "0:00:05": "...", ...}}. '
    'The top-level key MUST be the string "translation". '
    "Do NOT return a bare timestamp map without that wrapper key."
)

SHAPE_HINT = '{"translation":{"0:00:00":"...","0:00:05":"..."}}'


def build(target_language: str, native_language: str, source: str) -> str:
    return build_module_prompt(
        target_language=target_language,
        native_language=native_language,
        source=source,
        style=STYLE,
        shape=SHAPE,
    )
