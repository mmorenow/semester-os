"""Local-only security: loopback bind, Host allowlist (DNS rebinding), a per-install
API token, same-origin check on mutations, and no CORS headers ever.

Token-exempt: /api/health, /api/bootstrap, the Google OAuth callback (single-use
state) and /calendar/<secret>.ics (see calendar_feed.admit). The Vite dev proxy
must set changeOrigin and drop Origin/Referer.
"""

from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from config import CONFIG
from db import DATA_DIR

HOST = "127.0.0.1"
PORT = CONFIG.port

TOKEN_HEADER = "X-SemesterOS-Token"
TOKEN_PATH = DATA_DIR / ".semester_os_token"

ALLOWED_HOSTS = frozenset({f"127.0.0.1:{PORT}", f"localhost:{PORT}"})
ALLOWED_ORIGINS = frozenset({f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"})

MUTATING_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})

# Exempt for structural reasons: liveness probe, token handoff, and the OAuth
# redirect, which the browser performs without our header.
PUBLIC_API_PATHS = frozenset(
    {"/api/health", "/api/bootstrap", "/api/school/gcal/callback"}
)

_token_cache: str | None = None


def load_or_create_token() -> str:
    """Return the API token, generating and persisting it on first run."""
    global _token_cache
    if _token_cache:
        return _token_cache

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if TOKEN_PATH.exists():
        existing = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if existing:
            # Repair permissions in case the file was created by hand.
            try:
                os.chmod(TOKEN_PATH, 0o600)
            except OSError:
                pass
            _token_cache = existing
            return existing

    token = secrets.token_urlsafe(32)
    # Create the file with 0600 from the start, never wider even for an instant.
    fd = os.open(str(TOKEN_PATH), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token + "\n")
    _token_cache = token
    return token


def token_is_valid(candidate: str | None) -> bool:
    """Constant-time token check, on bytes: compare_digest raises on non-ASCII str,
    which would turn a hostile header into a 500 instead of a 401."""
    if not candidate or not isinstance(candidate, str):
        return False
    return hmac.compare_digest(
        candidate.strip().encode("utf-8", "surrogateescape"),
        load_or_create_token().encode("utf-8"),
    )


def host_is_allowed(host_header: str | None) -> bool:
    if not host_header:
        return False
    return host_header.strip().lower() in ALLOWED_HOSTS


def _origin_of(value: str | None) -> str | None:
    """Reduce an Origin or Referer header to a bare scheme://host:port."""
    if not value:
        return None
    value = value.strip()
    if value.lower() == "null":
        return "null"
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def origin_is_same(origin_header: str | None, referer_header: str | None) -> bool:
    """True when no origin information is present or all of it is ours.

    Missing headers are allowed: non-browser clients still need the token.
    """
    for header in (origin_header, referer_header):
        origin = _origin_of(header)
        if origin is None:
            continue
        if origin not in ALLOWED_ORIGINS:
            return False
    return True


def token_file_hint() -> str:
    try:
        relative = TOKEN_PATH.relative_to(Path.cwd())
    except ValueError:
        relative = TOKEN_PATH
    return str(relative)
