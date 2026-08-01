"""German dictionary / vocabulary module prompt."""

from prompts.base.common import build_module_prompt

STYLE = (
    "You are writing a Duden / DaF-style GERMAN vocabulary module from the source. "
    "Pick 8–20 high-value words/phrases.\n"
    "STRICT German-only metadata:\n"
    "- part_of_speech: German labels — Substantiv, Verb, Adjektiv, Adverb, Präposition, "
    "Konjunktion, Pronomen, etc. NEVER Russian сущ./глаг./прил. or English-only labels "
    "without German equivalents.\n"
    "- pronunciation: required — IPA in brackets [haʊ̯s] or clear phonetic spelling.\n"
    "- For Substantiv: article (der/die/das) and gender (masculine/feminine/neuter) "
    "required; plural_or_forms.plural when known.\n"
    "- For verbs: note separable prefix in term when applicable (e.g. an|kommen).\n"
    "Each entry: term (lemma), numbered senses. Every sense: definition (German), "
    "translation (learner native language), example (natural German from/adapted from "
    "source), collocations. Optional: register, synonyms, antonyms, usage_note.\n"
    "Do not invent morphology unsupported by the source.\n"
    'Complete JSON example: {"import_words":[{"term":"Haus","pronunciation":"[haʊ̯s]",'
    '"part_of_speech":"Substantiv","article":"das","gender":"neuter",'
    '"plural_or_forms":{"plural":"Häuser"},'
    '"senses":[{"definition":"Gebäude, in dem Menschen wohnen.",'
    '"translation":"房子","example":"Das Haus steht am See.",'
    '"collocations":["ein großes Haus"]}],'
    '"register":"neutral","usage_note":null}]}'
)

SHAPE = (
    '{"import_words":[{"term":string,"pronunciation":string,'
    '"part_of_speech":"Substantiv|Verb|Adjektiv|...",'
    '"article":"der|die|das" (nouns),"gender":"masculine|feminine|neuter" (nouns),'
    '"plural_or_forms":{"plural":string} (when known),'
    '"senses":[{"definition":string,"translation":string,"example":string,"collocations":[...]}]}]} '
    "with 8-20 entries"
)

SHAPE_HINT = (
    '{"import_words":[{"term":"Haus","pronunciation":"[haʊ̯s]","part_of_speech":"Substantiv",'
    '"article":"das","gender":"neuter",'
    '"senses":[{"definition":"...","translation":"...","example":"..."}]}]}'
)


def build(target_language: str, native_language: str, source: str) -> str:
    return build_module_prompt(
        target_language=target_language,
        native_language=native_language,
        source=source,
        style=STYLE,
        shape=SHAPE,
        extra=(
            "Definitions and examples in German. translation mandatory in learner native "
            "language. Nouns must include article + gender."
        ),
    )
