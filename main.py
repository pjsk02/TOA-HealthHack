import base64
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from deidentify import deidentify_study, parse_age_years
from models import StudyRecord
from node_policy import is_allowed

NODE_DATA_MAP = {
    "BCH": "data/bch_data.json",
    "MGH": "data/mgh_data.json",
    "BWH": "data/bwh_data.json",
}

HOSPITAL_NODE = os.environ.get("HOSPITAL_NODE", "").upper()

if HOSPITAL_NODE not in NODE_DATA_MAP:
    print(
        f"WARNING: HOSPITAL_NODE='{os.environ.get('HOSPITAL_NODE', '')}' "
        f"is not set or invalid. Valid values: {', '.join(NODE_DATA_MAP)}. "
        f"Defaulting to BCH.",
        file=sys.stderr,
    )
    HOSPITAL_NODE = "BCH"

data_path = Path(__file__).parent / NODE_DATA_MAP[HOSPITAL_NODE]

with open(data_path) as f:
    _raw = json.load(f)

studies: list[StudyRecord] = [StudyRecord(**record) for record in _raw]

app = FastAPI(
    title=f"Hospital Node — {HOSPITAL_NODE}",
    description="Single-node hospital boilerplate for the Open Accelerator Healthcare Hackathon.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "healthy", "node": HOSPITAL_NODE}


@app.get("/api/studies", response_model=list[StudyRecord])
def list_studies():
    return studies


@app.get("/api/studies/{study_id}", response_model=StudyRecord)
def get_study(study_id: str):
    for study in studies:
        if study.StudyID == study_id:
            return study
    raise HTTPException(status_code=404, detail=f"Study '{study_id}' not found on this node.")


# ---------------------------------------------------------------------------
# Auth (Section 7 contract): { role, org, irb_approved } from a Bearer token.
#
# This is a self-contained, dependency-free stub so nodes work standalone
# before gateway/auth.py exists. It hand-rolls a standard HS256 JWT
# (base64url header.payload.signature, HMAC-SHA256) using only the stdlib, so
# it stays wire-compatible with a future PyJWT-based gateway/auth.py as long
# as that module signs with the SAME secret via the MEDFIND_JWT_SECRET env
# var and the SAME claim names (role, org, irb_approved, sub, exp).
#
# Swap point for Person E: once gateway/auth.py exists, replace this whole
# block with `from gateway.auth import verify_token`, keeping the same
# {role, org, irb_approved, sub} return shape.
# ---------------------------------------------------------------------------

# Default MUST match gateway/auth.py's SECRET exactly, or every real token
# issued by the gateway will fail signature verification here and silently
# resolve to the anonymous role (see verify_token below) -- with no error
# raised anywhere, since verify_token fails closed to anonymous rather than
# throwing. Override both sides together via MEDFIND_JWT_SECRET if you ever
# rotate this for a real deployment.
JWT_SECRET = os.environ.get(
    "MEDFIND_JWT_SECRET", "medfind-hackathon-demo-secret-do-not-use-in-prod"
).encode()
VALID_ROLES = {"anonymous", "affiliated", "irb_approved"}
ANONYMOUS_CLAIMS = {"role": "anonymous", "org": None, "irb_approved": False, "sub": None}


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def verify_token(token: str | None) -> dict:
    """Verify a signed MedFind auth token -> {role, org, irb_approved, sub}.

    Missing, malformed, unsigned, or expired tokens all resolve to the
    anonymous role rather than raising, so callers can always trust the
    returned role for a policy check (fail closed at the policy step, not here).
    """
    if not token:
        return dict(ANONYMOUS_CLAIMS)
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}".encode()
        expected_sig = hmac.new(JWT_SECRET, signing_input, hashlib.sha256).digest()
        actual_sig = _b64url_decode(signature_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            return dict(ANONYMOUS_CLAIMS)
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception:
        return dict(ANONYMOUS_CLAIMS)

    exp = payload.get("exp")
    if exp is not None and time.time() > exp:
        return dict(ANONYMOUS_CLAIMS)

    role = payload.get("role", "anonymous")
    if role not in VALID_ROLES:
        role = "anonymous"

    return {
        "role": role,
        "org": payload.get("org"),
        "irb_approved": payload.get("irb_approved", role == "irb_approved"),
        "sub": payload.get("sub"),
    }


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip() or None


# ---------------------------------------------------------------------------
# POST /api/search — Semantic Diversity (req 1) + local counting (req 4)
#
# Matches `terms` (a synonym family expanded upstream by the gateway) against
# the free-text Diagnosis field, AND-filtered by body_part / modality / age.
# Returns a NUMBER ONLY — raw records/PII never leave the node during discovery.
# ---------------------------------------------------------------------------


class SearchRequest(BaseModel):
    terms: list[str] = Field(default_factory=list)
    body_part: str | None = None
    modality: str | None = None
    max_age_years: float | None = None


class SearchResponse(BaseModel):
    node: str
    count: int


def _study_matches(study: StudyRecord, req: SearchRequest) -> bool:
    if req.terms:
        diagnosis_lower = study.Diagnosis.lower()
        if not any(term.lower() in diagnosis_lower for term in req.terms if term):
            return False
    if req.body_part and study.BodyPartExamined.upper() != req.body_part.upper():
        return False
    if req.modality and study.Modality.upper() != req.modality.upper():
        return False
    if req.max_age_years is not None and parse_age_years(study.PatientAge) > req.max_age_years:
        return False
    return True


@app.post("/api/search", response_model=SearchResponse)
def search(req: SearchRequest):
    count = sum(1 for study in studies if _study_matches(study, req))
    return SearchResponse(node=HOSPITAL_NODE, count=count)


# ---------------------------------------------------------------------------
# POST /api/retrieve — Identity & RBAC (req 3) + Secure Retrieval (req 4)
#
# Re-verifies the token on EVERY call (zero trust), checks this node's own
# policy dict, and returns a de-identified study on success. Raw PII never
# crosses the node boundary even for authorized callers.
# ---------------------------------------------------------------------------


class RetrieveRequest(BaseModel):
    study_id: str


@app.post("/api/retrieve")
def retrieve(req: RetrieveRequest, authorization: str | None = Header(default=None)):
    token = _bearer_token(authorization)
    claims = verify_token(token)
    role = claims["role"]

    if not is_allowed(HOSPITAL_NODE, role):
        return JSONResponse(
            status_code=403,
            content={"error": f"Access denied by {HOSPITAL_NODE} policy for role {role}"},
        )

    for study in studies:
        if study.StudyID == req.study_id:
            return deidentify_study(study)

    return JSONResponse(
        status_code=404,
        content={"error": f"Study '{req.study_id}' not found on this node."},
    )
