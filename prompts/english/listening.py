"""English listening / comprehension module prompt."""

from prompts.base.common import build_module_prompt

STYLE = (
    "Create ENGLISH listening drills and open comprehension Q&A grounded only in the "
    "source. Do not invent facts.\n"
    "listening_tasks: 2–3 structured blocks with type + instruction + items.\n"
    "- type: true_false | multiple_choice | fill_in_the_blank.\n"
    "- instruction: how to do the drill (may use learner native language briefly).\n"
    "- true_false items: {statement (English), answer: \"true\" or \"false\"} — NOT В/Н.\n"
    "- multiple_choice items: {question (English), options[4] (English), answer: A/B/C/D}.\n"
    "- fill_in_the_blank items: {sentence with _____ (English), answer (English)}.\n"
    "questions[] and answers[]: 6–12 open comprehension pairs FULLY in English "
    "(same length). Do NOT write open Q&A in the learner native language."
)

SHAPE = (
    '{"listening_tasks":['
    '{"type":"true_false","instruction":"Listen and decide if each statement is true or false.",'
    '"items":[{"statement":"The report focuses on trade policy.","answer":"true"}]},'
    '{"type":"multiple_choice","instruction":"Choose the best answer.",'
    '"items":[{"question":"What is the main topic?","options":["Trade","Sports","Weather","Music"],"answer":"A"}]},'
    '{"type":"fill_in_the_blank","instruction":"Fill in the missing word.",'
    '"items":[{"sentence":"The agreement was signed in _____.","answer":"2024"}]}'
    '],'
    '"questions":["What problem does the speaker highlight?"],'
    '"answers":["Rising tariffs on imported goods."]}'
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
            "All statements, MC questions, blanks, and open Q&A must be in English. "
            "true_false answers: true or false only."
        ),
    )
