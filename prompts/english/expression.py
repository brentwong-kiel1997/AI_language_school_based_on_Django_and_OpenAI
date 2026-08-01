"""English speaking / writing / review module prompt."""

from prompts.base.common import build_module_prompt

STYLE = (
    "Create ENGLISH production tasks with SEPARATE fields — never one long paragraph.\n"
    "speaking_task and writing_task objects:\n"
    "- prompt: clear task in English.\n"
    "- useful_language: array of English words/phrases from the lesson to reuse.\n"
    "- checklist: short requirements in English.\n"
    "- sample_answer: REQUIRED model in English (speaking: ~8–14 sentences of spoken "
    "prose; writing: 8–12 essay sentences). Must satisfy checklist and reuse "
    "useful_language items.\n"
    "Optional: duration (speaking), length (writing), support_phrases "
    '(e.g. "I think", "on the one hand", "in my view").\n'
    "review: [{term (English), translation (learner native language)}] — 6–12 items.\n"
    "Ground tasks in the video topic; no invented facts."
)

SHAPE = (
    '{"speaking_task":{"prompt":"Summarise the video and give your opinion.",'
    '"duration":"1-2 min","useful_language":["trade","sanction","agreement"],'
    '"checklist":["Mention the main claim","Use at least two lesson words","Give one reason"],'
    '"sample_answer":"The video argues that..."},'
    '"writing_task":{"prompt":"Write a short essay on the topic.",'
    '"length":"8-12 sentences","useful_language":["policy","impact"],'
    '"checklist":["Clear introduction","Two supporting points","Conclusion"],'
    '"support_phrases":["I think","on the one hand","however"],'
    '"sample_answer":"In recent years,..."},'
    '"review":[{"term":"trade","translation":"贸易"},{"term":"sanction","translation":"制裁"}]}'
)

SHAPE_HINT = SHAPE


def build(target_language: str, native_language: str, source: str) -> str:
    return build_module_prompt(
        target_language=target_language,
        native_language=native_language,
        source=source,
        style=STYLE,
        shape=SHAPE,
        extra="sample_answer is mandatory for both speaking_task and writing_task.",
    )
