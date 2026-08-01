"""Generic speaking / writing / review module prompt."""

from .common import build_module_prompt

STYLE = (
    "Create production tasks with SEPARATE fields — never dump instructions, "
    "word lists, and checklist into one paragraph. "
    "speaking_task and writing_task are objects: "
    "prompt (clear task in TARGET language), "
    "useful_language (array of target words/phrases to reuse), "
    "checklist (array of short requirements), "
    "sample_answer (REQUIRED model response in the TARGET language that a strong "
    "learner could give — speaking: ~8–14 sentences of spoken prose; writing: "
    "8–12 essay sentences). "
    "Optional: duration (speaking) or length (writing), support_phrases (useful openers). "
    "review is an array of {term, translation} for quick recycle "
    "(term in target language; translation in learner native language). "
    "Ground tasks and sample answers in the source topic; do not invent video facts."
)

SHAPE = (
    '{"speaking_task":{"prompt":"...","duration":"1-2 min",'
    '"useful_language":["...","..."],"checklist":["...","..."],'
    '"sample_answer":"full spoken model answer in target language"},'
    '"writing_task":{"prompt":"...","length":"8-12 sentences",'
    '"useful_language":["..."],"checklist":["..."],'
    '"support_phrases":["I think","on the one hand"],'
    '"sample_answer":"full written model essay in target language"},'
    '"review":[{"term":"...","translation":"..."}]}'
)

SHAPE_HINT = SHAPE


def build(target_language: str, native_language: str, source: str) -> str:
    return build_module_prompt(
        target_language=target_language,
        native_language=native_language,
        source=source,
        style=STYLE,
        shape=SHAPE,
        extra=(
            "Do NOT return speaking_task/writing_task as a single long string. "
            "sample_answer is mandatory for both tasks."
        ),
    )
