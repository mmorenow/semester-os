"""Google Calendar sync for the School section, all on the account's primary calendar.

Pushes classes (weekly RRULEs), deadlines and school events, each tagged with
private `semesteros`/`semesteros_kind` properties; only tagged events are ever
updated or deleted. sync_pull() reads primary into external_events, skipping our own.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time as time_module
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import db
import school
import school_ics
import security
from db import LOCAL_TZ_NAME, DATA_DIR, GCAL_SOURCE, SCHOOL_DAY_CODES, get_db, now_iso
from school import SchoolError

LOCAL_TZ = ZoneInfo(LOCAL_TZ_NAME)

CLIENT_PATH = DATA_DIR / ".google_oauth_client.json"
TOKEN_PATH = DATA_DIR / ".google_token.json"

SCOPE = "https://www.googleapis.com/auth/calendar"
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"

# Loopback redirect built from the bind constants, so it cannot drift.
CALLBACK_PATH = "/api/school/gcal/callback"
DEFAULT_REDIRECT_URI = f"http://{security.HOST}:{security.PORT}{CALLBACK_PATH}"

# Fixed relative paths: the callback is never an open redirect.
SUCCESS_REDIRECT = "/?gcal=connected"
DENIED_REDIRECT = "/?gcal=denied"
ERROR_REDIRECT = "/?gcal=error"

CALENDAR_ID = "primary"
PULL_CALENDAR_ID = CALENDAR_ID

# Private extended properties: natural key, and owning target (filtered server-side).
PROPERTY_KEY = "semesteros"
KIND_PROPERTY = "semesteros_kind"

# target -> (kind property value, key prefix). A target never touches another prefix.
TARGET_KINDS: dict[str, tuple[str, str]] = {
    "classes": ("class", "class:"),
    "deadlines": ("assignment", "assignment:"),
    "events": ("event", "event:"),
}

# Google palette ids: Peacock, Tangerine, Tomato, Grape.
COLOR_CLASS = "7"
COLOR_DEADLINE = "6"
COLOR_EXAM = "11"
COLOR_EVENT = "3"

# Separate calendars older versions created; reported by status(), never touched.
LEGACY_CALENDARS = (
    ("classes_id", "Classes"),
    ("mirror_id", "Outlook mirror"),
    ("deadlines_id", "Deadlines"),
)

SYNC_TARGETS = ("classes", "deadlines", "events", "pull")

# Answered as a no-op with a reason rather than a 422.
RETIRED_TARGETS = {
    "mirror": "mirror is retired: Outlook stays out of Google primary",
}

# Projection window for deadlines and events, in campus days around today.
PROJECTION_BACK_DAYS = 14
PROJECTION_FORWARD_DAYS = 200

DEADLINE_BLOCK_MINUTES = 30
DEFAULT_EVENT_MINUTES = 60

HTTP_TIMEOUT_SECONDS = 30
USER_AGENT = "semester-os/0.1"

# The write ceiling is shared by every target of one sync.
MAX_WRITES_PER_SYNC = 500
MAX_LIST_PAGES = 20
LIST_PAGE_SIZE = 250

# Dry-run action list is a sample; counts are complete.
MAX_PLANNED_ACTIONS = 50

# Google's limits on the fields we set.
MAX_SUMMARY = 1024
MAX_LOCATION = 1024
MAX_DESCRIPTION = 8000
MAX_PROPERTY_VALUE = 1024

# OAuth state lives in memory on purpose: a restart invalidates flows in progress.
STATE_TTL_SECONDS = 600
MAX_PENDING_STATES = 20

_state_lock = threading.Lock()
_pending_states: dict[str, float] = {}

# One writer at a time: concurrent runs would each list before the other wrote, and duplicate.
_sync_lock = threading.Lock()

# Set by the first manual real sync. Until then nothing unattended writes to primary.
ARMED_STATE_KEY = "primary_armed_at"

PUSH_LOCK_TIMEOUT_SECONDS = 120

# Weekday order, as RRULE spells them.
RRULE_DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")

MEETING_LABELS = {"lecture": "Lecture", "lab": "Lab", "pso": "PSO"}


class GcalError(SchoolError):
    """A Google Calendar problem, rendered by app.py's SchoolError handler."""


# ---------------------------------------------------------------------------
# Configuration and stored state
# ---------------------------------------------------------------------------

def _read_client() -> dict[str, str] | None:
    """The OAuth client, from {"web": {...}} or flat keys; None when not configured."""
    if not CLIENT_PATH.is_file():
        return None
    try:
        raw = json.loads(CLIENT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None

    block = raw.get("web") if isinstance(raw.get("web"), dict) else raw
    if not isinstance(block, dict):
        return None

    client_id = str(block.get("client_id") or "").strip()
    client_secret = str(block.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        return None

    redirect_uri = str(block.get("redirect_uri") or "").strip()
    if not redirect_uri:
        candidates = block.get("redirect_uris")
        if isinstance(candidates, list):
            for candidate in candidates:
                text = str(candidate or "").strip()
                if text.endswith(CALLBACK_PATH):
                    redirect_uri = text
                    break
    if not redirect_uri:
        redirect_uri = DEFAULT_REDIRECT_URI

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }


def configured() -> bool:
    return _read_client() is not None


def _require_client() -> dict[str, str]:
    client = _read_client()
    if client is None:
        raise GcalError(
            "Google Calendar is not configured. Save the OAuth client JSON at "
            "data/.google_oauth_client.json and try again.",
            status_code=409,
        )
    return client


def _state_get(key: str) -> str | None:
    with get_db() as conn:
        row = conn.execute("SELECT value FROM gcal_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _state_set(key: str, value: str | None) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO gcal_state (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, now_iso()),
        )


def _read_token() -> dict[str, Any] | None:
    if not TOKEN_PATH.is_file():
        return None
    try:
        raw = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _write_token(payload: dict[str, Any]) -> None:
    """Persist the tokens, created 0600 so a refresh token is never briefly world readable."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handle = os.open(str(TOKEN_PATH), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    form: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    """One HTTPS call to Google. Returns (status, decoded body); non-2xx is not raised."""
    if params:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{url}?{query}" if query else url

    data: bytes | None = None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif json_body is not None:
        data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            body = response.read()
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = int(exc.code)
    except urllib.error.URLError as exc:
        raise GcalError(f"Google could not be reached ({exc.reason}).", status_code=502) from None
    except (TimeoutError, OSError) as exc:
        raise GcalError(f"Google could not be reached ({exc}).", status_code=502) from None

    if not body:
        return status, None
    try:
        return status, json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        return status, None


def _api_message(payload: Any, fallback: str) -> str:
    """The human sentence out of a Google error body, if it has one."""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:400]
        if isinstance(error, str):
            described = payload.get("error_description")
            return f"{error}: {described}"[:400] if described else error[:400]
    return fallback


# ---------------------------------------------------------------------------
# The authorization code flow
# ---------------------------------------------------------------------------

def _issue_state() -> str:
    """A single use, short lived state value bound to this server process."""
    value = secrets.token_urlsafe(32)
    now = time_module.monotonic()
    with _state_lock:
        for key, issued in list(_pending_states.items()):
            if now - issued > STATE_TTL_SECONDS:
                del _pending_states[key]
        if len(_pending_states) >= MAX_PENDING_STATES:
            # Drop the oldest rather than refuse, so repeated Connects never lock out.
            oldest = min(_pending_states, key=_pending_states.get)
            del _pending_states[oldest]
        _pending_states[value] = now
    return value


def consume_state(value: str | None) -> bool:
    """True exactly once per issued state, within its TTL. Popped first so a stale one is spent."""
    if not value or not isinstance(value, str):
        return False
    now = time_module.monotonic()
    with _state_lock:
        issued = _pending_states.pop(value, None)
    return issued is not None and (now - issued) <= STATE_TTL_SECONDS


def record_error(message: str | None) -> None:
    """Keep a failure for /api/school/gcal/status, since the callback redirect loses it."""
    _state_set("last_error", message)


def auth_url() -> str:
    """The consent URL. prompt=consent: Google only issues a refresh token on fresh consent."""
    client = _require_client()
    params = {
        "client_id": client["client_id"],
        "redirect_uri": client["redirect_uri"],
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": _issue_state(),
    }
    return f"{AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"


def _account_email(access_token: str) -> str | None:
    """The account address, from the primary calendar's id (avoids requesting an identity scope)."""
    status, payload = _request("GET", f"{CALENDAR_API}/calendars/primary", token=access_token)
    if status == 200 and isinstance(payload, dict):
        value = payload.get("id")
        return str(value) if value else None
    return None


def exchange_code(code: str) -> dict[str, Any]:
    """Trade an authorization code for tokens. Refuses a response without a refresh token."""
    client = _require_client()
    status, payload = _request(
        "POST",
        TOKEN_ENDPOINT,
        form={
            "code": code,
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "redirect_uri": client["redirect_uri"],
            "grant_type": "authorization_code",
        },
    )
    if status != 200 or not isinstance(payload, dict):
        raise GcalError(
            _api_message(payload, f"Google refused the authorization code (HTTP {status})."),
            status_code=502,
        )

    refresh_token = str(payload.get("refresh_token") or "").strip()
    access_token = str(payload.get("access_token") or "").strip()
    if not access_token:
        raise GcalError("Google returned no access token.", status_code=502)
    if not refresh_token:
        raise GcalError(
            "Google returned no refresh token, so this connection would stop working within "
            "the hour. Remove this app under your Google account's third party access and "
            "connect again.",
            status_code=502,
        )

    stored = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": payload.get("token_type") or "Bearer",
        "scope": payload.get("scope") or SCOPE,
        "expires_at": _expiry_iso(payload.get("expires_in")),
        "connected_at": now_iso(),
        "account_email": _account_email(access_token),
    }
    _write_token(stored)
    _state_set("last_error", None)
    return stored


def _expiry_iso(expires_in: Any) -> str:
    """When an access token stops working, as one of our UTC timestamps."""
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        seconds = 3600
    moment = datetime.now(timezone.utc) + timedelta(seconds=max(0, seconds))
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _refresh(token: dict[str, Any]) -> dict[str, Any]:
    """Renew the access token. Google keeps the refresh token we already hold."""
    client = _require_client()
    status, payload = _request(
        "POST",
        TOKEN_ENDPOINT,
        form={
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "refresh_token": token.get("refresh_token") or "",
            "grant_type": "refresh_token",
        },
    )
    if status != 200 or not isinstance(payload, dict) or not payload.get("access_token"):
        message = _api_message(payload, f"Google refused the refresh token (HTTP {status}).")
        _state_set("last_error", message)
        raise GcalError(message, status_code=502)

    updated = dict(token)
    updated["access_token"] = str(payload["access_token"])
    updated["expires_at"] = _expiry_iso(payload.get("expires_in"))
    if payload.get("refresh_token"):
        updated["refresh_token"] = str(payload["refresh_token"])
    _write_token(updated)
    _state_set("last_error", None)
    return updated


def _access_token(force_refresh: bool = False) -> str:
    """A usable access token, refreshing when this one is about to expire."""
    token = _read_token()
    if not token or not token.get("refresh_token"):
        raise GcalError(
            "Google Calendar is not connected. Press Connect in the School section first.",
            status_code=409,
        )
    if not force_refresh and token.get("access_token"):
        expires_at = db.parse_iso(token.get("expires_at"))
        if expires_at and expires_at - timedelta(seconds=60) > datetime.now(timezone.utc):
            return str(token["access_token"])
    return str(_refresh(token)["access_token"])


def disconnect() -> None:
    """Forget the tokens. The calendars and their events stay where they are."""
    try:
        TOKEN_PATH.unlink()
    except FileNotFoundError:
        pass




# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def status() -> dict[str, Any]:
    """Connection state for the UI. No network call unless the access token has expired."""
    is_configured = configured()
    token = _read_token()
    stored = {state_key: _state_get(state_key) for state_key, _ in LEGACY_CALENDARS}
    payload: dict[str, Any] = {
        "configured": is_configured,
        "connected": False,
        "account_email": (token or {}).get("account_email"),
        "calendar_id": CALENDAR_ID,
        "legacy_calendars": [
            {"summary": summary, "id": stored[state_key]}
            for state_key, summary in LEGACY_CALENDARS
            if stored[state_key]
        ],
        "calendars": stored,
        "redirect_uri": (_read_client() or {}).get("redirect_uri", DEFAULT_REDIRECT_URI),
        "error": _state_get("last_error"),
        "last_sync_at": _state_get("last_sync_at"),
    }

    if not is_configured:
        if token:
            payload["error"] = (
                "There are tokens but no OAuth client at data/.google_oauth_client.json."
            )
        return payload
    if not token or not token.get("refresh_token"):
        return payload

    expires_at = db.parse_iso(token.get("expires_at"))
    if token.get("access_token") and expires_at and expires_at > datetime.now(timezone.utc):
        payload["connected"] = True
        return payload

    try:
        _refresh(token)
    except GcalError as exc:
        payload["error"] = exc.detail
        return payload
    payload["connected"] = True
    return payload


# ---------------------------------------------------------------------------
# One run: the shared write budget, and one target's ledger
# ---------------------------------------------------------------------------

class _Run:
    """What every target of one sync shares: the token, the mode, the budget."""

    def __init__(self, token: str, dry_run: bool) -> None:
        self.token = token
        self.dry_run = bool(dry_run)
        self.writes = 0


class _Ledger:
    """One target's counts and, on a dry run, the actions it would take."""

    def __init__(self, run: _Run, target: str) -> None:
        self.run = run
        self.target = target
        self.kind, self.prefix = TARGET_KINDS[target]
        self.counts = {"created": 0, "updated": 0, "unchanged": 0, "removed": 0, "deferred": 0}
        self.actions: list[dict[str, Any]] = []

    def spend(self, action: str, key: str, summary: Any) -> bool:
        """Claim one write from the shared ceiling. False (counted deferred) when spent."""
        if self.run.writes >= MAX_WRITES_PER_SYNC:
            self.counts["deferred"] += 1
            return False
        self.run.writes += 1
        if self.run.dry_run and len(self.actions) < MAX_PLANNED_ACTIONS:
            self.actions.append(
                {"action": action, "key": key, "summary": str(summary) if summary else None}
            )
        return True

    def result(self, **extra: Any) -> dict[str, Any]:
        out: dict[str, Any] = {
            "target": self.target,
            "calendar_id": CALENDAR_ID,
            "dry_run": self.run.dry_run,
            **self.counts,
            **extra,
        }
        if self.run.dry_run:
            out["actions"] = self.actions
        return out


def _events_url(event_id: str | None = None) -> str:
    base = f"{CALENDAR_API}/calendars/{urllib.parse.quote(CALENDAR_ID, safe='')}/events"
    if event_id is None:
        return base
    return f"{base}/{urllib.parse.quote(str(event_id), safe='')}"


def _private(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    extended = item.get("extendedProperties")
    private = extended.get("private") if isinstance(extended, dict) else None
    return private if isinstance(private, dict) else {}


def _list_owned(
    token: str, target: str
) -> tuple[dict[str, dict[str, Any]], list[tuple[str, dict[str, Any]]]]:
    """Owned events for one target, keyed by semesteros, plus duplicates.

    singleEvents=false so a class stays one RRULE event; no time window, since a
    hidden owned event would be recreated. Raises rather than reconcile a truncated listing.
    """
    kind, prefix = TARGET_KINDS[target]
    owned: dict[str, dict[str, Any]] = {}
    duplicates: list[tuple[str, dict[str, Any]]] = []
    page_token: str | None = None
    for _ in range(MAX_LIST_PAGES):
        code, payload = _request(
            "GET",
            _events_url(),
            token=token,
            params={
                "maxResults": LIST_PAGE_SIZE,
                "singleEvents": "false",
                "showDeleted": "false",
                "privateExtendedProperty": f"{KIND_PROPERTY}={kind}",
                "pageToken": page_token,
            },
        )
        if code != 200 or not isinstance(payload, dict):
            raise GcalError(
                _api_message(payload, f"Google refused to list the calendar (HTTP {code})."),
                status_code=502,
            )
        for item in payload.get("items") or []:
            if not isinstance(item, dict) or item.get("recurringEventId"):
                continue
            if str(item.get("status") or "").lower() == "cancelled":
                continue
            private = _private(item)
            key = str(private.get(PROPERTY_KEY) or "")
            if not key.startswith(prefix) or str(private.get(KIND_PROPERTY) or "") != kind:
                continue
            if key in owned:
                duplicates.append((key, item))
            else:
                owned[key] = item
        page_token = payload.get("nextPageToken")
        if not page_token:
            return owned, duplicates
    raise GcalError(
        f"Google listed more than {MAX_LIST_PAGES * LIST_PAGE_SIZE} {kind} events, so this "
        "sync stopped rather than reconcile a calendar it could not read to the end.",
        status_code=502,
    )


# ---------------------------------------------------------------------------
# Event bodies and change detection
# ---------------------------------------------------------------------------

def _cut(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _instant_key(block: Any) -> str:
    """A start/end as a comparable UTC instant (or date), since Google echoes offsets we did not send."""
    if not isinstance(block, dict):
        return ""
    if block.get("date"):
        return f"date:{block['date']}"
    raw = block.get("dateTime")
    if not raw:
        return ""
    text = str(raw)
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return f"raw:{text}"
    if moment.tzinfo is None:
        zone = block.get("timeZone")
        try:
            moment = moment.replace(tzinfo=ZoneInfo(str(zone)) if zone else LOCAL_TZ)
        except Exception:  # noqa: BLE001 - an unknown zone name is data, not a crash
            moment = moment.replace(tzinfo=LOCAL_TZ)
    return moment.astimezone(timezone.utc).isoformat()


def _differs(existing: dict[str, Any], desired: dict[str, Any]) -> bool:
    """True when the event on Google no longer says what the database says."""
    for field in ("summary", "location", "description", "colorId"):
        if (existing.get(field) or None) != (desired.get(field) or None):
            return True
    if _instant_key(existing.get("start")) != _instant_key(desired.get("start")):
        return True
    if _instant_key(existing.get("end")) != _instant_key(desired.get("end")):
        return True
    if _recurrence_key(existing.get("recurrence")) != _recurrence_key(desired.get("recurrence")):
        return True
    return False


def _recurrence_key(lines: Any) -> list[str]:
    """Recurrence lines with RRULE parts sorted, since Google reorders them."""
    normalized: list[str] = []
    for line in lines or []:
        text = str(line).strip()
        head, sep, body = text.partition(":")
        if sep and head.upper() in ("RRULE", "EXRULE"):
            parts = sorted(part.strip().upper() for part in body.split(";") if part.strip())
            normalized.append(f"{head.upper()}:{';'.join(parts)}")
        else:
            normalized.append(text)
    return sorted(normalized)


def _patch_times(body: dict[str, Any]) -> dict[str, Any]:
    """PATCH body with the other time shape nulled: a merged date + dateTime is "Invalid start time"."""
    patched = dict(body)
    for field in ("start", "end"):
        block = patched.get(field)
        if not isinstance(block, dict):
            continue
        block = dict(block)
        if block.get("date"):
            block["dateTime"] = None
            block["timeZone"] = None
        elif block.get("dateTime"):
            block["date"] = None
            block.setdefault("timeZone", None)
        patched[field] = block
    return patched


def _utc_block(moment: datetime) -> dict[str, Any]:
    return {"dateTime": school.utc_z(moment)}


def _upsert(
    ledger: _Ledger, owned: dict[str, dict[str, Any]], key: str, body: dict[str, Any]
) -> None:
    """Create or update one event on primary, keyed by its semesteros property."""
    if not key.startswith(ledger.prefix):  # a programming error, never data
        raise GcalError(f"Refusing to write '{key}' from the {ledger.target} target.", 500)
    body = dict(body)
    body["extendedProperties"] = {
        "private": {PROPERTY_KEY: key[:MAX_PROPERTY_VALUE], KIND_PROPERTY: ledger.kind}
    }

    existing = owned.get(key)
    if existing is not None and not _differs(existing, body):
        ledger.counts["unchanged"] += 1
        return

    action = "create" if existing is None else "update"
    if not ledger.spend(action, key, body.get("summary")):
        return
    if ledger.run.dry_run:
        ledger.counts["created" if existing is None else "updated"] += 1
        return

    if existing is None:
        code, payload = _request("POST", _events_url(), token=ledger.run.token, json_body=body)
        if code not in (200, 201):
            raise GcalError(
                _api_message(payload, f"Google refused to create an event (HTTP {code})."),
                status_code=502,
            )
        if isinstance(payload, dict):
            # So a second upsert of this key in one run updates instead of creating.
            owned[key] = payload
        ledger.counts["created"] += 1
        return

    code, payload = _request(
        "PATCH",
        _events_url(str(existing.get("id") or "")),
        token=ledger.run.token,
        json_body=_patch_times(body),
    )
    if code not in (200, 201):
        raise GcalError(
            _api_message(payload, f"Google refused to update an event (HTTP {code})."),
            status_code=502,
        )
    ledger.counts["updated"] += 1


def _delete(ledger: _Ledger, key: str, event: dict[str, Any]) -> None:
    """Remove one owned event, re-checking its properties so untagged events are never deleted."""
    private = _private(event)
    owned_key = str(private.get(PROPERTY_KEY) or "")
    if (
        not owned_key
        or owned_key != key
        or not owned_key.startswith(ledger.prefix)
        or str(private.get(KIND_PROPERTY) or "") != ledger.kind
    ):
        return
    event_id = str(event.get("id") or "")
    if not event_id:
        return
    if not ledger.spend("delete", key, event.get("summary")):
        return
    if ledger.run.dry_run:
        ledger.counts["removed"] += 1
        return

    code, payload = _request("DELETE", _events_url(event_id), token=ledger.run.token)
    # 404/410: already gone.
    if code not in (200, 204, 404, 410):
        raise GcalError(
            _api_message(payload, f"Google refused to remove an event (HTTP {code})."),
            status_code=502,
        )
    ledger.counts["removed"] += 1


def _projection_window(today: date | None = None) -> tuple[date, date]:
    """The campus days deadlines and events are projected for, inclusive."""
    anchor = today or datetime.now(LOCAL_TZ).date()
    return (
        anchor - timedelta(days=PROJECTION_BACK_DAYS),
        anchor + timedelta(days=PROJECTION_FORWARD_DAYS),
    )


def _local_day(value: Any) -> date | None:
    """The campus day a stored date or timestamp falls on, or None."""
    if school.is_bare_date(value):
        return _parse_day(value)
    moment = school.parse_instant(value)
    return moment.astimezone(LOCAL_TZ).date() if moment else None


# ---------------------------------------------------------------------------
# Target: the seeded course meetings
# ---------------------------------------------------------------------------

def _weekday_indexes(days: Any) -> list[int]:
    if not isinstance(days, list):
        return []
    indexes = set()
    for code in days:
        if not isinstance(code, str):
            continue
        index = SCHOOL_DAY_CODES.get(code.strip().upper())
        if index is not None:
            indexes.add(index)
    return sorted(indexes)


def _first_occurrence(start: date, weekdays: list[int]) -> date | None:
    for offset in range(7):
        day = start + timedelta(days=offset)
        if day.weekday() in weekdays:
            return day
    return None


def _parse_day(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None



def _parse_hm(value: Any) -> time | None:
    try:
        return datetime.strptime(str(value).strip(), "%H:%M").time()
    except (AttributeError, ValueError):
        return None


def _meeting_event(row: Any) -> tuple[str, dict[str, Any]] | None:
    """One course meeting as a weekly recurring event.

    DTSTART is local wall time plus timeZone so the class keeps its time across DST;
    UNTIL is UTC, as RRULE requires.
    """
    weekdays = _weekday_indexes(db.meeting_to_dict(row).get("days"))
    start_time = _parse_hm(row["start_time"])
    if not weekdays or start_time is None:
        return None

    run_start = _parse_day(row["start_date"]) or datetime.now(LOCAL_TZ).date()
    first = _first_occurrence(run_start, weekdays)
    if first is None:
        return None

    duration = int(row["duration_min"] or 0) or 50
    local_start = datetime.combine(first, start_time, LOCAL_TZ)
    local_end = local_start + timedelta(minutes=duration)

    recurrence = f"RRULE:FREQ=WEEKLY;BYDAY={','.join(RRULE_DAYS[index] for index in weekdays)}"
    run_end = _parse_day(row["end_date"])
    if run_end is not None:
        until = (
            datetime.combine(run_end, time(23, 59, 59), LOCAL_TZ)
            .astimezone(timezone.utc)
            .strftime("%Y%m%dT%H%M%SZ")
        )
        recurrence = f"{recurrence};UNTIL={until}"

    kind = str(row["kind"] or "").strip()
    label = MEETING_LABELS.get(kind, kind.title() or "Meeting")
    body = {
        "summary": _cut(f"{row['course_code']} · {label}", MAX_SUMMARY),
        "location": _cut(row["location"], MAX_LOCATION),
        "description": _cut(row["course_title"], MAX_DESCRIPTION),
        "start": {"dateTime": local_start.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": LOCAL_TZ_NAME},
        "end": {"dateTime": local_end.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": LOCAL_TZ_NAME},
        "recurrence": [recurrence],
        "colorId": COLOR_CLASS,
    }
    # CRN is the key; a hand-typed row without one falls back to its id.
    crn = str(row["crn"] or "").strip() or f"m{int(row['id'])}"
    return f"class:{crn}:{kind}", body


def sync_classes(run: _Run) -> dict[str, Any]:
    """Every course meeting on primary as a weekly event; stale class events go."""
    ledger = _Ledger(run, "classes")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT m.*, c.code AS course_code, c.title AS course_title "
            "FROM course_meetings m JOIN courses c ON c.id = m.course_id "
            "ORDER BY c.code, m.start_time, m.id"
        ).fetchall()

    owned, duplicates = _list_owned(run.token, "classes")
    wanted: set[str] = set()
    for row in rows:
        built = _meeting_event(row)
        if built is None:
            continue
        wanted.add(built[0])
        _upsert(ledger, owned, built[0], built[1])

    for key, event in list(owned.items()):
        if key not in wanted:
            _delete(ledger, key, event)
    for key, event in duplicates:
        _delete(ledger, key, event)

    return ledger.result(meetings=len(rows))


# ---------------------------------------------------------------------------
# Target: deadlines (reconciled in full every sync, so a failed push self-heals)
# ---------------------------------------------------------------------------

DONE_ASSIGNMENT_STATUSES = ("submitted", "graded")


def _deadline_event(item: Any) -> tuple[str, dict[str, Any]] | None:
    """One assignment as its deadline event, or None.

    due_at..ends_at block when ends_at is set; all-day for a bare date; else a
    30-minute block ending at due_at. Done work keeps its event, prefixed with a check.
    """
    row = dict(item)
    identifier = row.get("id")
    due_raw = row.get("due_at")
    if identifier is None or not due_raw:
        return None

    if school.is_bare_date(due_raw):
        day = _parse_day(due_raw)
        if day is None:
            return None
        start_block: dict[str, Any] = {"date": day.isoformat()}
        end_block: dict[str, Any] = {"date": (day + timedelta(days=1)).isoformat()}
    else:
        due = school.parse_instant(due_raw)
        if due is None:
            return None
        ends = school.parse_instant(row.get("ends_at")) if row.get("ends_at") else None
        if ends is not None and ends > due:
            start_block, end_block = _utc_block(due), _utc_block(ends)
        else:
            start_block = _utc_block(due - timedelta(minutes=DEADLINE_BLOCK_MINUTES))
            end_block = _utc_block(due)

    code = str(row.get("course_code") or "").strip()
    title = str(row.get("title") or "Assignment").strip()
    summary = f"{code} · {title}" if code else title
    if row.get("status") in DONE_ASSIGNMENT_STATUSES:
        summary = f"✓ {summary}"
    description = "\n\n".join(
        part
        for part in (
            str(row.get("notes") or "").strip(),
            str(row.get("brief_md") or row.get("url") or "").strip(),
        )
        if part
    )
    body = {
        "summary": _cut(summary, MAX_SUMMARY),
        "location": _cut(row.get("location"), MAX_LOCATION),
        "description": _cut(description, MAX_DESCRIPTION),
        "start": start_block,
        "end": end_block,
        "colorId": COLOR_EXAM if row.get("kind") == "exam" else COLOR_DEADLINE,
    }
    return f"assignment:{int(identifier)}", body


def _assignment_rows(ids: Iterable[int] | None = None) -> list[Any]:
    sql = "SELECT a.*, c.code AS course_code FROM assignments a JOIN courses c ON c.id = a.course_id"
    params: list[Any] = []
    if ids is not None:
        id_list = [int(value) for value in ids]
        if not id_list:
            return []
        sql += f" WHERE a.id IN ({', '.join('?' for _ in id_list)})"
        params = id_list
    with get_db() as conn:
        return conn.execute(sql + " ORDER BY a.due_at, a.id", params).fetchall()


def _classify_assignment(row: Any, window: tuple[date, date]) -> str:
    """'project' (on the calendar), 'history' (qualifies, outside the window) or 'gone'."""
    if row["status"] == "dropped" or not row["due_at"]:
        return "gone"
    day = _local_day(row["due_at"])
    if day is None:
        return "gone"
    return "project" if window[0] <= day <= window[1] else "history"


def _reconcile(
    ledger: _Ledger,
    owned: dict[str, dict[str, Any]],
    duplicates: list[tuple[str, dict[str, Any]]],
    rows: list[Any],
    key_of: Any,
    classify: Any,
    build: Any,
    *,
    only_keys: set[str] | None = None,
) -> None:
    """Upsert 'project' rows, delete owned events whose row is 'gone', leave 'history' alone.

    `only_keys` limits the pass to what a note touched.
    """
    window = _projection_window()
    status_by_key: dict[str, str] = {}
    for row in rows:
        key = key_of(row)
        if only_keys is not None and key not in only_keys:
            continue
        verdict = classify(row, window)
        status_by_key[key] = verdict
        if verdict == "project":
            built = build(row)
            if built is None:
                status_by_key[key] = "gone"
            else:
                _upsert(ledger, owned, built[0], built[1])

    for key, event in list(owned.items()):
        if only_keys is not None and key not in only_keys:
            continue
        if status_by_key.get(key, "gone") == "gone":
            _delete(ledger, key, event)
    for key, event in duplicates:
        if only_keys is not None and key not in only_keys:
            continue
        _delete(ledger, key, event)


def sync_deadlines(run: _Run) -> dict[str, Any]:
    """Every dated, not dropped assignment in the window on primary; the rest go."""
    ledger = _Ledger(run, "deadlines")
    rows = _assignment_rows()
    owned, duplicates = _list_owned(run.token, "deadlines")
    _reconcile(
        ledger,
        owned,
        duplicates,
        rows,
        lambda row: f"assignment:{int(row['id'])}",
        _classify_assignment,
        _deadline_event,
    )
    return ledger.result(assignments=len(rows))


# ---------------------------------------------------------------------------
# Target: events
# ---------------------------------------------------------------------------

def _school_event_body(item: Any) -> tuple[str, dict[str, Any]] | None:
    """One school_events row as a Google event, or None. All-day end: inclusive here, exclusive on Google."""
    row = dict(item)
    identifier = row.get("id")
    if identifier is None:
        return None

    if int(row.get("all_day") or 0):
        start_day = _parse_day(row.get("start_at"))
        if start_day is None:
            return None
        last_day = _parse_day(row.get("end_at")) or start_day
        if last_day < start_day:
            last_day = start_day
        start_block: dict[str, Any] = {"date": start_day.isoformat()}
        end_block: dict[str, Any] = {"date": (last_day + timedelta(days=1)).isoformat()}
    else:
        start = school.parse_instant(row.get("start_at"))
        if start is None:
            return None
        end = school.parse_instant(row.get("end_at")) if row.get("end_at") else None
        if end is None or end <= start:
            end = start + timedelta(minutes=DEFAULT_EVENT_MINUTES)
        start_block, end_block = _utc_block(start), _utc_block(end)

    code = str(row.get("course_code") or "").strip()
    course_title = str(row.get("course_title") or "").strip()
    course_line = " · ".join(part for part in (code, course_title) if part)
    description = "\n\n".join(
        part for part in (str(row.get("notes") or "").strip(), course_line) if part
    )
    body = {
        "summary": _cut(row.get("title"), MAX_SUMMARY) or "(untitled)",
        "location": _cut(row.get("location"), MAX_LOCATION),
        "description": _cut(description, MAX_DESCRIPTION),
        "start": start_block,
        "end": end_block,
        "colorId": COLOR_EVENT,
    }
    return f"event:{int(identifier)}", body


def _event_rows(ids: Iterable[int] | None = None) -> list[Any]:
    sql = (
        "SELECT e.*, c.code AS course_code, c.title AS course_title FROM school_events e "
        "LEFT JOIN courses c ON c.id = e.course_id"
    )
    params: list[Any] = []
    if ids is not None:
        id_list = [int(value) for value in ids]
        if not id_list:
            return []
        sql += f" WHERE e.id IN ({', '.join('?' for _ in id_list)})"
        params = id_list
    with get_db() as conn:
        return conn.execute(sql + " ORDER BY e.start_at, e.id", params).fetchall()


def _classify_event(row: Any, window: tuple[date, date]) -> str:
    if row["status"] != "scheduled":
        return "gone"
    day = _local_day(row["start_at"])
    if day is None:
        return "gone"
    return "project" if window[0] <= day <= window[1] else "history"


def sync_events(run: _Run) -> dict[str, Any]:
    """Every scheduled school event in the window on primary; cancelled ones go."""
    ledger = _Ledger(run, "events")
    rows = _event_rows()
    owned, duplicates = _list_owned(run.token, "events")
    _reconcile(
        ledger,
        owned,
        duplicates,
        rows,
        lambda row: f"event:{int(row['id'])}",
        _classify_event,
        _school_event_body,
    )
    return ledger.result(events=len(rows))


# ---------------------------------------------------------------------------
# A note's immediate push
# ---------------------------------------------------------------------------

def push_changes(
    assignment_ids: Iterable[int] = (), event_ids: Iterable[int] = ()
) -> dict[str, Any]:
    """Reconcile only the rows one applied note touched. Raises GcalError.

    A convenience: the next full sync reaches the same state if this fails.
    """
    assignment_list = sorted({int(value) for value in assignment_ids})
    event_list = sorted({int(value) for value in event_ids})
    if not assignment_list and not event_list:
        return {}
    if not armed():
        raise GcalError(
            "Nothing has been written to your Google calendar yet: run a sync once from the "
            "School section (a dry run first is a good idea). That sync uploads these changes.",
            status_code=409,
        )

    token = _access_token()
    if not _sync_lock.acquire(timeout=PUSH_LOCK_TIMEOUT_SECONDS):
        raise GcalError(
            "A calendar sync was already running, so these changes will be uploaded by the "
            "next sync.",
            status_code=409,
        )
    try:
        run = _Run(token, dry_run=False)
        results: dict[str, Any] = {}
        if assignment_list:
            ledger = _Ledger(run, "deadlines")
            owned, duplicates = _list_owned(token, "deadlines")
            _reconcile(
                ledger,
                owned,
                duplicates,
                _assignment_rows(assignment_list),
                lambda row: f"assignment:{int(row['id'])}",
                _classify_assignment,
                _deadline_event,
                only_keys={f"assignment:{value}" for value in assignment_list},
            )
            results["deadlines"] = ledger.result(assignments=len(assignment_list))
        if event_list:
            ledger = _Ledger(run, "events")
            owned, duplicates = _list_owned(token, "events")
            _reconcile(
                ledger,
                owned,
                duplicates,
                _event_rows(event_list),
                lambda row: f"event:{int(row['id'])}",
                _classify_event,
                _school_event_body,
                only_keys={f"event:{value}" for value in event_list},
            )
            results["events"] = ledger.result(events=len(event_list))
        return results
    finally:
        _sync_lock.release()


def armed() -> bool:
    """True once a real sync to primary has been run by hand."""
    return bool(_state_get(ARMED_STATE_KEY))


def upsert_deadlines(assignments: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Push a set of assignment rows now. Kept for callers that hold rows, not ids."""
    ids = [
        int(item["id"])
        for item in assignments
        if isinstance(item, dict) and isinstance(item.get("id"), int)
    ]
    return push_changes(assignment_ids=ids).get("deadlines", {})


# ---------------------------------------------------------------------------
# Target: the pull (primary -> external_events, via school_ics storage rules)
# ---------------------------------------------------------------------------

def _pulled_instant(block: Any) -> tuple[str | None, bool]:
    """A Google start/end as stored: bare date for all-day (exclusive end), else UTC instant."""
    if not isinstance(block, dict):
        return None, False

    day = block.get("date")
    if day:
        parsed = _parse_day(day)
        return (parsed.isoformat(), True) if parsed else (None, False)

    raw = block.get("dateTime")
    if not raw:
        return None, False
    try:
        moment = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None, False
    if moment.tzinfo is None:
        zone = block.get("timeZone")
        try:
            moment = moment.replace(tzinfo=ZoneInfo(str(zone)) if zone else LOCAL_TZ)
        except Exception:  # noqa: BLE001 - an unknown zone name is data, not a crash
            moment = moment.replace(tzinfo=LOCAL_TZ)
    return school_ics._utc_iso(moment), False


def _pulled_row(item: Any, owned_series: set[str] | frozenset[str] = frozenset()) -> dict[str, Any] | None:
    """One Google event as an external_events row, or None.

    None for our own events (by property, or recurringEventId of an owned series),
    cancelled events, workingLocation markers, and items without id or start.
    """
    if not isinstance(item, dict):
        return None
    if str(item.get("status") or "").strip().lower() == "cancelled":
        return None

    private = _private(item)
    if private.get(PROPERTY_KEY) or private.get(KIND_PROPERTY):
        return None
    series = item.get("recurringEventId")
    if series and str(series) in owned_series:
        return None

    if str(item.get("eventType") or "").strip() == "workingLocation":
        return None

    # An expanded instance id ("<series>_<original start>") is unique, so it is the uid.
    uid = school_ics._text(item.get("id"), school_ics.MAX_UID)
    if not uid:
        return None

    start_at, all_day = _pulled_instant(item.get("start"))
    if not start_at:
        return None
    end_at, _ = _pulled_instant(item.get("end"))

    return {
        "uid": uid,
        "instance_start": start_at,
        "title": school_ics._text(item.get("summary"), school_ics.MAX_TITLE),
        "location": school_ics._text(item.get("location"), school_ics.MAX_LOCATION),
        "description": school_ics._text(item.get("description"), school_ics.MAX_DESCRIPTION),
        "start_at": start_at,
        "end_at": end_at,
        "all_day": 1 if all_day else 0,
    }


def _list_instances(token: str, time_min: str, time_max: str) -> list[dict[str, Any]]:
    """Every occurrence on primary inside the window (singleEvents=true, unlike _list_owned)."""
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    for _ in range(MAX_LIST_PAGES):
        code, payload = _request(
            "GET",
            _events_url(),
            token=token,
            params={
                "maxResults": LIST_PAGE_SIZE,
                "singleEvents": "true",
                "showDeleted": "false",
                "pageToken": page_token,
                "timeMin": time_min,
                "timeMax": time_max,
            },
        )
        if code != 200 or not isinstance(payload, dict):
            raise GcalError(
                _api_message(payload, f"Google refused to read your calendar (HTTP {code})."),
                status_code=502,
            )
        for item in payload.get("items") or []:
            items.append(item)
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return items


def sync_pull(dry_run: bool = False) -> dict[str, Any]:
    """Read primary into external_events; vanished occurrences are retired, not deleted.

    A failure is recorded before raising, except on a dry run, which writes nothing.
    """
    window_start, window_end = school_ics._window()
    time_min = window_start.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    time_max = window_end.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    try:
        token = _access_token()
        owned, duplicates = _list_owned(token, "classes")
        owned_series = {str(event.get("id")) for event in owned.values() if event.get("id")}
        owned_series.update(str(event.get("id")) for _, event in duplicates if event.get("id"))
        items = _list_instances(token, time_min, time_max)
    except GcalError as exc:
        if not dry_run:
            with get_db() as conn:
                school_ics._write_state(
                    conn, GCAL_SOURCE, ok=False, error=exc.detail, event_count=None
                )
        raise

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    skipped = 0
    for item in items:
        row = _pulled_row(item, owned_series)
        if row is None:
            skipped += 1
            continue
        key = (row["uid"], row["instance_start"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
        if len(rows) >= school_ics.MAX_EVENTS_PER_SYNC:
            break

    base = {
        "target": "pull",
        "calendar_id": PULL_CALENDAR_ID,
        "source": GCAL_SOURCE,
        "dry_run": bool(dry_run),
        "events": len(items),
        "skipped": skipped,
    }
    if dry_run:
        return {**base, "would_store": len(rows)}

    with get_db() as conn:
        counts = school_ics._store(conn, GCAL_SOURCE, rows, window_start, window_end)
        school_ics._write_state(
            conn, GCAL_SOURCE, ok=True, error=None, event_count=counts["stored"]
        )
    return {**base, **counts}


def pull_status() -> dict[str, Any]:
    """Where the pull stands, in the shape school_ics reports a feed in."""
    token = _read_token()
    connected = bool(configured() and token and token.get("refresh_token"))
    with get_db() as conn:
        return school_ics._state_row(conn, GCAL_SOURCE, configured=connected)


# ---------------------------------------------------------------------------
# The entry point the API and the background task use
# ---------------------------------------------------------------------------

RUNNERS = {"classes": sync_classes, "deadlines": sync_deadlines, "events": sync_events}


def sync(targets: Iterable[str], dry_run: bool = False, *, arm: bool = True) -> dict[str, Any]:
    """Run the requested targets; each reports its own result or error, nothing is raised per target.

    `arm`: a manual real run of a writing target sets ARMED_STATE_KEY. The background loop passes False.
    """
    requested: list[str] = []
    for target in targets or ():
        name = str(target).strip()
        if name not in SYNC_TARGETS and name not in RETIRED_TARGETS:
            raise GcalError(
                f"Unknown sync target '{name}'. Valid values: {', '.join(SYNC_TARGETS)}.",
                status_code=422,
            )
        if name not in requested:
            requested.append(name)
    if not requested:
        raise GcalError(
            f"Name at least one target. Valid values: {', '.join(SYNC_TARGETS)}.",
            status_code=422,
        )

    results: dict[str, Any] = {}
    ran = False
    with _sync_lock:
        run: _Run | None = None
        for name in requested:
            if name in RETIRED_TARGETS:
                results[name] = {
                    "ok": True,
                    "error": None,
                    "target": name,
                    "skipped": RETIRED_TARGETS[name],
                }
                continue
            try:
                if name == "pull":
                    outcome = sync_pull(dry_run=dry_run)
                else:
                    if run is None:
                        run = _Run(_access_token(), dry_run)
                    outcome = RUNNERS[name](run)
                results[name] = {"ok": True, "error": None, **outcome}
                ran = True
                if arm and not dry_run and name in RUNNERS and not armed():
                    _state_set(ARMED_STATE_KEY, now_iso())
            except GcalError as exc:
                results[name] = {"ok": False, "error": exc.detail, "target": name}
        if ran and not dry_run:
            _state_set("last_sync_at", now_iso())
    return results


def sync_if_connected(targets: Iterable[str] = SYNC_TARGETS) -> dict[str, Any] | None:
    """Background entry point. None when not connected; only pulls until armed."""
    if not configured():
        return None
    token = _read_token()
    if not token or not token.get("refresh_token"):
        return None
    if not armed():
        targets = [name for name in targets if name == "pull"]
        if not targets:
            return None
    return sync(targets, arm=False)
