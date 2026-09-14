#!/usr/bin/env python3
"""The Semester OS server sealed for screenshots: loopback-only urllib, no refresh loop.

SEMESTER_OS_CAPTURE_NOW (ISO instant) shifts the clock used for written timestamps.
Usage: SEMESTER_OS_PORT=8790 SEMESTER_OS_DB=/tmp/demo.db python scripts/capture/demo_server.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "app" / "server"))

_real_urlopen = urllib.request.urlopen


def _loopback_only(request, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003 - mirrors urlopen
    url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
    host = urllib.parse.urlsplit(url).hostname or ""
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError(f"The capture server never reaches the network (attempted {host}).")
    return _real_urlopen(request, *args, **kwargs)


urllib.request.urlopen = _loopback_only

import db  # noqa: E402  (patched before anything imports now_iso from it)

_capture_now = os.environ.get("SEMESTER_OS_CAPTURE_NOW")
if _capture_now:
    _offset = datetime.fromisoformat(_capture_now) - datetime.now(timezone.utc)

    def _shifted_now_iso() -> str:
        moment = datetime.now(timezone.utc) + _offset
        return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    db.now_iso = _shifted_now_iso

import app as semester_app  # noqa: E402  (the guard has to be in place first)
import security  # noqa: E402


async def _no_refresh() -> None:
    await asyncio.Event().wait()


semester_app.calendar_refresh_loop = _no_refresh

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(semester_app.app, host=security.HOST, port=security.PORT, log_level="warning")
