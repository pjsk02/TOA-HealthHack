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
    from .privacy import apply_suppression
except ImportError:
    try:
        from privacy import apply_suppression  # type: ignore
    except ImportError:

        def apply_suppression(
            hospital_counts: list[dict],
            k: int = 5,
            role: str = "anonymous",
        ) -> list[dict]:
            """Stub — replace any count < k with the safe message;
            anonymous sees network-total only (empty per-hospital list)."""
            SAFE = (
                "Cohort too small to display safely (fewer than 5 records)."
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


try:
    from .auth import login, verify_token
except ImportError:
    try:
        from auth import login, verify_token  # type: ignore
    except ImportError:

        def verify_token(token: str) -> dict | None:
            """Stub — returns role claims or None if invalid."""
            if not token:
                return None
            # Accept any non-empty token as IRB-approved for local wiring.
            return {
                "role": "irb_approved",
                "org": "demo",
                "irb_approved": True,
            }

        def login(username: str) -> dict:
            """Stub — mirrors auth.login()'s {"token": ...} response shape."""
            return {"token": f"stub-token-for-{username}"}


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
    username: str = Field(..., examples=["jorgenson"])


class SearchRequest(BaseModel):
    query: str = Field(..., examples=["pediatric brain tumor MRI"])
    max_age_years: Optional[int] = Field(default=None, examples=[3])


class RetrieveRequest(BaseModel):
    hospital: str = Field(..., examples=["BCH"])
    study_id: str = Field(..., examples=["BR-7721"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _role_from_token(authorization: Optional[str]) -> str:
    token = _extract_bearer(authorization)
    if not token:
        return "anonymous"
    claims = verify_token(token)
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


@app.post("/login")
def login_route(body: LoginRequest):
    """Issue a signed token carrying {role, org, irb_approved} for `username`.
    Unknown usernames resolve to the anonymous role (see auth.USERS)."""
    return login(body.username)


@app.post("/search")
async def search(
    body: SearchRequest,
    authorization: Optional[str] = Header(default=None),
):
    expanded = expand_terms(body.query)
    terms = list(expanded.get("terms") or [])
    role = _role_from_token(authorization)

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
        raw_counts = await asyncio.gather(*tasks)

    counts_list = list(raw_counts)
    results = apply_suppression(counts_list, k=5, role=role)
    # Normalize hospital key in case a real privacy module returns "node"
    normalized: list[dict] = []
    for item in results:
        entry = dict(item)
        if "hospital" not in entry and "node" in entry:
            entry["hospital"] = entry.pop("node")
        normalized.append(entry)

    return {
        "query_expanded_to": terms,
        "results": normalized,
        "network_total": _network_total(counts_list, k=5),
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
