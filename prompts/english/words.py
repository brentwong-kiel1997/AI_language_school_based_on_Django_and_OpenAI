"""English dictionary / vocabulary module prompt."""

from prompts.base.common import build_module_prompt

STYLE = (
    "You are writing a Cambridge Learner's Dictionary / OALD-style ENGLISH vocabulary "
    "module for a video lesson. Pick 8–20 high-value words/phrases from the source.\n"
    "STRICT English-only metadata:\n"
    "- part_of_speech: full English labels only — noun, verb, adjective, adverb, "
    "preposition, conjunction, pronoun, determiner, interjection, phrasal verb, etc. "
    "NEVER use Russian (сущ./глаг./прил.) or German (Substantiv) labels.\n"
    "- ipa: required, IPA in slashes, e.g. /ˈvækjuːm/ (pick British or American and stay "
    "consistent across the lesson).\n"
    "- cefr: required — one of A1, A2, B1, B2, C1, C2.\n"
    "- register: neutral/formal/informal/technical when useful; else null.\n"
    "Each entry: term (lemma/headword), numbered senses. Every sense MUST have: "
    "definition (clear English learner definition), translation (learner native language), "
    "example (natural English, from or lightly adapted from the source), collocations "
    "(array, may be empty). Optional per entry: synonyms, antonyms, usage_note.\n"
    "Do not invent facts, etymology, or senses unsupported by the source.\n"
    'Complete JSON example: {"import_words":[{"term":"vacuum","ipa":"/ˈvækjuːm/",'
    '"part_of_speech":"noun","cefr":"C1",'
    '"senses":[{"definition":"A space entirely devoid of matter.",'
    '"translation":"真空","example":"The experiment was done in a vacuum.",'
    '"collocations":["in a vacuum","vacuum cleaner"]}],'
    '"register":"neutral","synonyms":[],"antonyms":[],"usage_note":null}]}'
)

SHAPE = (
    '{"import_words":[{"term":string,"ipa":string,"part_of_speech":"noun|verb|adjective|...",'
    '"cefr":"A1"|"A2"|"B1"|"B2"|"C1"|"C2",'
    '"senses":[{"definition":string,"translation":string,"example":string,"collocations":[...]}],'
    '"register":string|null,"synonyms":[...],"antonyms":[...],"usage_note":string|null}]} '
    "with 8-20 entries"
)

SHAPE_HINT = (
    '{"import_words":[{"term":"vacuum","ipa":"/ˈvækjuːm/","part_of_speech":"noun",'
    '"cefr":"C1","senses":[{"definition":"...","translation":"...","example":"..."}]}]}'
)


def build(target_language: str, native_language: str, source: str) -> str:
    return build_module_prompt(
        target_language=target_language,
        native_language=native_language,
        source=source,
        style=STYLE,
        shape=SHAPE,
        extra=(
            "part_of_speech and definitions must be in English. "
            "translation is mandatory in the learner native language. "
            "Reject mixing Russian/German grammatical labels into English entries."
        ),
    )
