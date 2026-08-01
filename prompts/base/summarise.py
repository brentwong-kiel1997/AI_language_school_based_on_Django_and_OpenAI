"""Prompt for chunking long transcripts before module generation."""

STYLE = (
    "Return JSON only with keys keywords, grammar_points, question_clues, "
    "translation_clues, level_evidence, summary. Summarise this transcript "
    "chunk without inventing facts:"
)


def build(chunk: str) -> str:
    return f"{STYLE}\n{chunk}"
