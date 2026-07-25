"""
Auth module for MedFind — issues and verifies signed JWTs carrying
{role, org, irb_approved}. Demo-only: one shared secret, no real PKI/user DB.

Imported by:
  - gateway/app.py  (POST /login, and to attach tokens to outbound calls)
  - hospital node main.py  (to verify tokens on POST /api/retrieve)
"""
import datetime

import jwt

SECRET = "medfind-hackathon-demo-secret-do-not-use-in-prod"
ALGORITHM = "HS256"
TOKEN_TTL_MINUTES = 60

# Hardcoded user table: username -> {role, org, irb_approved}
# role: "irb_approved" | "affiliated" | "anonymous"
USERS = {
    "jorgenson": {"role": "irb_approved", "org": "Harvard Medical School", "irb_approved": True},
    "chen": {"role": "affiliated", "org": "MIT", "irb_approved": False},
    "anonymous": {"role": "anonymous", "org": "public", "irb_approved": False},
}


def issue_token(username: str) -> str:
    """Look up `username` in USERS and return a signed JWT carrying their
    role, org, and irb_approved flag. Unknown usernames are treated as
    anonymous."""
    user = USERS.get(username, USERS["anonymous"])

    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "username": username,
        "role": user["role"],
        "org": user["org"],
        "irb_approved": user["irb_approved"],
        "iat": now,
        "exp": now + datetime.timedelta(minutes=TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def login(username: str) -> dict:
    """POST /login logic: returns the exact response shape the gateway
    should send back, e.g. {"token": "<jwt>"}. app.py wires this to the
    route; it should not need to touch token internals directly."""
    return {"token": issue_token(username)}


def verify_token(token: str) -> dict | None:
    """Verify a JWT and return {role, org, irb_approved}, or None if the
    token is missing, malformed, expired, or has a bad signature."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None

    return {
        "role": payload.get("role"),
        "org": payload.get("org"),
        "irb_approved": payload.get("irb_approved"),
    }
