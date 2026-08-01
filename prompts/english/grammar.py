"""English textbook-style grammar module prompt."""

from prompts.base.common import build_module_prompt

STYLE = (
    "Write ENGLISH grammar for a learner textbook with SEPARATE JSON fields — never dump "
    "collocations/forms/model/note into overview.\n"
    "At least 2 patterns from the source. Each import_grammars item:\n"
    "- pattern: English label, e.g. \"present perfect with since/for\", \"passive voice\".\n"
    "- meaning: core function in the learner native language.\n"
    "- overview: 1–2 short English sentences (when/how to use); NOT a wall of text.\n"
    "- collocations: typical English patterns with native gloss, "
    '[{"phrase":"have been working","translation":"一直在做…"}].\n'
    "- forms: quick-reference lines (affirmative/negative/question, irregular notes).\n"
    "- model: one full English sentence + native translation.\n"
    "- note: common mistakes / contrast (optional).\n"
    "- examples: 3–6 short English phrases with native translations.\n"
    "- practice: instruction (may use native language) + items "
    '[{"prompt":"native prompt","answer":"English answer"}]; every item needs both.\n'
    "Ground all examples in the video topic; light adaptation OK."
)

SHAPE = (
    '{"import_grammars":[{'
    '"pattern":"present perfect with since",'
    '"meaning":"表示从过去持续到现在的动作",'
    '"overview":"Use the present perfect with since/for for actions that started in the past and continue now.",'
    '"collocations":[{"phrase":"have lived here since 2020","translation":"从2020年起一直住在这里"}],'
    '"forms":["have/has + past participle","since + point in time","for + duration"],'
    '"model":{"sentence":"Trade has grown since the agreement.","translation":"自协议以来贸易增长了。"},'
    '"note":"Do not use since with a finished past time (use past simple).",'
    '"examples":[{"phrase":"have worked here for years","translation":"在这里工作多年了"}],'
    '"practice":{"instruction":"Complete using the present perfect:",'
    '"items":[{"prompt":"自2019年以来","answer":"since 2019"}]}'
    "}]} with at least 2 entries"
)

SHAPE_HINT = SHAPE


def build(target_language: str, native_language: str, source: str) -> str:
    return build_module_prompt(
        target_language=target_language,
        native_language=native_language,
        source=source,
        style=STYLE,
        shape=SHAPE,
        extra="practice.items must be objects with prompt + English answer.",
    )
