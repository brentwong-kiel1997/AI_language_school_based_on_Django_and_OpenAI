"""Russian dictionary / vocabulary module prompt."""

from prompts.base.common import build_module_prompt

STYLE = (
    "You are writing a Russian dictionary module in Ozhegov / Gramota.ru / 俄汉词典 style "
    "from the source. Pick 8–20 high-value words/phrases.\n"
    "STRICT Russian-only metadata:\n"
    "- pronunciation.stress_marked: headword WITH acute stress (U+0301), e.g. "
    "сотрудни́чество — required.\n"
    "- pronunciation.ipa: IPA in brackets when known.\n"
    "- part_of_speech: Russian abbreviations ONLY — сущ., глаг., прил., нареч., "
    "мест., предл., союз, межд., etc. NEVER English noun/verb or German Substantiv.\n"
    "- grammatical_info.gender for nouns: masculine/feminine/neuter (or м./ж./ср.).\n"
    "- forms.genitive: genitive ending when known (e.g. \"-а\", \"-и\").\n"
    "- For verbs: aspect in grammatical_info when clear (perfective/imperfective).\n"
    "Each entry: term (lemma without stress in term field is OK if stress_marked present), "
    "numbered senses. Every sense: definition (Russian), translation (learner native "
    "language), example (Russian from/adapted from source), collocations.\n"
    "Optional: synonyms, antonyms, phraseology, note.\n"
    "Do not invent unsupported morphology.\n"
    'Complete JSON example: {"import_words":[{"term":"сотрудничество",'
    '"pronunciation":{"stress_marked":"сотрудни́чество","ipa":"[sətrudˈnʲit͡ɕɪstvə]"},'
    '"part_of_speech":"сущ.","grammatical_info":{"gender":"neuter"},'
    '"forms":{"genitive":"-а"},'
    '"senses":[{"definition":"Совместная деятельность для достижения цели.",'
    '"translation":"合作","example":"Военное сотрудничество России и Китая.",'
    '"collocations":["военное сотрудничество"]}],'
    '"synonyms":[],"antonyms":[],"phraseology":[],"note":null}]}'
)

SHAPE = (
    '{"import_words":[{"term":string,'
    '"pronunciation":{"stress_marked":"with acute stress","ipa":string},'
    '"part_of_speech":"сущ.|глаг.|прил.|...",'
    '"grammatical_info":{"gender":"masculine|feminine|neuter","aspect":"perfective|imperfective"} (when applicable),'
    '"forms":{"genitive":"-а"} (nouns, when known),'
    '"senses":[{"definition":string,"translation":string,"example":string,"collocations":[...]}]}]} '
    "with 8-20 entries"
)

SHAPE_HINT = (
    '{"import_words":[{"term":"сотрудничество",'
    '"pronunciation":{"stress_marked":"сотрудни́чество"},'
    '"part_of_speech":"сущ.","grammatical_info":{"gender":"neuter"},'
    '"forms":{"genitive":"-а"},'
    '"senses":[{"definition":"...","translation":"合作","example":"...","collocations":["..."]}]}]}'
)


def build(target_language: str, native_language: str, source: str) -> str:
    return build_module_prompt(
        target_language=target_language,
        native_language=native_language,
        source=source,
        style=STYLE,
        shape=SHAPE,
        extra=(
            "stress_marked with acute accent is mandatory. "
            "translation mandatory in learner native language. "
            "Never use English/German POS labels for Russian entries."
        ),
    )
