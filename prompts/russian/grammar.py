"""Russian textbook-style grammar module prompt."""

from prompts.base.common import build_module_prompt

STYLE = (
    "Write Russian grammar like a clean 俄语语法 textbook card. "
    "Use SEPARATE fields — never paste 【典型搭配】【三格结尾速查】【例句】【注意】 "
    "into one explanation string. "
    "pattern e.g. \"к + 三格 (Дательный падеж)\"; "
    "meaning e.g. \"表示「向…」、「朝…」、「对…」\"; "
    "overview: 1–2 sentences only; "
    "collocations: e.g. обратиться к кому / 向…求助; "
    "forms: ending quick list; "
    "model: one full Russian sentence + Chinese gloss; "
    "note: contrasts when useful; "
    "examples: short phrases; "
    "practice.instruction like \"用 … 翻译以下中文：\"; "
    "practice.items: EACH item is {\"prompt\":\"中文\",\"answer\":\"俄语参考答案\"}. "
    "答案 must be natural Russian that clearly uses the target grammar. "
    "Metalanguage in the learner native language; Russian stays in phrase/sentence/answer fields."
)

SHAPE = (
    '{"import_grammars":[{'
    '"pattern":"с + 工具格 (Творительный падеж)",'
    '"meaning":"表示「与…一起」、「和…的关系」",'
    '"overview":"с + 工具格表示共同行动的伙伴或联系对象。",'
    '"collocations":[{"phrase":"сотрудничать с кем","translation":"与…合作"}],'
    '"forms":["阳/中：-ом/-ем","阴：-ой/-ей","复：-ами/-ями"],'
    '"model":{"sentence":"Россия сотрудничает с Китаем.",'
    '"translation":"俄罗斯与中国合作。"},'
    '"note":"с + Тв. ≠ с + Род.",'
    '"examples":[{"phrase":"связи с Китаем","translation":"与中国的关系"}],'
    '"practice":{"instruction":"用 с + 工具格 翻译以下中文：",'
    '"items":[{"prompt":"中国提议与俄罗斯合作。",'
    '"answer":"Китай предложил сотрудничать с Россией."}]}'
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
        extra=(
            "STRICT: every practice item needs prompt (Chinese) + answer (Russian). "
            "Do not return practice items as bare strings."
        ),
    )
