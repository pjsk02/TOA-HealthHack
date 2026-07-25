"""Query parsing + term expansion for MedFind discovery search (PRD section 7).

expand_terms() turns a researcher's free-text query into the structured,
synonym-expanded shape the gateway fans out to hospital nodes with. Body
part / modality / pediatric / age are detected with a small keyword parser;
clinical vocabulary is expanded via the hand-written dictionary in
synonyms.py. No LLM or embeddings -- the dictionary is the deliverable.
"""

import re

try:
    from .synonyms import expand_term
except ImportError:
    from synonyms import expand_term  # type: ignore

# BCH (the only pediatric node) covers ages 0-21 (PRD section 9), so an
# explicit age ceiling in that range implies a pediatric-oriented query even
# without the word "pediatric" -- e.g. "under age 3" alone.
PEDIATRIC_AGE_THRESHOLD_YEARS = 21

BODY_PART_KEYWORDS: dict[str, list[str]] = {
    "BRAIN": ["brain", "cerebral", "cranial", "neuro", "head", "intracranial"],
    "HEART": ["heart", "cardiac", "cardio"],
    "FETAL": ["fetal", "fetus", "prenatal", "obstetric"],
}

MODALITY_KEYWORDS: dict[str, list[str]] = {
    "MR": ["mri", "magnetic resonance", "mr"],
    "CT": ["cat scan", "computed tomography", "ct"],
}

PEDIATRIC_KEYWORDS = [
    "pediatric", "paediatric", "child", "children", "infant", "infants",
    "neonate", "neonatal", "newborn", "kids", "juvenile", "toddler",
]

HOSPITAL_NAMES = {"bch", "mgh", "bwh"}

STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "for", "and", "or", "only", "with",
    "to", "is", "are", "at", "by", "from", "under", "over", "age", "aged",
    "years", "year", "yrs", "yr", "old", "than", "less", "more", "younger",
    "below", "above", "scan", "scans", "study", "studies", "show", "find",
    "search", "me", "please",
}

AGE_PATTERNS = [
    re.compile(r"under\s+(?:the\s+)?age\s+(?:of\s+)?(\d+)", re.I),
    re.compile(r"younger\s+than\s+(\d+)", re.I),
    re.compile(r"less\s+than\s+(\d+)", re.I),
    re.compile(r"below\s+(?:age\s+)?(\d+)", re.I),
    re.compile(r"under\s+(\d+)", re.I),
    re.compile(r"<\s*(\d+)", re.I),
    re.compile(r"age\s+(\d+)\s+(?:and\s+under|or\s+younger)", re.I),
]

_WORD_RE = re.compile(r"[a-z][a-z\-]*")


def _detect_first_match(text: str, keyword_map: dict[str, list[str]]) -> str | None:
    for label, keywords in keyword_map.items():
        for kw in keywords:
            if re.search(rf"\b{re.escape(kw)}\b", text):
                return label
    return None


def _detect_pediatric_keyword(text: str) -> bool:
    return any(re.search(rf"\b{kw}\b", text) for kw in PEDIATRIC_KEYWORDS)


def _detect_max_age_years(text: str) -> int | None:
    for pattern in AGE_PATTERNS:
        match = pattern.search(text)
        if match:
            return int(match.group(1))
    return None


def _noise_words() -> set[str]:
    noise = set(STOPWORDS) | HOSPITAL_NAMES | set(PEDIATRIC_KEYWORDS)
    for keywords in (*BODY_PART_KEYWORDS.values(), *MODALITY_KEYWORDS.values()):
        for kw in keywords:
            noise.update(kw.split())
    return noise


_NOISE_WORDS = _noise_words()


def _extract_clinical_terms(text: str) -> list[str]:
    candidates = [w for w in _WORD_RE.findall(text) if w not in _NOISE_WORDS]

    expanded: list[str] = []
    seen: set[str] = set()
    for word in candidates:
        for term in sorted(expand_term(word)):
            if term not in seen:
                seen.add(term)
                expanded.append(term)
    return expanded


def expand_terms(query: str) -> dict:
    """'pediatric brain tumor MRI' ->
    {terms:[...], body_part:'BRAIN', modality:'MR', pediatric:True,
     max_age_years:<int|None>}
    """
    text = query.lower()

    max_age_years = _detect_max_age_years(text)
    pediatric = _detect_pediatric_keyword(text) or (
        max_age_years is not None and max_age_years <= PEDIATRIC_AGE_THRESHOLD_YEARS
    )

    return {
        "terms": _extract_clinical_terms(text),
        "body_part": _detect_first_match(text, BODY_PART_KEYWORDS),
        "modality": _detect_first_match(text, MODALITY_KEYWORDS),
        "pediatric": pediatric,
        "max_age_years": max_age_years,
    }
