"""German listening / comprehension module prompt."""

from prompts.base.common import build_module_prompt

STYLE = (
    "Create GERMAN listening drills and open comprehension Q&A grounded only in the source.\n"
    "listening_tasks: 2–3 blocks with type + instruction + items.\n"
    "- true_false: {statement (German), answer: \"wahr\"/\"falsch\" or \"richtig\"/\"falsch\"}.\n"
    "- multiple_choice: German question, 4 German options, answer A/B/C/D.\n"
    "- fill_in_the_blank: German sentence with _____, German answer.\n"
    "Instruction may use learner native language briefly.\n"
    "questions[] and answers[]: 6–12 open comprehension pairs FULLY in German. "
    "Do NOT write open Q&A in the learner native language."
)

SHAPE = (
    '{"listening_tasks":['
    '{"type":"true_false","instruction":"Richtig oder falsch?",'
    '"items":[{"statement":"Der Bericht handelt von Handelspolitik.","answer":"wahr"}]},'
    '{"type":"multiple_choice","instruction":"Wählen Sie die beste Antwort.",'
    '"items":[{"question":"Was ist das Hauptthema?","options":["Handel","Sport","Wetter","Musik"],"answer":"A"}]}'
    '],'
    '"questions":["Welches Problem wird genannt?"],'
    '"answers":["Steigende Zölle auf Importe."]}'
)

SHAPE_HINT = SHAPE


def build(target_language: str, native_language: str, source: str) -> str:
    return build_module_prompt(
        target_language=target_language,
        native_language=native_language,
        source=source,
        style=STYLE,
        shape=SHAPE,
        extra="Open questions/answers and drill content must be in German.",
    )
