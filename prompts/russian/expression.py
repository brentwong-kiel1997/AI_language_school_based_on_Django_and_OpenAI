"""Russian speaking / writing / review module prompt."""

from prompts.base.common import build_module_prompt
from prompts.base.expression import SHAPE, SHAPE_HINT

STYLE = (
    "Create Russian speaking and writing tasks with SEPARATE fields "
    "(prompt / useful_language / checklist / sample_answer). "
    "Never pack everything into one paragraph. "
    "speaking_task.prompt in Russian; writing_task.prompt in Russian; "
    "useful_language and checklist in Russian; "
    "sample_answer REQUIRED in Russian for BOTH tasks "
    "(口语: coherent 1–2 minute spoken model; 写作: 8–12 sentence essay model). "
    "Sample answers must use several useful_language items and satisfy the checklist. "
    "support_phrases for writing: я думаю / по-моему / с одной стороны…; "
    "review: [{term (RU), translation (learner native language)}]. "
    "Ground in the video topic; no invented facts."
)


def build(target_language: str, native_language: str, source: str) -> str:
    return build_module_prompt(
        target_language=target_language,
        native_language=native_language,
        source=source,
        style=STYLE,
        shape=SHAPE,
        extra=(
            "STRICT: speaking_task and writing_task must be JSON objects. "
            "prompt, useful_language, checklist, and sample_answer are required."
        ),
    )


__all__ = ["STYLE", "SHAPE", "SHAPE_HINT", "build"]
