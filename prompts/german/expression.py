"""German speaking / writing / review module prompt."""

from prompts.base.common import build_module_prompt

STYLE = (
    "Create GERMAN production tasks with SEPARATE fields.\n"
    "speaking_task / writing_task:\n"
    "- prompt, useful_language, checklist, sample_answer — all in German.\n"
    "- sample_answer REQUIRED (speaking: ~8–14 Sätze; writing: 8–12 Satz Aufsatz).\n"
    "- support_phrases for writing: z. B. \"Ich denke\", \"meiner Meinung nach\", "
    "\"einerseits … andererseits\".\n"
    "review: [{term (German), translation (learner native language)}].\n"
    "Ground in the video topic."
)

SHAPE = (
    '{"speaking_task":{"prompt":"Fassen Sie das Video zusammen und äußern Sie Ihre Meinung.",'
    '"duration":"1-2 Min","useful_language":["Handel","Sanktion"],'
    '"checklist":["Hauptthese nennen","Zwei Wörter aus der Lektion verwenden"],'
    '"sample_answer":"Das Video erklärt, dass..."},'
    '"writing_task":{"prompt":"Schreiben Sie einen kurzen Aufsatz zum Thema.",'
    '"length":"8-12 Sätze","useful_language":["Politik","Auswirkung"],'
    '"checklist":["Einleitung","Zwei Argumente","Schluss"],'
    '"support_phrases":["Ich denke","einerseits","andererseits"],'
    '"sample_answer":"In den letzten Jahren..."},'
    '"review":[{"term":"Handel","translation":"贸易"}]}'
)

SHAPE_HINT = SHAPE


def build(target_language: str, native_language: str, source: str) -> str:
    return build_module_prompt(
        target_language=target_language,
        native_language=native_language,
        source=source,
        style=STYLE,
        shape=SHAPE,
        extra="sample_answer mandatory for both tasks.",
    )
