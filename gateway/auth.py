"""
Auth module for MedFind — signup, password login, JWT claims, admin grants.

Users persist in gateway/users.json (demo plaintext passwords). JWT carries
{role, org, irb_approved, hospitals, username}.
"""
from __future__ import annotations

import datetime
import json
import threading
from pathlib import Path
from typing import Any, Optional

import jwt

SECRET = "medfind-hackathon-demo-secret-do-not-use-in-prod"
ALGORITHM = "HS256"
TOKEN_TTL_MINUTES = 60

VALID_ROLES = {"anonymous", "affiliated", "irb_approved", "network_admin"}
VALID_HOSPITALS = {"BCH", "MGH", "BWH"}

USERS_PATH = Path(__file__).resolve().parent / "users.json"
_lock = threading.Lock()

_SEED_ADMIN = {
    "password": "admin",
    "role": "network_admin",
    "org": "MedFind Network",
    "irb_approved": True,
    "hospitals": ["BCH", "MGH", "BWH"],
}


def _normalize_hospitals(hospitals: Any) -> list[str]:
    if not isinstance(hospitals, list):
        return []
    out: list[str] = []
    for h in hospitals:
        code = str(h).upper().strip()
        if code in VALID_HOSPITALS and code not in out:
            out.append(code)
    return out


def _load_users() -> dict[str, dict]:
    with _lock:
        if not USERS_PATH.exists():
            data = {"admin": dict(_SEED_ADMIN)}
            USERS_PATH.write_text(
                json.dumps(data, indent=2) + "\n", encoding="utf-8"
            )
            return data
        raw = json.loads(USERS_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {"admin": dict(_SEED_ADMIN)}
        return raw


def _save_users(users: dict[str, dict]) -> None:
    with _lock:
        USERS_PATH.write_text(
            json.dumps(users, indent=2) + "\n", encoding="utf-8"
        )


def _public_user(username: str, record: dict) -> dict:
    return {
        "username": username,
        "role": record.get("role", "anonymous"),
        "org": record.get("org"),
        "irb_approved": bool(record.get("irb_approved", False)),
        "hospitals": _normalize_hospitals(record.get("hospitals")),
    }


def issue_token(username: str, user: dict) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "username": username,
        "role": user.get("role", "anonymous"),
        "org": user.get("org"),
        "irb_approved": bool(user.get("irb_approved", False)),
        "hospitals": _normalize_hospitals(user.get("hospitals")),
        "iat": now,
        "exp": now + datetime.timedelta(minutes=TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def signup(username: str, password: str, org: Optional[str] = None) -> dict:
    """Create a new affiliated user with empty hospital grants.

    Raises ValueError with a machine-readable code: empty | taken | reserved.
    """
    username = (username or "").strip().lower()
    password = password or ""
    if not username or not password:
        raise ValueError("empty")
    if username == "anonymous":
        raise ValueError("reserved")

    users = _load_users()
    if username in users:
        raise ValueError("taken")

    users[username] = {
        "password": password,
        "role": "affiliated",
        "org": (org or "").strip() or "Independent",
        "irb_approved": False,
        "hospitals": [],
    }
    _save_users(users)
    return _public_user(username, users[username])


def login(username: str, password: str) -> dict:
    """Verify password and return {token, role, org, hospitals, username}.

    Raises ValueError("auth") on bad credentials.
    """
    username = (username or "").strip().lower()
    users = _load_users()
    user = users.get(username)
    if not user or user.get("password") != password:
        raise ValueError("auth")

    return {
        "token": issue_token(username, user),
        "username": username,
        "role": user.get("role", "anonymous"),
        "org": user.get("org"),
        "hospitals": _normalize_hospitals(user.get("hospitals")),
    }


def verify_token(token: str) -> dict | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None

    role = payload.get("role") or "anonymous"
    if role not in VALID_ROLES:
        role = "anonymous"

    return {
        "role": role,
        "org": payload.get("org"),
        "irb_approved": payload.get("irb_approved"),
        "hospitals": _normalize_hospitals(payload.get("hospitals")),
        "username": payload.get("username"),
    }


def list_users() -> list[dict]:
    users = _load_users()
    return [
        _public_user(name, record)
        for name, record in sorted(users.items())
    ]


def update_user(
    username: str,
    *,
    role: Optional[str] = None,
    hospitals: Optional[list[str]] = None,
    org: Optional[str] = None,
    irb_approved: Optional[bool] = None,
) -> dict:
    """Admin update of role / hospital grants. Raises ValueError codes."""
    username = (username or "").strip().lower()
    users = _load_users()
    if username not in users:
        raise ValueError("missing")

    record = users[username]

    if role is not None:
        if role not in VALID_ROLES or role == "anonymous":
            raise ValueError("bad_role")
        # Keep a single network master account as network_admin.
        if username == "admin" and role != "network_admin":
            raise ValueError("protect_admin")
        record["role"] = role
        if role == "irb_approved" or role == "network_admin":
            record["irb_approved"] = True
        elif irb_approved is None:
            record["irb_approved"] = False

    if hospitals is not None:
        record["hospitals"] = _normalize_hospitals(hospitals)
        if username == "admin":
            # Master always retains all sites.
            record["hospitals"] = ["BCH", "MGH", "BWH"]

    if org is not None:
        record["org"] = org

    if irb_approved is not None and role is None:
        record["irb_approved"] = bool(irb_approved)

    users[username] = record
    _save_users(users)
    return _public_user(username, record)


def require_network_admin(claims: dict | None) -> None:
    if not claims or claims.get("role") != "network_admin":
        raise PermissionError("admin_required")
