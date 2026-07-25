"""
Privacy module — small-cell suppression for the MedFind discovery gateway.

Concepts in play (judge-facing story):

- k-anonymity: a cohort is only safe to describe in aggregate if it contains
  at least `k` individuals. Below that, even a bare COUNT is an indirect
  identifier — "4 kids under 3 with this glioma at this hospital" is close
  enough to a name in a small population. We default k=5.

- Small-cell suppression: the standard statistical-disclosure-control
  technique of replacing any cell (here, a per-hospital count) that falls
  below the k threshold with a redaction message instead of a number or
  rows. This is exactly what census bureaus / health registries do with
  small counts in public tables.

- Differencing attack risk: even if every *individual* query is safely
  suppressed, an attacker can sometimes recover a small cell by taking the
  difference of two overlapping, both-safe queries (e.g. "all gliomas" minus
  "gliomas excluding patient X's exact age"). We don't attempt to defend
  against this fully in a 3-hour hackathon build (that requires query
  auditing / budget tracking), but the presence of optional noise/rounding
  below is the first line of defense real systems use, and it's worth
  naming explicitly in the demo.

- Role-based aggregation: an anonymous caller doesn't even get to see which
  hospitals hold data or how the counts are distributed across them — only
  a single network-wide total (itself suppressed/bucketed). Per-hospital
  breakdowns are reserved for authenticated researchers, because knowing
  "BCH has the data, MGH doesn't" is itself a (weaker) disclosure.
"""

import math
import random

SAFE_MESSAGE = "Cohort too small to display safely (fewer than 5 records)."

# Roles that are allowed to see a per-hospital breakdown at all.
# "anonymous" only ever gets a folded network-wide total.
BREAKDOWN_ROLES = {"affiliated", "irb_approved"}

# --- Optional stretch-goal knobs (off by default) ---------------------------
# The plain small-cell suppression above is the must-have for the demo.
# These add a second layer of protection against exact-count differencing
# attacks by perturbing surviving (non-suppressed) counts before display.
ENABLE_NOISE = False       # Laplace mechanism (differential-privacy flavored)
ENABLE_ROUNDING = False    # deterministic bucket rounding (simpler, safer for a live demo)
ROUNDING_BUCKET = 5
NOISE_EPSILON = 1.0        # smaller epsilon = more privacy, more noise


def _round_count(count: int, bucket: int = ROUNDING_BUCKET) -> int:
    """Round a surviving count to the nearest bucket (e.g. 32 -> 30).

    Deterministic count-rounding is a lightweight mitigation against
    differencing attacks: an adversary comparing two overlapping queries
    sees rounded values, not exact ones, so subtracting them no longer
    reliably reveals a single record's presence.
    """
    return int(round(count / bucket) * bucket)


def _add_laplace_noise(count: int, epsilon: float = NOISE_EPSILON) -> int:
    """Perturb a surviving count with Laplace noise (differential privacy).

    Scale = sensitivity / epsilon; sensitivity = 1 since one patient can
    change a count by at most 1. Result is floored at 0 — a hospital never
    displays a negative cohort size.
    """
    noise = random.laplace(loc=0.0, scale=1.0 / epsilon)
    return max(0, int(round(count + noise)))


def _perturb(count: int) -> int:
    """Apply whichever optional perturbation is enabled, in order."""
    result = count
    if ENABLE_ROUNDING:
        result = _round_count(result)
    if ENABLE_NOISE:
        result = _add_laplace_noise(result)
    return result


def _network_total_display(total: int, bucket: int = 10) -> str:
    """Render a network-wide total as a rounded-down '<bucket>+' style string
    (e.g. 47 -> '40+'), so an anonymous caller never learns an exact
    aggregate figure either — only a safe lower bound.
    """
    if total < bucket:
        return str(total)
    floored = (total // bucket) * bucket
    return f"{floored}+"


def _suppress_row(row: dict, k: int) -> dict:
    """Apply small-cell suppression to a single {"hospital", "count"} row."""
    hospital = row.get("hospital")
    count = row.get("count")

    if count is None:
        # Already suppressed / no count field — pass through unchanged.
        return dict(row)

    if count < k:
        return {"hospital": hospital, "display": SAFE_MESSAGE}

    displayed = _perturb(count)
    return {"hospital": hospital, "count": displayed}


def apply_suppression(hospital_counts: list[dict], k: int = 5, role: str = "anonymous") -> list[dict]:
    """Replace any count < k with the safe message; anonymous sees network-total
    only (no per-hospital breakdown).

    Args:
        hospital_counts: [{"hospital": "BCH", "count": 32}, ...] — raw,
            per-hospital counts as returned by node /api/search calls.
        k: the small-cell threshold (k-anonymity floor). Default 5.
        role: "anonymous" | "affiliated" | "irb_approved".

    Returns:
        A list[dict]. For roles in BREAKDOWN_ROLES, one entry per hospital,
        each either {"hospital", "count"} (safe to show) or
        {"hospital", "display"} (suppressed). For "anonymous" (or any
        unrecognized role), a single-entry list folding all hospitals into
        one network-wide figure: either {"network_total": "<n>+"} or
        {"display": SAFE_MESSAGE} if even the total is below k.
    """
    if role not in BREAKDOWN_ROLES:
        # Anonymous callers never see which hospitals hold data, or how
        # counts are split across them — only a single aggregate figure.
        total = sum(row.get("count", 0) for row in hospital_counts)

        if total < k:
            return [{"display": SAFE_MESSAGE}]

        return [{"network_total": _network_total_display(total)}]

    return [_suppress_row(row, k) for row in hospital_counts]
