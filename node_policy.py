"""
Per-hospital retrieval policy (MedFind PRD section 7 / section 4).

Each node owns and evaluates its OWN policy — the hospital decides, not the
gateway. Policies deliberately differ across hospitals so a researcher can be
permitted at one site and denied at another even with a grant. The gateway
also enforces the user's hospital allowlist before forwarding retrieve calls.

network_admin is allowed at every site (network master).
"""

Role = str  # "anonymous" | "affiliated" | "irb_approved" | "network_admin"
Decision = str  # "allow" | "deny"

# NODE_POLICIES[node_name][role] -> "allow" | "deny"
NODE_POLICIES: dict[str, dict[Role, Decision]] = {
    "BCH": {
        "network_admin": "allow",
        "irb_approved": "allow",
        "affiliated": "allow",
        "anonymous": "deny",
    },
    "MGH": {
        "network_admin": "allow",
        "irb_approved": "allow",
        "affiliated": "deny",
        "anonymous": "deny",
    },
    "BWH": {
        "network_admin": "allow",
        "irb_approved": "allow",
        "affiliated": "allow",
        "anonymous": "deny",
    },
}

# Fail closed: any node/role combination not explicitly listed above is denied.
DEFAULT_POLICY: dict[Role, Decision] = {
    "network_admin": "deny",
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
