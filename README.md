# MedFind — Federated DICOM Discovery Network

**The Open Accelerator Healthcare Hackathon — Track 1: Federated Medical Imaging Search**

> Find where relevant pediatric imaging data lives across a network of hospitals — without moving it, without exposing PII, and without granting access to anyone who isn't authorized.

## The Problem

A child being treated for a brain tumor gets scanned every few months so clinicians can tell whether it's growing, stable, or responding to treatment. Building models that help specialists measure these changes reliably requires examples from many children, scanners, hospitals, and disease stages — but pediatric brain tumors are rare, so no single hospital has enough cases on its own.

The scans researchers need may already exist somewhere in a network of children's hospitals. Today there's no safe way to find out, and even less clarity on how to access what's found without exposing sensitive patient health information. Researchers currently approach hospitals one at a time, spending months on contacts and approvals before even learning whether enough suitable data exists.

MedFind answers, for a participating network: **where might relevant data exist, how much is available, who is authorized to see it, and how can it be securely retrieved?**

## Our Solution

MedFind is a **distributed search** network: a central **gateway** takes a researcher's natural-language query, expands it into the clinical vocabulary each hospital actually uses in its reports, and forwards the query to every hospital node in parallel. Each hospital node runs its own database and evaluates the query — and, separately, any retrieval request — against its **own** local access policy. The gateway never stores patient data and never overrides a hospital's access decision; it only carries the researcher's identity token and aggregates what the hospitals are willing to disclose.

```
                        researcher (browser / API client)
                                   │
                    natural-language query + bearer token
                                   ▼
                  ┌─────────────────────────────────┐
                  │      MedFind Gateway  (:8000)    │
                  │  • /login    – issue signed JWT  │
                  │  • /search   – expand + fan-out  │
                  │  • /retrieve – token-forwarding   │
                  │              proxy                │
                  └───────┬───────────┬───────────┬───┘
                           │           │           │
                 POST /api/search, POST /api/retrieve
                           │           │           │
                     ┌─────▼───┐ ┌─────▼───┐ ┌─────▼───┐
                     │  BCH    │ │  MGH    │ │  BWH    │
                     │ :8001   │ │ :8002   │ │ :8003   │
                     │900 studies│900 studies│900 studies│
                     │local policy│local policy│local policy│
                     └─────────┘ └─────────┘ └─────────┘
```

Each hospital node is an independent FastAPI service holding its own synthetic dataset in memory. It decides, per role, whether a caller may retrieve a de-identified study — and different hospitals are allowed to (and do) disagree about the same researcher.

## How This Meets the Challenge

**1. Semantic Diversity** — A query for "tumor" needs to also find "neoplasm," "glioma," or "low-grade astrocytoma" in another hospital's report. `gateway/semantic.py` parses the free-text query for body part, modality, pediatric intent, and an age ceiling, then expands each remaining clinical word through the hand-written synonym dictionary in `gateway/synonyms.py`. Expansion is directional: broad terms ("tumor," "neoplasm," "mass," "lesion") expand into each other, while specific subtypes (e.g., "glioma") expand only into close relatives — deliberately excluding "mass"/"lesion," since those words also appear in negation phrases like "no mass effect" throughout the real report text, which would otherwise reintroduce false positives.

**2. Privacy vs. Discovery** — `/api/search` on every hospital node returns **a count, never records** — raw data never leaves a node during discovery. The gateway then applies k-anonymity suppression (`k=5`): any hospital's cohort smaller than 5 is replaced with a fixed safety message instead of an exact number, and the reported network total excludes suppressed cohorts (shown as e.g. `"40+"`).

**3. Identity & Role-Based Access Control** — The gateway's `/login` issues a signed JWT (HS256) carrying `{role, org, irb_approved}` for a small demo identity table (Dr. Jorgenson — IRB-approved, Harvard Medical School; Chen — affiliated, MIT; anonymous — public). Each hospital node owns its **own** policy table (`node_policy.py`) mapping role → allow/deny, independently of the other nodes:

| Hospital | `irb_approved` | `affiliated` | `anonymous` |
|---|---|---|---|
| BCH (Boston Children's) | allow | deny | deny |
| MGH (Mass General) | deny | deny | deny |
| BWH (Brigham and Women's) | allow | allow | deny |

Any node/role pair not explicitly listed is denied — hospitals fail closed by default.

**4. Secure Data Retrieval** — Locating data is only half the problem, so every retrieval is a genuine round trip to the hospital that holds the record, not just a lookup against something the gateway cached. `/retrieve` on the gateway forwards the caller's bearer token as-is to the specific hospital node's `/api/retrieve`. The node **re-verifies the token itself** and checks its own policy before returning anything — zero trust, re-checked on every single call, since the gateway is never the authority on who gets to see what. On success, the node strips direct identifiers (`PatientName`, `PatientID`, `PatientBirthDate`) and coarsens `PatientAge` into a band (e.g. `"3-5y"`) before the record ever leaves the hospital boundary; the gateway applies the same PII strip a second time as defense-in-depth on the way back out.

## Repository Layout

```
.
├── main.py              # Hospital node app — health/list/search/retrieve endpoints,
│                         #   standalone JWT verification, run once per hospital
├── models.py             # StudyRecord schema shared across the whole system
├── deidentify.py          # PII stripping + age-banding applied to every retrieval
├── node_policy.py          # Per-hospital, per-role allow/deny access table
├── requirements.txt         # fastapi, uvicorn, pydantic, pyjwt, httpx
├── data/
│   ├── bch_data.json        # 900 records — Boston Children's Hospital (pediatric, 0–21y)
│   ├── mgh_data.json         # 900 records — Massachusetts General Hospital (adult, 22–85y)
│   └── bwh_data.json          # 900 records — Brigham and Women's Hospital (adult, 18–75y)
├── gateway/
│   ├── app.py                 # Orchestration service (:8000) — /login, /search, /retrieve
│   ├── auth.py                  # JWT issuance/verification + demo user table
│   ├── semantic.py                # Free-text query → structured search terms
│   └── synonyms.py                 # Clinical synonym-expansion dictionary
└── frontend/
    └── index.html                  # Static demo UI: login → search → retrieve
```

Each hospital node is 300 brain / 300 heart / 300 fetal studies. Conditions overlap across hospitals on purpose — a search for something like "hydrocephalus" should surface matches from more than one node.

## Getting Started

> **First time?** See the [Pre-Hackathon Setup Guide](PRE_HACK_SETUP.md) for installing Python, Git, and a virtual environment.

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Start the three hospital nodes

Open three separate terminals:

```bash
# Terminal 1 — Boston Children's Hospital
HOSPITAL_NODE=BCH uvicorn main:app --port 8001 --reload

# Terminal 2 — Massachusetts General Hospital
HOSPITAL_NODE=MGH uvicorn main:app --port 8002 --reload

# Terminal 3 — Brigham and Women's Hospital
HOSPITAL_NODE=BWH uvicorn main:app --port 8003 --reload
```

### 3. Start the gateway

```bash
# Terminal 4 — Gateway
uvicorn gateway.app:app --port 8000 --reload
```

### 4. Open the demo frontend

Open `frontend/index.html` directly in a browser. It talks to the gateway at `http://localhost:8000`.

### 5. Verify everything is running

```bash
curl http://localhost:8000/health   # {"status":"healthy","service":"gateway"}
curl http://localhost:8001/health   # {"status":"healthy","node":"BCH"}
curl http://localhost:8002/health   # {"status":"healthy","node":"MGH"}
curl http://localhost:8003/health   # {"status":"healthy","node":"BWH"}
```

Interactive Swagger docs are auto-generated per service: `http://localhost:8000/docs` (gateway), `http://localhost:8001/docs` / `:8002` / `:8003` (nodes).

## Demo Walkthrough

This mirrors the scenario from the challenge brief: Dr. Jorgenson searches for pediatric brain MRI scans, the network returns counts while protecting small cohorts, and she's granted a secure path to the permitted records.

**1. Log in as Dr. Jorgenson (IRB-approved, Harvard Medical School)**

```bash
curl -X POST http://localhost:8000/login -H "Content-Type: application/json" \
  -d '{"username": "jorgenson"}'
# -> {"token": "<jwt>"}
```

**2. Search the network**

```bash
curl -X POST http://localhost:8000/search -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt>" \
  -d '{"query": "pediatric brain tumor MRI"}'
```

```json
{
  "query_expanded_to": ["tumor", "neoplasm", "glioma", "astrocytoma", "mass", "lesion", "growth"],
  "results": [
    {"hospital": "BCH", "count": 41},
    {"hospital": "MGH", "display": "Cohort too small to display safely (fewer than 5 records)."},
    {"hospital": "BWH", "count": 12}
  ],
  "network_total": "53+"
}
```

**3. Retrieve a permitted study**

```bash
curl -X POST http://localhost:8000/retrieve -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt>" \
  -d '{"hospital": "BCH", "study_id": "BR-7721"}'
```

BCH's policy allows `irb_approved`, so this returns the study with `PatientName`/`PatientID`/`PatientBirthDate` removed and `PatientAge` banded (e.g. `"6-12y"`). The same request against `MGH` (whose policy denies every role) returns `403 {"error": "Access denied by MGH policy for role irb_approved"}` instead — same researcher, same query, different hospital, different answer, exactly as intended.

Logging in as `chen` (affiliated, MIT) or skipping login entirely (anonymous) demonstrates the other two rows of the access table — try retrieving from BWH vs. BCH vs. MGH as each identity to see the policy differences play out.

## API Reference

### Gateway (`:8000`)

| Method | Endpoint | Auth | Body | Notes |
|---|---|---|---|---|
| `GET` | `/health` | — | — | Liveness check |
| `POST` | `/login` | — | `{"username": str}` | Issues a signed JWT; unknown usernames resolve to anonymous |
| `POST` | `/search` | optional Bearer | `{"query": str, "max_age_years"?: int}` | Expands query, fans out to all nodes, applies suppression |
| `POST` | `/retrieve` | required Bearer | `{"hospital": str, "study_id": str}` | Forwards token to the named node's `/api/retrieve` |

### Hospital Node (`:8001` / `:8002` / `:8003`)

| Method | Endpoint | Auth | Body | Notes |
|---|---|---|---|---|
| `GET` | `/health` | — | — | Returns node name + status |
| `GET` | `/api/studies` | — | — | All raw studies on this node (unauthenticated by design, for local dev/inspection) |
| `GET` | `/api/studies/{study_id}` | — | — | One raw study, or 404 |
| `POST` | `/api/search` | — | `{"terms": [str], "body_part"?, "modality"?, "max_age_years"?}` | Returns `{"node", "count"}` only — no records, no PII |
| `POST` | `/api/retrieve` | Bearer JWT | `{"study_id": str}` | Re-verifies token, checks this node's own policy, returns a de-identified study or 403/404 |

## Data Schema

Each study record (`models.py`):

| Field | Format | Example |
|---|---|---|
| `PatientName` | `LastName^FirstName` | `Harrington^Lucas` |
| `PatientID` | `PREFIX-NNNNN` | `CHB-99214` |
| `PatientBirthDate` | `YYYYMMDD` | `20181104` |
| `PatientAge` | `NNNY` / `NNNM` / `NNND` | `007Y` |
| `PatientSex` | `M` / `F` | `M` |
| `InstitutionName` | Full hospital name | `Boston Children's Hospital` |
| `StudyID` | `PREFIX-NNNN` | `BR-7721` |
| `StudyInstanceUID` | DICOM UID format | `1.3.12.2.1107.5.2.19.45152...` |
| `StudyDate` | `YYYYMMDD` | `20260715` |
| `Modality` | DICOM modality code | `MR` |
| `BodyPartExamined` | `BRAIN` / `HEART` / `FETAL` | `BRAIN` |
| `Diagnosis` | Full radiology report | Multi-paragraph clinical text |

On retrieval, `PatientName`, `PatientID`, and `PatientBirthDate` are removed and `PatientAge` is replaced with a coarse band (e.g. `"0-2y"`, `"65y+"`) — all other fields pass through unchanged.

## Tech Stack

- Python 3.10+, FastAPI, Uvicorn
- Pydantic (schema validation)
- PyJWT / HMAC-SHA256 (token issuance and verification)
- httpx (async fan-out from the gateway to hospital nodes)
- Vanilla HTML/CSS/JS frontend — no build step, no framework

## Demo-Only Notes

This is hackathon demo code, not a production deployment:

- The JWT signing secret is a hardcoded, shared demo string (`gateway/auth.py`'s `SECRET`, and `main.py`'s `MEDFIND_JWT_SECRET` default) — both sides must use the same value for gateway-issued tokens to verify at the nodes.
- CORS is wide open (`allow_origins=["*"]`) on both the gateway and every node.
- All traffic is plain HTTP on localhost; there is no TLS.
- The identity table (`gateway/auth.py`'s `USERS`) is a hardcoded list of three demo accounts, not a real user directory.
