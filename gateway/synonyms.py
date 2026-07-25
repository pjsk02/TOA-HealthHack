"""Hand-written medical synonym dictionary for MedFind's term-expansion search.

This dictionary IS the semantic-search deliverable for the hackathon freeze
(PRD section 5) -- no LLM or embeddings. Coverage is tuned against the actual
`Diagnosis` free-text in data/{bch,mgh,bwh}_data.json so expanded terms
produce real keyword hits, not just plausible-looking synonyms.

Expansion is DIRECTED, not a symmetric synonym graph: SYNONYMS[key] lists
what a query for `key` should also search for. Broad/umbrella concepts
(tumor, neoplasm, mass, lesion, cancer) intentionally expand wide, including
into each other -- that breadth is what the "tumor -> neoplasm, glioma,
astrocytoma, mass, lesion" example in the PRD asks for. Specific subtypes
(glioma, meningioma, medulloblastoma, ...) expand only into their own close
relatives plus "tumor"/"neoplasm", deliberately WITHOUT "mass"/"lesion":
those two words are common in negation phrases ("no mass effect", "no
evidence of a lesion") throughout the corpus, so pulling them into a precise
query like "glioma" reintroduces false positives and defeats small-cohort
narrowing (see the "low-grade glioma, under age 3" demo query).
"""

SYNONYMS: dict[str, list[str]] = {
    # --- Neoplasm / tumor family (BRAIN) -- the demo's core vocabulary ---
    "tumor": ["neoplasm", "glioma", "astrocytoma", "mass", "lesion", "growth"],
    "neoplasm": ["tumor", "mass", "lesion", "growth", "malignant", "malignancy"],
    "mass": ["lesion", "tumor", "neoplasm", "growth"],
    "lesion": ["mass", "tumor"],
    "cancer": ["carcinoma", "malignant", "malignancy", "neoplasm", "tumor"],
    "carcinoma": ["cancer", "malignant", "neoplasm"],
    "malignant": ["malignancy", "cancer", "carcinoma", "neoplasm"],

    # Specific subtypes: precise expansion only -- no "mass"/"lesion" noise.
    "glioma": ["astrocytoma", "glioblastoma", "oligodendroglioma", "tumor", "neoplasm"],
    "astrocytoma": ["glioma", "glioblastoma", "pilocytic astrocytoma", "tumor", "neoplasm"],
    "glioblastoma": ["astrocytoma", "glioma", "tumor", "neoplasm", "malignant"],
    "oligodendroglioma": ["glioma", "astrocytoma", "tumor", "neoplasm"],
    "medulloblastoma": ["tumor", "neoplasm"],
    "ependymoma": ["tumor", "neoplasm"],
    "craniopharyngioma": ["suprasellar mass", "tumor", "neoplasm"],
    "germinoma": ["pineal mass", "germ cell tumor", "tumor", "neoplasm"],
    "pineoblastoma": ["pineal mass", "tumor", "neoplasm", "malignant"],
    "meningioma": ["tumor", "neoplasm"],
    "schwannoma": ["tumor", "neoplasm"],
    "adenoma": ["tumor", "neoplasm"],
    "metastasis": ["metastatic", "malignant", "tumor", "neoplasm"],
    "cyst": ["cystic"],
    "nodule": ["nodular"],

    # Grade/behavior qualifiers left unexpanded on purpose: "benign" and
    # "grade i/ii" show up throughout the corpus in unrelated contexts
    # (e.g. "benign expansion of the subarachnoid spaces", hemorrhage
    # grading), so expanding them would reintroduce the same false-positive
    # problem as "mass"/"lesion" above.
    "low-grade": [],
    "high-grade": ["malignant"],

    # --- Brain / neuro structural (non-tumor) ---
    "hydrocephalus": ["ventriculomegaly", "ventricular dilation"],
    "ventriculomegaly": ["hydrocephalus", "ventricular dilation"],
    "seizure": ["epilepsy", "epileptic", "epileptogenic"],
    "epilepsy": ["seizure", "epileptic", "epileptogenic"],
    "hemorrhage": ["bleed", "hemorrhagic"],
    "infarct": ["ischemia", "ischemic", "stroke"],
    "demyelinating": ["demyelination", "adem"],

    # --- Cardiac (HEART) ---
    "cardiomyopathy": ["myocardial"],
    "arrhythmia": ["dysrhythmia"],
    "congenital": ["congenital anomaly", "congenital malformation"],

    # --- Fetal (FETAL) ---
    "encephalocele": ["neural tube defect"],
    "gestation": ["gestational", "prenatal"],
}


def expand_term(term: str) -> set[str]:
    """Return the synonym family for one clinical term (case-insensitive).

    Looks up `term` as a dictionary key and returns {term} plus its listed
    expansions. Falls back to {term} unchanged if it isn't a recognized key,
    so unrecognized-but-plausible clinical words still pass through as
    literal search terms instead of being silently dropped.
    """
    key = term.lower()
    return {term, *SYNONYMS.get(key, [])}
