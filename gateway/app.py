"""
MedFind gateway orchestration service (:8000).

Owns POST /search (term expansion + fan-out + k-suppression) and
POST /retrieve (token-forwarding proxy). Imports section-7 module
contracts when available; otherwise uses thin local stubs.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Section-7 module imports (drop-in when C/D/E land)
# ---------------------------------------------------------------------------

try:
    from .semantic import expand_terms
except ImportError:
    try:
        from semantic import expand_terms  # type: ignore
    except ImportError:

        def expand_terms(query: str) -> dict:
            """Stub — 'pediatric brain tumor MRI' -> terms + filters."""
            q = (query or "").lower()
            terms = ["tumor", "neoplasm", "glioma", "astrocytoma", "mass", "lesion"]
            body_part = "BRAIN" if "brain" in q else None
            modality = "MR" if ("mri" in q or " mr" in f" {q}") else None
            pediatric = "pediatric" in q or "paediatric" in q
            return {
                "terms": terms,
                "body_part": body_part,
                "modality": modality,
                "pediatric": pediatric,
            }


try:
    from .privacy import apply_suppression, privatize_count
except ImportError:
    try:
        from privacy import apply_suppression, privatize_count  # type: ignore
    except ImportError:

        def apply_suppression(
            hospital_counts: list[dict],
            k: int = 5,
            role: str = "anonymous",
            epsilon: float | None = None,
        ) -> list[dict]:
            """Stub — replace any count < k with the safe message;
            anonymous sees network-total only (empty per-hospital list)."""
            SAFE = (
                "Result suppressed to protect patient privacy. "
                "Cohort too small to release a count."
            )
            if role == "anonymous":
                return []

            results: list[dict] = []
            for item in hospital_counts:
                hospital = item.get("hospital") or item.get("node")
                count = int(item.get("count", 0))
                if count < k:
                    results.append({"hospital": hospital, "display": SAFE})
                else:
                    results.append({"hospital": hospital, "count": count})
            return results

        def privatize_count(
            count: int, k: int = 5, epsilon: float | None = None
        ) -> int:
            return int(count)


try:
    from .hierarchy import next_coarser_from_expanded
except ImportError:
    try:
        from hierarchy import next_coarser_from_expanded  # type: ignore
    except ImportError:

        def next_coarser_from_expanded(expanded: dict) -> dict | None:
            return None


try:
    from .auth import (
        login,
        list_users,
        require_network_admin,
        signup,
        update_user,
        verify_token,
    )
except ImportError:
    try:
        from auth import (  # type: ignore
            login,
            list_users,
            require_network_admin,
            signup,
            update_user,
            verify_token,
        )
    except ImportError:

        def verify_token(token: str) -> dict | None:
            if not token:
                return None
            return {
                "role": "network_admin",
                "org": "demo",
                "irb_approved": True,
                "hospitals": ["BCH", "MGH", "BWH"],
                "username": "admin",
            }

        def login(username: str, password: str) -> dict:
            return {
                "token": f"stub-token-for-{username}",
                "username": username,
                "role": "network_admin",
                "org": "demo",
                "hospitals": ["BCH", "MGH", "BWH"],
            }

        def signup(username: str, password: str, org: str | None = None) -> dict:
            return {
                "username": username,
                "role": "affiliated",
                "org": org or "Independent",
                "irb_approved": False,
                "hospitals": [],
            }

        def list_users() -> list:
            return []

        def update_user(username: str, **kwargs) -> dict:
            return {"username": username, **kwargs}

        def require_network_admin(claims: dict | None) -> None:
            if not claims or claims.get("role") != "network_admin":
                raise PermissionError("admin_required")


# ---------------------------------------------------------------------------
# Node registry
# ---------------------------------------------------------------------------

NODES: dict[str, str] = {
    "BCH": "http://127.0.0.1:8001",
    "MGH": "http://127.0.0.1:8002",
    "BWH": "http://127.0.0.1:8003",
}

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="MedFind Gateway",
    description="Federated DICOM discovery orchestration (:8000).",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str = Field(..., examples=["admin"])
    password: str = Field(..., examples=["admin"])


class SignupRequest(BaseModel):
    username: str = Field(..., examples=["alice"])
    password: str = Field(..., examples=["alice123"])
    org: Optional[str] = Field(default=None, examples=["MIT"])


class AdminUserUpdate(BaseModel):
    role: Optional[str] = Field(default=None, examples=["irb_approved"])
    hospitals: Optional[list[str]] = Field(
        default=None, examples=[["BCH", "MGH"]]
    )
    org: Optional[str] = None
    irb_approved: Optional[bool] = None


class SearchRequest(BaseModel):
    query: str = Field(..., examples=["pediatric brain tumor MRI"])
    max_age_years: Optional[int] = Field(default=None, examples=[3])
    epsilon: Optional[float] = Field(
        default=None,
        examples=[0.5],
        description="Optional ε for Laplace DP noise on surviving counts.",
    )


class RetrieveRequest(BaseModel):
    hospital: str = Field(..., examples=["BCH"])
    study_id: str = Field(..., examples=["BR-7721"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _claims_from_auth(authorization: Optional[str]) -> dict | None:
    token = _extract_bearer(authorization)
    if not token:
        return None
    return verify_token(token)


def _role_from_token(authorization: Optional[str]) -> str:
    claims = _claims_from_auth(authorization)
    if not claims:
        return "anonymous"
    return str(claims.get("role") or "anonymous")


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    # Allow raw token without Bearer prefix for local testing.
    return authorization.strip() or None


async def _fanout_search(
    client: httpx.AsyncClient,
    name: str,
    base_url: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    # NOTE: hospital node /api/search responds with {"node": ..., "count": ...},
    # but the privacy.apply_suppression() contract (section 7) expects each row
    # keyed as {"hospital": ..., "count": ...}. Normalize here.
    try:
        resp = await client.post(f"{base_url}/api/search", json=payload)
        if resp.status_code != 200:
            return {"hospital": name, "count": 0}
        data = resp.json()
        return {
            "hospital": data.get("node", name),
            "count": int(data.get("count", 0)),
        }
    except (httpx.HTTPError, ValueError, TypeError):
        return {"hospital": name, "count": 0}


def _network_total(raw_counts: list[dict], k: int = 5) -> str:
    """Sum raw counts; append '+' when any cohort was suppressed (or always
    use floor-style display consistent with the PRD example)."""
    total = sum(int(c.get("count", 0)) for c in raw_counts)
    any_small = any(int(c.get("count", 0)) < k for c in raw_counts)
    if any_small:
        # Exclude suppressed cohorts from the visible sum (PRD: 32+8 -> "40+")
        visible = sum(
            int(c.get("count", 0))
            for c in raw_counts
            if int(c.get("count", 0)) >= k
        )
        return f"{visible}+"
    return str(total)


def _strip_pii(obj: Any) -> Any:
    """Defense in depth: never let raw PII fields leak through the gateway."""
    PII_KEYS = {"PatientName", "PatientID", "PatientBirthDate"}
    if isinstance(obj, dict):
        return {
            k: _strip_pii(v)
            for k, v in obj.items()
            if k not in PII_KEYS
        }
    if isinstance(obj, list):
        return [_strip_pii(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health():
    return {"status": "healthy", "service": "gateway"}


@app.post("/signup")
def signup_route(body: SignupRequest):
    """Create an affiliated user with empty hospital grants."""
    try:
        user = signup(body.username, body.password, body.org)
    except ValueError as exc:
        code = str(exc)
        if code == "taken":
            raise HTTPException(status_code=409, detail="Username already taken.") from exc
        if code == "reserved":
            raise HTTPException(status_code=400, detail="Username is reserved.") from exc
        raise HTTPException(
            status_code=400, detail="Username and password are required."
        ) from exc
    return {"ok": True, "user": user}


@app.post("/login")
def login_route(body: LoginRequest):
    """Password login → JWT with {role, org, irb_approved, hospitals}."""
    try:
        return login(body.username, body.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=401, detail="Invalid username or password."
        ) from exc


@app.get("/admin/users")
def admin_list_users(authorization: Optional[str] = Header(default=None)):
    claims = _claims_from_auth(authorization)
    try:
        require_network_admin(claims)
    except PermissionError as exc:
        raise HTTPException(
            status_code=403, detail="Network admin required."
        ) from exc
    return {"users": list_users()}


@app.patch("/admin/users/{username}")
def admin_update_user(
    username: str,
    body: AdminUserUpdate,
    authorization: Optional[str] = Header(default=None),
):
    claims = _claims_from_auth(authorization)
    try:
        require_network_admin(claims)
    except PermissionError as exc:
        raise HTTPException(
            status_code=403, detail="Network admin required."
        ) from exc

    try:
        user = update_user(
            username,
            role=body.role,
            hospitals=body.hospitals,
            org=body.org,
            irb_approved=body.irb_approved,
        )
    except ValueError as exc:
        code = str(exc)
        if code == "missing":
            raise HTTPException(status_code=404, detail="User not found.") from exc
        if code == "bad_role":
            raise HTTPException(status_code=400, detail="Invalid role.") from exc
        if code == "protect_admin":
            raise HTTPException(
                status_code=400, detail="Cannot demote the network admin account."
            ) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "user": user}


@app.post("/search")
async def search(
    body: SearchRequest,
    authorization: Optional[str] = Header(default=None),
):
    expanded = expand_terms(body.query)
    terms = list(expanded.get("terms") or [])
    role = _role_from_token(authorization)
    epsilon = body.epsilon
    k = 5

    payload: dict[str, Any] = {"terms": terms}
    if expanded.get("body_part"):
        payload["body_part"] = expanded["body_part"]
    if expanded.get("modality"):
        payload["modality"] = expanded["modality"]
    if body.max_age_years is not None:
        payload["max_age_years"] = body.max_age_years

    async with httpx.AsyncClient(timeout=10.0) as client:
        tasks = [
            _fanout_search(client, name, url, payload)
            for name, url in NODES.items()
        ]
        raw_counts = list(await asyncio.gather(*tasks))

        results = apply_suppression(
            raw_counts, k=k, role=role, epsilon=epsilon
        )

        # One-shot generalization rollup for hard-suppressed hospitals:
        # re-query that node at the next-coarser hierarchy level. If the
        # coarser true count meets k, replace silence with a rollup card.
        # No recursive climb — at most one extra fan-out round.
        coarser = next_coarser_from_expanded(expanded)
        if coarser and role != "anonymous":
            coarse_payload = dict(payload)
            coarse_payload["terms"] = list(coarser["terms"])
            rollup_level = str(coarser["rollup_level"])
            pediatric_prefix = (
                "pediatric " if expanded.get("pediatric") else ""
            )

            for idx, row in enumerate(results):
                if "display" not in row or "rollup_count" in row:
                    continue
                hospital = row.get("hospital")
                if not hospital or hospital not in NODES:
                    continue
                coarse_row = await _fanout_search(
                    client, hospital, NODES[hospital], coarse_payload
                )
                coarse_count = int(coarse_row.get("count", 0))
                if coarse_count < k:
                    continue
                shown = privatize_count(
                    coarse_count, k=k, epsilon=epsilon
                )
                results[idx] = {
                    "hospital": hospital,
                    "display": (
                        f"Too small at this level; {shown} cases at "
                        f"coarser level: {pediatric_prefix}{rollup_level}"
                    ),
                    "rollup_count": shown,
                    "rollup_level": rollup_level,
                }

    # Normalize hospital key in case a module returns "node"
    normalized: list[dict] = []
    for item in results:
        entry = dict(item)
        if "hospital" not in entry and "node" in entry:
            entry["hospital"] = entry.pop("node")
        normalized.append(entry)

    return {
        "query_expanded_to": terms,
        "results": normalized,
        "network_total": _network_total(raw_counts, k=k),
    }


@app.post("/retrieve")
async def retrieve(
    body: RetrieveRequest,
    authorization: Optional[str] = Header(default=None),
):
    hospital = body.hospital.upper().strip()
    if hospital not in NODES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown hospital '{body.hospital}'. "
            f"Valid: {', '.join(NODES)}",
        )

    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authorization Bearer token required for retrieve.",
        )

    claims = verify_token(token)
    if not claims:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token.",
        )

    granted = [str(h).upper() for h in (claims.get("hospitals") or [])]
    if hospital not in granted:
        return JSONResponse(
            status_code=403,
            content={
                "error": (
                    f"User not granted access to {hospital}. "
                    f"Granted hospitals: {', '.join(granted) or '(none)'}."
                )
            },
        )

    headers = {"Authorization": f"Bearer {token}"}
    url = f"{NODES[hospital]}/api/retrieve"
    payload = {"study_id": body.study_id}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Node {hospital} unreachable: {exc}",
            ) from exc

    # Return the node's status + body verbatim (minus any accidental PII).
    try:
        data = resp.json()
    except ValueError:
        return JSONResponse(status_code=resp.status_code, content={"raw": resp.text})

    return JSONResponse(status_code=resp.status_code, content=_strip_pii(data))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("gateway.app:app", host="0.0.0.0", port=8000, reload=False)
