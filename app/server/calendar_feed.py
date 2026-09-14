"""Subscribable iCalendar (RFC 5545) feed of the semester at a secret URL.

Built from school_gcal's event bodies so both paths agree. Cancelled or dropped
rows are omitted, not STATUS:CANCELLED, since clients render that inconsistently.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import tempfile
import threading
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import db
import school
import school_gcal
import security
from db import DATA_DIR, LOCAL_TZ_NAME, get_db, now_iso
from school import SchoolError

LOG = logging.getLogger("semester_os.calendar_feed")

LOCAL_TZ = ZoneInfo(LOCAL_TZ_NAME)

STATE_PATH = DATA_DIR / ".calendar_feed.json"

# Admission regex is looser than a real secret so any wrong one gets the route's 404.
FEED_PATH_PREFIX = "/calendar/"
FEED_SUFFIX = ".ics"
FEED_PATH_RE = re.compile(r"^/calendar/[A-Za-z0-9_-]{1,256}\.ics$")
SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
SECRET_BYTES = 32

UID_DOMAIN = "semester-os"
PRODID = "-//Semester OS//Calendar feed 1.0//EN"
CALENDAR_NAME = "Semester OS"
CALENDAR_DESCRIPTION = "Classes, deadlines, exams and events from Semester OS."

# Google Calendar ignores this and refreshes every 8-24 hours.
REFRESH_INTERVAL = "PT1H"

WINDOW_BACK_DAYS = 30
WINDOW_FORWARD_DAYS = 200
WINDOW_MAX_FORWARD_DAYS = 400

# UNTIL for open-ended meetings, relative to the first session so SEQUENCE stays stable.
OPEN_MEETING_DAYS = 200

# RFC 5545 section 3.1: lines SHOULD NOT exceed 75 octets, excluding the CRLF.
FOLD_OCTETS = 75

# RFC 7986 COLOR is rarely rendered, so events also carry CATEGORIES.
# Nearest CSS names to school_gcal's Google palette ids.
CALENDAR_COLOR = "steelblue"
KIND_COLORS = {
    "class": "deepskyblue",  # Peacock
    "deadline": "orangered",  # Tangerine
    "exam": "crimson",  # Tomato
    "event": "darkorchid",  # Grape
}
KIND_CATEGORY = {"class": "Class", "deadline": "Deadline", "exam": "Exam", "event": "Event"}

MAX_PUBLIC_URL = 255
_HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")

# Any of these means the request came through a proxy, whatever its Host says.
FORWARDING_HEADERS = (
    "forwarded",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-real-ip",
    "cf-connecting-ip",
    "cf-ray",
    "true-client-ip",
    "tailscale-user-login",
    "tailscale-funnel-request",
    "ngrok-trace-id",
)

# The raw user agent is never stored, only one of these labels.
CLIENT_LABELS = {
    "google": "Google Calendar",
    "apple": "Apple Calendar",
    "outlook": "Outlook",
    "browser": "A web browser",
    "other": "Another calendar app",
}

_state_lock = threading.Lock()
_versions_lock = threading.Lock()
_schema_ready: set[str] = set()


# ---------------------------------------------------------------------------
# The secret and the public address, in data/.calendar_feed.json
# ---------------------------------------------------------------------------

def _write_state(payload: dict[str, Any]) -> None:
    """Replace the state file atomically, 0600 from the moment it exists."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=".calendar_feed.", suffix=".tmp", dir=str(STATE_PATH.parent)
    )
    try:
        os.chmod(temp_name, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, STATE_PATH)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _new_state(previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    stamp = now_iso()
    state = {
        "secret": secrets.token_urlsafe(SECRET_BYTES),
        "created_at": (previous or {}).get("created_at") or stamp,
        "rotated_at": stamp,
        "public_base_url": (previous or {}).get("public_base_url"),
    }
    return state


def _read_raw() -> Any:
    """The state file as JSON, or None when it is missing or unreadable. Caller holds the lock."""
    if not STATE_PATH.is_file():
        return None
    try:
        os.chmod(STATE_PATH, 0o600)
    except OSError:
        pass
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _valid(raw: Any) -> dict[str, Any] | None:
    if not (isinstance(raw, dict) and isinstance(raw.get("secret"), str) and SECRET_RE.match(raw["secret"])):
        return None
    public = raw.get("public_base_url")
    return {
        "secret": raw["secret"],
        "created_at": raw.get("created_at"),
        "rotated_at": raw.get("rotated_at"),
        "public_base_url": public if isinstance(public, str) and public else None,
    }


def _load_locked() -> dict[str, Any]:
    raw = _read_raw()
    state = _valid(raw)
    if state is not None:
        return state
    if STATE_PATH.exists():
        LOG.warning("The calendar feed state file was unreadable; a new feed link was issued.")
    state = _new_state(None)
    _write_state(state)
    return state


def load_state() -> dict[str, Any]:
    """The feed's state, creating a secret on first use.

    Read fresh each call so a rotation from any process applies immediately.
    """
    with _state_lock:
        return _load_locked()


def rotate_secret() -> dict[str, Any]:
    """Issue a new secret, invalidating every old link. Public address carries over."""
    with _state_lock:
        current = _valid(_read_raw()) or {}
        state = _new_state(current)
        _write_state(state)
    return state


def secret_matches(candidate: str | None) -> bool:
    """Constant-time comparison of a presented secret with the stored one."""
    if not candidate or not isinstance(candidate, str):
        return False
    stored = load_state()["secret"]
    return hmac.compare_digest(candidate.encode("utf-8"), stored.encode("utf-8"))


def clean_public_base_url(value: Any) -> str | None:
    """Validate the opt-in public origin: https, bare origin, a real host name.

    IPs and local names are rejected; they would widen access without being reachable.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise SchoolError("public_base_url must be an https:// address or null.", status_code=422)
    text = value.strip()
    if not text:
        return None
    if len(text) > MAX_PUBLIC_URL:
        raise SchoolError(
            f"The public address is longer than {MAX_PUBLIC_URL} characters.", status_code=422
        )
    if any(ord(char) < 33 for char in text):
        raise SchoolError("The public address may not contain spaces or control characters.", status_code=422)
    parts = urlsplit(text)
    if parts.scheme.lower() != "https":
        raise SchoolError(
            "The public address must start with https:// so the feed is encrypted in transit.",
            status_code=422,
        )
    if parts.username or parts.password or "@" in parts.netloc:
        raise SchoolError("The public address may not contain a user name or password.", status_code=422)
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise SchoolError(
            "Enter only the address itself, such as https://my-mac.tail1234.ts.net, "
            "without a path. Semester OS adds the feed path.",
            status_code=422,
        )
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        raise SchoolError("The public address has an invalid port.", status_code=422) from None
    if not host:
        raise SchoolError("The public address needs a host name.", status_code=422)
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        raise SchoolError(
            "Use the host name your tunnel gives you, not an IP address.", status_code=422
        )
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise SchoolError(
            "That address only works on this computer. The public address is the one "
            "your tunnel gives you, reachable from the internet.",
            status_code=422,
        )
    if not _HOSTNAME_RE.match(host):
        raise SchoolError("The public address is not a valid host name.", status_code=422)
    netloc = host if port in (None, 443) else f"{host}:{port}"
    return f"https://{netloc}"


def set_public_base_url(value: Any) -> dict[str, Any]:
    """Save or clear the opt-in public origin. The secret is untouched."""
    cleaned = clean_public_base_url(value)
    with _state_lock:
        state = _load_locked()
        state["public_base_url"] = cleaned
        _write_state(state)
    return state


# ---------------------------------------------------------------------------
# Admission: what the Host-check middleware lets through
# ---------------------------------------------------------------------------

def is_feed_path(path: str | None) -> bool:
    return bool(path) and FEED_PATH_RE.match(path) is not None


def came_through_proxy(headers: Mapping[str, str]) -> bool:
    """True when any header a reverse proxy or tunnel adds is present."""
    return any(headers.get(name) for name in FORWARDING_HEADERS)


def _public_netloc(state: Mapping[str, Any] | None = None) -> str | None:
    base = (state or load_state()).get("public_base_url")
    if not base:
        return None
    return urlsplit(base).netloc.lower() or None


def public_host_matches(host_header: str | None, state: Mapping[str, Any] | None = None) -> bool:
    """True when a Host header names the saved public origin."""
    if not host_header:
        return False
    netloc = _public_netloc(state)
    if not netloc:
        return False
    host = host_header.strip().lower()
    if host == netloc:
        return True
    # A proxy may or may not state the default port.
    return ":" not in netloc and host == f"{netloc}:443"


ADMIT_FEED = "feed"
ADMIT_LOCAL = "local"
ADMIT_HIDDEN = "hidden"


def admit(method: str, path: str, headers: Mapping[str, str]) -> str:
    """Classify a request for the guard middleware: "feed", "hidden" (404) or "local".

    Proxied requests on a loopback Host are hidden, or a Host-rewriting tunnel
    would expose the whole dashboard, /api/bootstrap included.
    """
    host = headers.get("host")
    host_local = security.host_is_allowed(host)
    feed = method.upper() in ("GET", "HEAD") and is_feed_path(path)

    if host_local:
        if feed:
            return ADMIT_FEED
        return ADMIT_HIDDEN if came_through_proxy(headers) else ADMIT_LOCAL
    if host and public_host_matches(host):
        return ADMIT_FEED if feed else ADMIT_HIDDEN
    return ADMIT_LOCAL


# ---------------------------------------------------------------------------
# Logs: the secret never reaches one
# ---------------------------------------------------------------------------

_REDACT_RE = re.compile(r"/calendar/[^/\s\"'?#]+\.ics")
REDACTED_PATH = "/calendar/<redacted>.ics"


def redact(text: Any) -> Any:
    if isinstance(text, str):
        return _REDACT_RE.sub(REDACTED_PATH, text)
    return text


class _RedactFeedPath(logging.Filter):
    """Rewrites the feed path in a log record's message and arguments."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: redact(value) for key, value in record.args.items()}
        return True


_REDACTOR = _RedactFeedPath()


def install_log_redaction() -> None:
    """Attach the redacting filter to uvicorn's loggers. Idempotent.

    uvicorn's dictConfig keeps existing filters, so attaching at import is enough.
    """
    for name in ("uvicorn.access", "uvicorn.error", "uvicorn"):
        logger = logging.getLogger(name)
        if _REDACTOR not in logger.filters:
            logger.addFilter(_REDACTOR)


# ---------------------------------------------------------------------------
# Versions and readers: the two small tables this module owns
# ---------------------------------------------------------------------------

FEED_SCHEMA_SQL = """
-- What the calendar feed last published per UID. Additive: a UID that stops
-- appearing keeps its row, and if it ever comes back its SEQUENCE carries on
-- from where it was instead of starting over and being ignored by a client.
CREATE TABLE IF NOT EXISTS calendar_feed_versions (
    uid           TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    sequence      INTEGER NOT NULL DEFAULT 0,
    first_seen_at TEXT NOT NULL,
    modified_at   TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL
);

-- Which kind of calendar app last read the feed, and whether through the local
-- or the public address. Only the kind is kept, never the user agent or an IP.
CREATE TABLE IF NOT EXISTS calendar_feed_clients (
    client        TEXT PRIMARY KEY,
    via           TEXT,
    last_fetch_at TEXT,
    fetch_count   INTEGER NOT NULL DEFAULT 0
);
"""


def ensure_schema() -> None:
    """Create this module's tables in the database db.DB_PATH points at. Idempotent."""
    key = str(db.DB_PATH)
    if key in _schema_ready:
        return
    with get_db() as conn:
        conn.executescript(FEED_SCHEMA_SQL)
    _schema_ready.add(key)


def classify_client(user_agent: str | None) -> str:
    ua = (user_agent or "").lower()
    if "google" in ua:
        return "google"
    if any(word in ua for word in ("calendaragent", "dataaccessd", "ical/", "apple", "macos/", "ios/")):
        return "apple"
    if any(word in ua for word in ("outlook", "microsoft", "exchange", "office")):
        return "outlook"
    if "mozilla" in ua:
        return "browser"
    return "other"


def record_fetch(user_agent: str | None, via: str) -> None:
    """Remember that a kind of client read the feed. Never fails the request."""
    try:
        ensure_schema()
        client = classify_client(user_agent)
        with get_db() as conn:
            conn.execute(
                "INSERT INTO calendar_feed_clients (client, via, last_fetch_at, fetch_count) "
                "VALUES (?, ?, ?, 1) ON CONFLICT(client) DO UPDATE SET via = excluded.via, "
                "last_fetch_at = excluded.last_fetch_at, fetch_count = fetch_count + 1",
                (client, via, now_iso()),
            )
    except Exception:  # noqa: BLE001 - bookkeeping must never break a subscription
        LOG.exception("Could not record a calendar feed read.")


# ---------------------------------------------------------------------------
# Building the components, from school_gcal's own event bodies
# ---------------------------------------------------------------------------

def feed_window(today: date | None = None) -> tuple[date, date]:
    """Inclusive campus days covered: 30 back, forward to max(200 days, last meeting), capped at 400."""
    anchor = today or datetime.now(LOCAL_TZ).date()
    end = anchor + timedelta(days=WINDOW_FORWARD_DAYS)
    with get_db() as conn:
        row = conn.execute("SELECT MAX(end_date) AS last FROM course_meetings").fetchone()
    last = school_gcal._parse_day(row["last"]) if row else None
    if last and last > end:
        end = min(last, anchor + timedelta(days=WINDOW_MAX_FORWARD_DAYS))
    return anchor - timedelta(days=WINDOW_BACK_DAYS), end


def _uid_from_key(key: str) -> str:
    """class:10001:lecture -> class-10001-lecture@semester-os."""
    local = re.sub(r"[^A-Za-z0-9_.-]+", "-", key.replace(":", "-")).strip("-")
    return f"{local}@{UID_DOMAIN}"


def _meeting_rows() -> list[Any]:
    with get_db() as conn:
        return conn.execute(
            "SELECT m.*, c.code AS course_code, c.title AS course_title "
            "FROM course_meetings m JOIN courses c ON c.id = m.course_id "
            "ORDER BY c.code, m.start_time, m.id"
        ).fetchall()


def _meeting_in_window(row: Any, window: tuple[date, date]) -> bool:
    start = school_gcal._parse_day(row["start_date"])
    end = school_gcal._parse_day(row["end_date"])
    if end is not None and end < window[0]:
        return False
    if start is not None and start > window[1]:
        return False
    return True


def _close_open_rule(body: dict[str, Any]) -> None:
    """Give a weekly rule with no UNTIL one, fixed from its own first session."""
    rules = body.get("recurrence") or []
    if not rules or "UNTIL=" in rules[0].upper():
        return
    start = body.get("start") or {}
    try:
        first = datetime.strptime(str(start.get("dateTime")), "%Y-%m-%dT%H:%M:%S").date()
    except ValueError:
        return
    last_day = first + timedelta(days=OPEN_MEETING_DAYS)
    until = (
        datetime.combine(last_day, time(23, 59, 59), LOCAL_TZ)
        .astimezone(timezone.utc)
        .strftime("%Y%m%dT%H%M%SZ")
    )
    body["recurrence"] = [f"{rules[0]};UNTIL={until}"] + list(rules[1:])


def build_components(today: date | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every VEVENT as a dict, sorted by UID, built with school_gcal's body and classify helpers."""
    window = feed_window(today)
    components: list[dict[str, Any]] = []
    counts = {"classes": 0, "deadlines": 0, "exams": 0, "events": 0}

    for row in _meeting_rows():
        if not _meeting_in_window(row, window):
            continue
        built = school_gcal._meeting_event(row)
        if built is None:
            continue
        key, body = built
        _close_open_rule(body)
        code = str(row["course_code"] or "").strip()
        components.append(_component(key, body, "class", code, transparent=False))
        counts["classes"] += 1

    for row in school_gcal._assignment_rows():
        if school_gcal._classify_assignment(row, window) != "project":
            continue
        built = school_gcal._deadline_event(row)
        if built is None:
            continue
        key, body = built
        item = dict(row)
        is_exam = item.get("kind") == "exam"
        due = school.parse_instant(item.get("due_at"))
        ends = school.parse_instant(item.get("ends_at"))
        is_block = due is not None and ends is not None and ends > due
        kind = "exam" if is_exam else "deadline"
        url = str(item.get("url") or "").strip()
        components.append(
            _component(
                key,
                body,
                kind,
                str(item.get("course_code") or "").strip(),
                transparent=not (is_exam or is_block),
                url=url if url.lower().startswith(("https://", "http://")) else None,
            )
        )
        counts["exams" if is_exam else "deadlines"] += 1

    for row in school_gcal._event_rows():
        if school_gcal._classify_event(row, window) != "project":
            continue
        built = school_gcal._school_event_body(row)
        if built is None:
            continue
        key, body = built
        components.append(
            _component(key, body, "event", str(dict(row).get("course_code") or "").strip(), transparent=False)
        )
        counts["events"] += 1

    components.sort(key=lambda item: item["uid"])
    meta = {
        "window": {"start": window[0].isoformat(), "end": window[1].isoformat()},
        "counts": counts,
    }
    return components, meta


def _component(
    key: str,
    body: Mapping[str, Any],
    kind: str,
    course_code: str,
    *,
    transparent: bool,
    url: str | None = None,
) -> dict[str, Any]:
    all_day = "date" in (body.get("start") or {})
    categories = [KIND_CATEGORY[kind]]
    if course_code:
        categories.append(course_code)
    return {
        "uid": _uid_from_key(key),
        "kind": kind,
        "summary": body.get("summary") or "(untitled)",
        "location": body.get("location"),
        "description": body.get("description"),
        "start": dict(body.get("start") or {}),
        "end": dict(body.get("end") or {}),
        "recurrence": list(body.get("recurrence") or []),
        "categories": categories,
        "color": KIND_COLORS[kind],
        "transparent": transparent or all_day,
        "url": url,
    }


def _fingerprint(component: Mapping[str, Any]) -> str:
    payload = json.dumps(component, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _stamp_versions(components: list[dict[str, Any]]) -> None:
    """Attach sequence/created/modified, bumping changed UIDs.

    IMMEDIATE transaction plus a lock so concurrent refreshes cannot double-bump.
    """
    ensure_schema()
    stamp = now_iso()
    with _versions_lock, get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = {
                row["uid"]: row
                for row in conn.execute("SELECT * FROM calendar_feed_versions").fetchall()
            }
            for component in components:
                fingerprint = _fingerprint(component)
                row = existing.get(component["uid"])
                if row is None:
                    conn.execute(
                        "INSERT INTO calendar_feed_versions (uid, fingerprint, sequence, "
                        "first_seen_at, modified_at, last_seen_at) VALUES (?, ?, 0, ?, ?, ?)",
                        (component["uid"], fingerprint, stamp, stamp, stamp),
                    )
                    sequence, created, modified = 0, stamp, stamp
                elif row["fingerprint"] != fingerprint:
                    sequence = int(row["sequence"]) + 1
                    created, modified = row["first_seen_at"], stamp
                    conn.execute(
                        "UPDATE calendar_feed_versions SET fingerprint = ?, sequence = ?, "
                        "modified_at = ?, last_seen_at = ? WHERE uid = ?",
                        (fingerprint, sequence, stamp, stamp, component["uid"]),
                    )
                else:
                    sequence = int(row["sequence"])
                    created, modified = row["first_seen_at"], row["modified_at"]
                    if row["last_seen_at"][:13] != stamp[:13]:
                        # At most hourly, so refreshes do not rewrite every row.
                        conn.execute(
                            "UPDATE calendar_feed_versions SET last_seen_at = ? WHERE uid = ?",
                            (stamp, component["uid"]),
                        )
                component["sequence"] = sequence
                component["created_at"] = created
                component["modified_at"] = modified
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise


# ---------------------------------------------------------------------------
# RFC 5545 serialization
# ---------------------------------------------------------------------------

def escape_text(value: Any) -> str:
    """TEXT escaping (RFC 5545 section 3.3.11), with control characters removed."""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(char for char in text if char in "\n\t" or ord(char) >= 32)
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _param_value(value: str) -> str:
    """A parameter value, quoted when it holds a character that would end it."""
    cleaned = "".join(char for char in value if char != '"' and ord(char) >= 32)
    return f'"{cleaned}"' if any(char in cleaned for char in ":;,") else cleaned


def fold_line(line: str) -> str:
    """Fold at 75 octets without splitting UTF-8; continuations hold 74 plus the leading space."""
    encoded = line.encode("utf-8")
    if len(encoded) <= FOLD_OCTETS:
        return line
    pieces: list[str] = []
    current = bytearray()
    limit = FOLD_OCTETS
    for char in line:
        char_bytes = char.encode("utf-8")
        if len(current) + len(char_bytes) > limit:
            pieces.append(current.decode("utf-8"))
            current = bytearray()
            limit = FOLD_OCTETS - 1
        current.extend(char_bytes)
    pieces.append(current.decode("utf-8"))
    return "\r\n ".join(pieces)


def content_line(name: str, value: str, params: Iterable[tuple[str, str]] = ()) -> str:
    head = name + "".join(f";{key}={_param_value(val)}" for key, val in params)
    return fold_line(f"{head}:{value}")


def _utc_stamp(value: str) -> str:
    moment = db.parse_iso(value) or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _time_line(name: str, block: Mapping[str, Any]) -> tuple[str, str | None]:
    """DTSTART or DTEND from a Google-shaped block. Returns the line and any TZID."""
    if block.get("date"):
        day = datetime.strptime(str(block["date"]), "%Y-%m-%d")
        return content_line(name, day.strftime("%Y%m%d"), [("VALUE", "DATE")]), None
    raw = str(block.get("dateTime") or "")
    zone = block.get("timeZone")
    if zone:
        local = datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S")
        return content_line(name, local.strftime("%Y%m%dT%H%M%S"), [("TZID", str(zone))]), str(zone)
    moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=LOCAL_TZ)
    return content_line(name, moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")), None


def _offset_text(offset: timedelta) -> str:
    total = int(offset.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    text = f"{sign}{hours:02d}{minutes:02d}"
    return f"{text}{seconds:02d}" if seconds else text


def _transitions(zone: ZoneInfo, start: datetime, end: datetime) -> list[tuple[datetime, timedelta, timedelta]]:
    """Every UTC offset change between two instants: daily steps, bisected to the second."""
    def offset_at(moment: datetime) -> timedelta:
        return moment.astimezone(zone).utcoffset() or timedelta(0)

    found: list[tuple[datetime, timedelta, timedelta]] = []
    cursor = start
    before = offset_at(cursor)
    step = timedelta(days=1)
    while cursor < end:
        following = cursor + step
        after = offset_at(following)
        if after != before:
            low, high = cursor, following
            while high - low > timedelta(seconds=1):
                middle = low + (high - low) / 2
                if offset_at(middle) == before:
                    low = middle
                else:
                    high = middle
            found.append((high.replace(microsecond=0), before, after))
            before = after
        cursor = following
    return found


def vtimezone_lines(zone_name: str, first_day: date, last_day: date) -> list[str]:
    """A VTIMEZONE from zoneinfo, Jan 1 of the first year through the end of the last.

    Each transition's DTSTART is in the local time it leaves (RFC 5545 3.6.5).
    """
    zone = ZoneInfo(zone_name)
    start = datetime(first_day.year, 1, 1, tzinfo=timezone.utc)
    end = datetime(last_day.year + 1, 1, 1, tzinfo=timezone.utc)

    def block(moment_utc: datetime, before: timedelta, after: timedelta) -> list[str]:
        local = moment_utc.astimezone(zone)
        kind = "DAYLIGHT" if local.dst() else "STANDARD"
        wall = (moment_utc + before).replace(tzinfo=None)
        return [
            f"BEGIN:{kind}",
            content_line("DTSTART", wall.strftime("%Y%m%dT%H%M%S")),
            content_line("TZOFFSETFROM", _offset_text(before)),
            content_line("TZOFFSETTO", _offset_text(after)),
            content_line("TZNAME", escape_text(local.tzname() or zone_name)),
            f"END:{kind}",
        ]

    initial = start.astimezone(zone).utcoffset() or timedelta(0)
    lines = ["BEGIN:VTIMEZONE", content_line("TZID", zone_name)]
    lines += block(start, initial, initial)
    for moment, before, after in _transitions(zone, start, end):
        lines += block(moment, before, after)
    lines.append("END:VTIMEZONE")
    return lines


def _event_lines(component: Mapping[str, Any]) -> tuple[list[str], set[str], date | None]:
    """One VEVENT, the TZIDs it references and the first day it touches."""
    stamp = _utc_stamp(component["modified_at"])
    lines = [
        "BEGIN:VEVENT",
        content_line("UID", escape_text(component["uid"])),
        content_line("DTSTAMP", stamp),
        content_line("CREATED", _utc_stamp(component["created_at"])),
        content_line("LAST-MODIFIED", stamp),
        content_line("SEQUENCE", str(int(component["sequence"]))),
    ]
    zones: set[str] = set()
    start_line, start_zone = _time_line("DTSTART", component["start"])
    end_line, end_zone = _time_line("DTEND", component["end"])
    lines += [start_line, end_line]
    zones.update(zone for zone in (start_zone, end_zone) if zone)
    for rule in component["recurrence"]:
        name, _, value = str(rule).partition(":")
        if name.upper() == "RRULE" and value:
            lines.append(content_line("RRULE", value))
    lines.append(content_line("SUMMARY", escape_text(component["summary"])))
    if component.get("location"):
        lines.append(content_line("LOCATION", escape_text(component["location"])))
    if component.get("description"):
        lines.append(content_line("DESCRIPTION", escape_text(component["description"])))
    if component.get("url"):
        lines.append(content_line("URL", str(component["url"]), [("VALUE", "URI")]))
    lines.append(content_line("CATEGORIES", ",".join(escape_text(item) for item in component["categories"])))
    lines.append(content_line("COLOR", component["color"]))
    lines.append(content_line("TRANSP", "TRANSPARENT" if component["transparent"] else "OPAQUE"))
    lines.append(content_line("STATUS", "CONFIRMED"))
    lines.append("END:VEVENT")

    first: date | None = None
    start_block = component["start"]
    try:
        if start_block.get("date"):
            first = date.fromisoformat(str(start_block["date"]))
        elif start_block.get("dateTime"):
            first = date.fromisoformat(str(start_block["dateTime"])[:10])
    except ValueError:
        first = None
    return lines, zones, first


def render(today: date | None = None) -> tuple[bytes, dict[str, Any]]:
    """The whole feed as bytes, plus what the Connect page reports about it."""
    components, meta = build_components(today)
    _stamp_versions(components)

    body_lines: list[str] = []
    zones: set[str] = set()
    first_days: list[date] = []
    for component in components:
        lines, used, first = _event_lines(component)
        body_lines += lines
        zones |= used
        if first:
            first_days.append(first)

    window_start = date.fromisoformat(meta["window"]["start"])
    window_end = date.fromisoformat(meta["window"]["end"])
    lines = [
        "BEGIN:VCALENDAR",
        content_line("VERSION", "2.0"),
        content_line("PRODID", escape_text(PRODID)),
        content_line("CALSCALE", "GREGORIAN"),
        content_line("NAME", escape_text(CALENDAR_NAME)),
        content_line("X-WR-CALNAME", escape_text(CALENDAR_NAME)),
        content_line("DESCRIPTION", escape_text(CALENDAR_DESCRIPTION)),
        content_line("X-WR-CALDESC", escape_text(CALENDAR_DESCRIPTION)),
        content_line("X-WR-TIMEZONE", escape_text(LOCAL_TZ_NAME)),
        content_line("COLOR", CALENDAR_COLOR),
        content_line("REFRESH-INTERVAL", REFRESH_INTERVAL, [("VALUE", "DURATION")]),
        content_line("X-PUBLISHED-TTL", REFRESH_INTERVAL),
    ]
    for zone_name in sorted(zones):
        first = min(first_days + [window_start])
        lines += vtimezone_lines(zone_name, first, window_end)
    lines += body_lines
    lines.append("END:VCALENDAR")

    payload = ("\r\n".join(lines) + "\r\n").encode("utf-8")
    meta["etag"] = '"' + hashlib.sha256(payload).hexdigest()[:32] + '"'
    meta["event_count"] = len(components)
    return payload, meta


# ---------------------------------------------------------------------------
# What the Connect page reads
# ---------------------------------------------------------------------------

def feed_urls(state: Mapping[str, Any]) -> dict[str, str | None]:
    path = f"{FEED_PATH_PREFIX}{state['secret']}{FEED_SUFFIX}"
    local = f"http://{security.HOST}:{security.PORT}{path}"
    public_base = state.get("public_base_url")
    public = f"{public_base}{path}" if public_base else None
    return {
        "path": path,
        "local_url": local,
        "local_webcal_url": "webcal://" + local.split("://", 1)[1],
        "public_url": public,
        "public_webcal_url": ("webcal://" + public.split("://", 1)[1]) if public else None,
    }


def describe(today: date | None = None) -> dict[str, Any]:
    """Links, coverage and readers for the Connect page. Carries the secret.

    Readers from before the last rotation are dropped.
    """
    state = load_state()
    _, meta = render(today)
    ensure_schema()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT client, via, last_fetch_at, fetch_count FROM calendar_feed_clients "
            "ORDER BY last_fetch_at DESC"
        ).fetchall()
    rotated_at = db.parse_iso(state.get("rotated_at"))
    readers = []
    for row in rows:
        seen = db.parse_iso(row["last_fetch_at"])
        if rotated_at and seen and seen < rotated_at:
            continue
        readers.append(
            {
                "client": row["client"],
                "label": CLIENT_LABELS.get(row["client"], CLIENT_LABELS["other"]),
                "via": row["via"],
                "last_fetch_at": row["last_fetch_at"],
            }
        )
    return {
        **feed_urls(state),
        "public_base_url": state.get("public_base_url"),
        "created_at": state.get("created_at"),
        "rotated_at": state.get("rotated_at"),
        "timezone": LOCAL_TZ_NAME,
        "window": meta["window"],
        "counts": meta["counts"],
        "event_count": meta["event_count"],
        "readers": readers,
    }
