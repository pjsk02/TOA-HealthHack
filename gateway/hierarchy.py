"""
Simulated clinical generalization hierarchy for MedFind discovery rollups.

This is a **faked SNOMED-style lookup** — a plain hand-written dict of
specific clinical labels → ordered coarser parents. It is NOT a real
terminology service, ontology reasoner, or SNOMED CT integration. The point
for the demo: when a specific cohort is too small to release under
k-anonymity, we can re-ask the same hospital at a coarser semantic level
and report that larger (safer) count instead of going silent.
"""

from __future__ import annotations

from typing import Optional

# specific label -> [next-coarser, ..., broadest]
# Order is important: index 0 is the first generalization step.
HIERARCHY: dict[str, list[str]] = {
    # CNS / brain neoplasm family (demo core)
    "glioma": ["low-grade glioma", "CNS neoplasm", "neoplasm"],
    "astrocytoma": ["low-grade glioma", "CNS neoplasm", "neoplasm"],
    "glioblastoma": ["high-grade glioma", "CNS neoplasm", "neoplasm"],
    "oligodendroglioma": ["low-grade glioma", "CNS neoplasm", "neoplasm"],
    "pilocytic astrocytoma": ["low-grade glioma", "CNS neoplasm", "neoplasm"],
    "medulloblastoma": ["CNS neoplasm", "neoplasm"],
    "ependymoma": ["CNS neoplasm", "neoplasm"],
    "craniopharyngioma": ["CNS neoplasm", "neoplasm"],
    "germinoma": ["CNS neoplasm", "neoplasm"],
    "pineoblastoma": ["CNS neoplasm", "neoplasm"],
    "meningioma": ["CNS neoplasm", "neoplasm"],
    "schwannoma": ["CNS neoplasm", "neoplasm"],
    "adenoma": ["neoplasm"],
    "metastasis": ["neoplasm"],
    "tumor": ["neoplasm"],
    "mass": ["neoplasm"],
    "lesion": ["neoplasm"],
    "growth": ["neoplasm"],
    "cancer": ["neoplasm"],
    "carcinoma": ["neoplasm"],
    "malignant": ["neoplasm"],
    "malignancy": ["neoplasm"],
    "low-grade glioma": ["CNS neoplasm", "neoplasm"],
    "high-grade glioma": ["CNS neoplasm", "neoplasm"],
    "CNS neoplasm": ["neoplasm"],
}

# Map each rollup *level label* to concrete Diagnosis-matching search terms.
# Broader levels deliberately include more umbrella vocabulary so the
# re-query can grow the cohort. These strings are chosen to hit real free
# text in data/{bch,mgh,bwh}_data.json — not SNOMED codes.
LEVEL_SEARCH_TERMS: dict[str, list[str]] = {
    "low-grade glioma": [
        "glioma", "astrocytoma", "low-grade", "pilocytic", "oligodendroglioma",
    ],
    "high-grade glioma": [
        "glioma", "glioblastoma", "high-grade", "malignant", "astrocytoma",
    ],
    "CNS neoplasm": [
        "tumor", "neoplasm", "glioma", "astrocytoma", "glioblastoma",
        "meningioma", "medulloblastoma", "ependymoma", "schwannoma",
    ],
    "neoplasm": [
        "tumor", "neoplasm", "mass", "lesion", "cancer", "malignant",
        "carcinoma", "growth", "malignancy",
    ],
}


def get_parents(term: str) -> list[str]:
    """Return the ordered coarser parents for `term` (case-insensitive)."""
    if not term:
        return []
    return list(HIERARCHY.get(term.lower().strip(), []))


def next_coarser_from_expanded(expanded: dict) -> Optional[dict]:
    """Given expand_terms() output, return the next-coarser re-query pack.

    Returns:
        {
          "terms": [...],          # search terms for node /api/search
          "rollup_level": str,     # human label of the coarser level
        }
        or None if no generalization step is available from the input terms.

    Policy: among input terms that have hierarchy parents, pick the
    *most specific* term (longest parent chain) and take its first parent
    as the next rollup level. One step only — the gateway does a single
    extra fan-out round, no recursive climb.
    """
    terms = list(expanded.get("terms") or [])
    best_term: str | None = None
    best_parents: list[str] = []

    for raw in terms:
        key = str(raw).lower().strip()
        parents = get_parents(key)
        if not parents:
            continue
        # Prefer the term with the deepest hierarchy (most specific).
        if best_term is None or len(parents) > len(best_parents):
            best_term = key
            best_parents = parents

    if not best_parents:
        return None

    rollup_level = best_parents[0]
    search_terms = list(LEVEL_SEARCH_TERMS.get(rollup_level, [rollup_level]))
    # Always include the level label itself in case it appears in free text.
    if rollup_level.lower() not in {t.lower() for t in search_terms}:
        search_terms.insert(0, rollup_level)

    return {
        "terms": search_terms,
        "rollup_level": rollup_level,
    }
