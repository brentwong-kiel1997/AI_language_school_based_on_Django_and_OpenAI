"""Russian timed-caption translation module prompt."""

from prompts.base.common import build_module_prompt

STYLE = (
    "Переведите титры исходного видео с временными метками на родной язык ученика. "
    "Сохраните все метки времени без изменений. Не выдумывайте факты, которых нет в источнике."
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
