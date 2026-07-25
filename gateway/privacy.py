"""
MedFind privacy engine — k-anonymity suppression + optional ε-differential privacy.

Judge-facing concepts (kept inline so the demo story is readable in the code):

- **k-anonymity / small-cell suppression**: a per-hospital cohort is only safe
  to describe with an exact count if it contains at least `k` individuals
  (default k=5). Below that, even a bare COUNT is an indirect identifier in a
  rare-disease setting ("4 kids under 3 with this glioma at BCH"). We replace
  the number with a redaction message — classic statistical disclosure control.

- **Differencing / reconstruction risk**: exact surviving counts still leak
  under overlapping queries (safe query A minus safe query B can reveal a
  single record). Laplace noise is a first-line mitigation; full protection
  needs a query budget / auditor (out of scope for this hackathon).

- **ε-differential privacy (Laplace mechanism)**: for a count query the
  global sensitivity Δ is 1 (one patient changes the answer by at most 1).
  We add noise ~ Laplace(0, b) with scale b = Δ/ε = 1/ε. Smaller ε ⇒ more
  privacy ⇒ more noise. This is *local to the released aggregate* (gateway
  privatizes the hospital-returned count); it is not a full global-DP system
  with a tracked privacy budget across queries.

- **Post-processing floor**: after noising we clamp the displayed count to
  be ≥ k so noise can never re-introduce a sub-threshold cell. True
  k-suppression runs on the *true* count BEFORE noise is added.
"""

from __future__ import annotations

import math
import random
from typing import Optional

SAFE_MESSAGE = (
    "Result suppressed to protect patient privacy. "
    "Cohort too small to release a count."
)

# Roles allowed to see a per-hospital breakdown.
BREAKDOWN_ROLES = {"affiliated", "irb_approved", "network_admin"}

# Count-query sensitivity for the Laplace mechanism (one patient ±1).
SENSITIVITY = 1.0


def _laplace_sample(scale: float) -> float:
    """Draw from Laplace(0, scale) via the inverse-CDF transform (stdlib only).

    If U ~ Uniform(-1/2, 1/2), then
        X = -b * sgn(U) * ln(1 - 2|U|)
    is Laplace(0, b). Avoids any non-stdlib dependency.
    """
    # Exclude the exact endpoints so ln(1 - 2|U|) is defined.
    u = random.random() - 0.5
    while u == 0.0:
        u = random.random() - 0.5
    return -scale * math.copysign(1.0, u) * math.log(1.0 - 2.0 * abs(u))


def privatize_count(
    count: int,
    k: int = 5,
    epsilon: Optional[float] = None,
) -> int:
    """Apply ε-DP Laplace noise to a surviving (already ≥ k) count.

    Floor the result at `k` so post-processing never surfaces a sub-threshold
    cell. If epsilon is None, return the true count unchanged.
    """
    if epsilon is None or epsilon <= 0:
        return int(count)
    scale = SENSITIVITY / float(epsilon)
    noised = int(round(count + _laplace_sample(scale)))
    return max(k, noised)


def apply_suppression(
    hospital_counts: list[dict],
    k: int = 5,
    role: str = "anonymous",
    epsilon: Optional[float] = None,
) -> list[dict]:
    """k-anonymity small-cell suppression (+ optional ε-DP noise).

    Backward-compatible with the gateway call site:
        apply_suppression(raw_counts, k=5, role=role[, epsilon=epsilon])

    Args:
        hospital_counts: [{"hospital": "BCH", "count": 32}, ...] from fan-out.
        k: small-cell / k-anonymity threshold.
        role: "anonymous" | "affiliated" | "irb_approved".
        epsilon: if set, Laplace-noise surviving counts (scale = 1/ε), floor at k.

    Returns:
        For affiliated / irb_approved: one row per hospital, either
          {"hospital", "count"} or {"hospital", "display": SAFE_MESSAGE}.
        For anonymous (or unknown role): [] — no per-hospital breakdown;
          the gateway's top-level `network_total` is the only aggregate shown.
    """
    if role not in BREAKDOWN_ROLES:
        # Network-total-only: withhold which hospitals hold data and how
        # counts are split. Gateway still emits `network_total` separately.
        return []

    results: list[dict] = []
    for row in hospital_counts:
        hospital = row.get("hospital") or row.get("node")
        count = int(row.get("count", 0))

        # True k-anonymity check FIRST — never decide suppression on a noised value.
        if count < k:
            results.append({"hospital": hospital, "display": SAFE_MESSAGE})
            continue

        results.append({
            "hospital": hospital,
            "count": privatize_count(count, k=k, epsilon=epsilon),
        })
    return results
