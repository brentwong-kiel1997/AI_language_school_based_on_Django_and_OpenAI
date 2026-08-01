"""German timed-caption translation module prompt."""

from prompts.base.common import build_module_prompt

STYLE = (
    "Übersetzen Sie die zeitgestempelten Untertitel des Quellvideos in die "
    "Muttersprache des Lernenden. Behalten Sie alle Zeitstempel exakt bei. "
    "Keine erfundenen Inhalte."
)

SHAPE = (
    'EXACTLY {"translation": {"0:00:00": "...", "0:00:05": "...", ...}}. '
    'Top-level key MUST be "translation".'
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
