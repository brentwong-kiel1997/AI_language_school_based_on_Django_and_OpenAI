"""Russian listening / comprehension module prompt."""

from prompts.base.common import build_module_prompt
from prompts.base.listening import SHAPE, SHAPE_HINT

STYLE = (
    "Create Russian listening drills and Russian open comprehension Q&A for this video. "
    "listening_tasks MUST be structured blocks: type + instruction + items. "
    "Include at least one true_false (В/Н) and preferably also multiple_choice and/or "
    "fill_in_the_blank. Statements, MC questions, blanks, and answers stay in Russian. "
    "Instruction may briefly use the learner native language if helpful. "
    "questions[] and answers[]: open comprehension FULLY in Russian (same length, 6–12 pairs). "
    "Do NOT write open questions/answers in Chinese or other native languages. "
    "Ground only in the source; no invented facts."
)


def build(target_language: str, native_language: str, source: str) -> str:
    return build_module_prompt(
        target_language=target_language,
        native_language=native_language,
        source=source,
        style=STYLE,
        shape=SHAPE,
        extra=(
            "Use type/instruction/items for listening_tasks. "
            "true_false answers: В or Н. "
            "Open questions/answers: Russian only."
        ),
    )


__all__ = ["STYLE", "SHAPE", "SHAPE_HINT", "build"]
