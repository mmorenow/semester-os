"""Session-wide guard: no test may reach the network or a real credential.

Runs before any test module is imported: Google credential paths point into an
empty temp dir, and urlopen refuses non-loopback hosts. Per-test mocks are not
enough, since a renamed function silently escapes them.
"""

from __future__ import annotations

import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "app" / "server"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

_SANDBOX = tempfile.mkdtemp(prefix="semester-os-tests-")
_real_urlopen = urllib.request.urlopen
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _guarded_urlopen(request, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003 - mirrors urlopen
    url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
    host = urllib.parse.urlsplit(url).hostname or ""
    if host not in _LOOPBACK:
        raise RuntimeError(f"Tests may not reach the network (attempted {host}). Fake the call.")
    return _real_urlopen(request, *args, **kwargs)


urllib.request.urlopen = _guarded_urlopen

import school_gcal  # noqa: E402

school_gcal.TOKEN_PATH = Path(_SANDBOX) / ".google_token.json"
school_gcal.CLIENT_PATH = Path(_SANDBOX) / ".google_oauth_client.json"
