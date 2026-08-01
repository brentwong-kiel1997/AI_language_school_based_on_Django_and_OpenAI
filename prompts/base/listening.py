"""Generic listening / comprehension module prompt."""

from .common import build_module_prompt

STYLE = (
    "Create structured listening drills plus open comprehension Q&A, "
    "grounded only in the source. Do not invent facts absent from the transcript. "
    "listening_tasks is an array of exercise blocks with SEPARATE fields: "
    "type (true_false | multiple_choice | fill_in_the_blank), "
    "instruction (how to do the drill; may use learner native language), "
    "items (typed rows). "
    "true_false items: {statement, answer} with answer В/Н or true/false/yes/no. "
    "multiple_choice items: {question, options[4], answer}. "
    "fill_in_the_blank items: {sentence with _____, answer}. "
    "Listening statements/MC questions/blanks stay in the TARGET language. "
    "questions[] and answers[] are open comprehension in the TARGET language "
    "(same length; 6–12 pairs). Do NOT write those open Q&A in the learner native language. "
    "Prefer 2–3 listening_tasks covering different types."
)

SHAPE = (
    '{"listening_tasks":['
    '{"type":"true_false","instruction":"...",'
    '"items":[{"statement":"...","answer":"В"}]},'
    '{"type":"multiple_choice","instruction":"...",'
    '"items":[{"question":"...","options":["A","B","C","D"],"answer":"B"}]},'
    '{"type":"fill_in_the_blank","instruction":"...",'
    '"items":[{"sentence":"... _____ ...","answer":"..."}]}'
    '],'
    '"questions":["target-language question",...],'
    '"answers":["target-language answer",...]}'
)

SHAPE_HINT = (
    '{"listening_tasks":[{"type":"true_false","instruction":"Верно или неверно?",'
    '"items":[{"statement":"...","answer":"В"}]}],'
    '"questions":["О чём главная новость?"],'
    '"answers":["О военном сотрудничестве России и Китая."]}'
)


def build(target_language: str, native_language: str, source: str) -> str:
    return build_module_prompt(
        target_language=target_language,
        native_language=native_language,
        source=source,
        style=STYLE,
        shape=SHAPE,
        extra=(
            "questions/answers MUST be written in the target language "
            f"({target_language}), not in {native_language}. "
            "listening_tasks use type/instruction/items."
        ),
    )
