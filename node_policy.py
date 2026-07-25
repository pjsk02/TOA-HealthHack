"""
Per-hospital retrieval policy (MedFind PRD section 7 / section 4).

Each node owns and evaluates its OWN policy — the hospital decides, not the
gateway. Policies deliberately differ across hospitals so a researcher (e.g.
Dr. Jorgenson, role="irb_approved") can be permitted at one site and denied
at another. The gateway never sees or influences this table; it only forwards
the caller's token.
"""

Role = str  # "anonymous" | "affiliated" | "irb_approved"
Decision = str  # "allow" | "deny"

# NODE_POLICIES[node_name][role] -> "allow" | "deny"
NODE_POLICIES: dict[str, dict[Role, Decision]] = {
    "BCH": {
        "irb_approved": "allow",
        "affiliated": "deny",
        "anonymous": "deny",
    },
    "MGH": {
        "irb_approved": "deny",
        "affiliated": "deny",
        "anonymous": "deny",
    },
    "BWH": {
        "irb_approved": "allow",
        "affiliated": "allow",
        "anonymous": "deny",
    },
}

# Fail closed: any node/role combination not explicitly listed above is denied.
DEFAULT_POLICY: dict[Role, Decision] = {
    "irb_approved": "deny",
    "affiliated": "deny",
    "anonymous": "deny",
}


def get_policy(node_name: str) -> dict[Role, Decision]:
    """Return the policy dict for a given node, defaulting closed if unknown."""
    return NODE_POLICIES.get(node_name.upper(), DEFAULT_POLICY)


def is_allowed(node_name: str, role: str) -> bool:
    """True iff `role` may retrieve records from `node_name` per its local policy."""
    policy = get_policy(node_name)
    return policy.get(role, "deny") == "allow"
