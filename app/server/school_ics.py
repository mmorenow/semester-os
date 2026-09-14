"""ICS ingestion for the Outlook and Brightspace feeds into external_events.

Rows are never deleted (vanished occurrences get is_active = 0), upserts key on
(source, uid, instance_start), and feed failures are recorded in ics_sync_state.
Feed URLs are bearer secrets: never stored in the database, only the host is logged.
"""

from __future__ import annotations

import sqlite3
import threading
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events

import config
import db
from db import (
    CALENDAR_READ_SOURCES,
    LOCAL_TZ_NAME,
    ICS_SOURCES,
    NOTES_EVENT_SOURCE,
    get_db,
    now_iso,
)

# Shared with /api/school/schedule so validation errors read the same.
from school import (  # noqa: F401
    MAX_SCHEDULE_DAYS,
    SchoolError,
    _require_date,
)

LOCAL_TZ = ZoneInfo(LOCAL_TZ_NAME)

# Callers name a source, never a URL, so request input never reaches urlopen().
if tuple(config.FEED_NAMES) != tuple(ICS_SOURCES):
    raise RuntimeError("config.FEED_NAMES and db.ICS_SOURCES name different feeds.")

WINDOW_BACK_DAYS = 7
WINDOW_FORWARD_DAYS = 120

REFRESH_INTERVAL_SECONDS = 30 * 60

FETCH_TIMEOUT_SECONDS = 45
USER_AGENT = "semester-os/0.1"

# Feeds are untrusted input: bound download size, row count and text lengths.
MAX_FEED_BYTES = 8 * 1024 * 1024
MAX_EVENTS_PER_SYNC = 5000
MAX_TITLE = 500
MAX_LOCATION = 500
MAX_DESCRIPTION = 5000
MAX_UID = 500

# One sync per source at a time (background task vs. manual Sync now).
_locks: dict[str, threading.Lock] = {source: threading.Lock() for source in ICS_SOURCES}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def feed_url(source: str) -> str | None:
    """The feed URL from config.yaml, or None. Re-read per call, so edits apply without restart."""
    return config.feed_url(source)


def _feed_host(url: str) -> str:
    """The host of a feed URL, the only part safe to log (the query string is the credential)."""
    try:
        return urlsplit(url).netloc.split("@")[-1] or "unknown host"
    except ValueError:
        return "unknown host"


# ---------------------------------------------------------------------------
# Fetching and parsing
# ---------------------------------------------------------------------------

class FeedError(Exception):
    """A feed could not be read. The message is safe to show and to store."""


def _fetch(url: str) -> str:
    """Download a feed over https only, bounded in time and size."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc:
        raise FeedError("The feed URL must be an https:// address.")

    host = _feed_host(url)
    request = urllib.request.Request(
        url, method="GET", headers={"User-Agent": USER_AGENT, "Accept": "text/calendar"}
    )
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            final = getattr(response, "geturl", lambda: url)() or url
            if urlsplit(final).scheme != "https":
                # urllib follows redirects to plain http (even localhost); refuse the body.
                raise FeedError(f"{host} redirected the feed to an address that is not https://.")
            body = response.read(MAX_FEED_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise FeedError(f"{host} answered HTTP {exc.code}.") from None
    except urllib.error.URLError as exc:
        raise FeedError(f"{host} could not be reached ({exc.reason}).") from None
    except (TimeoutError, OSError) as exc:
        raise FeedError(f"{host} could not be reached ({exc}).") from None

    if len(body) > MAX_FEED_BYTES:
        raise FeedError(f"{host} returned more than {MAX_FEED_BYTES // (1024 * 1024)} MB.")
    if not body:
        raise FeedError(f"{host} returned an empty document.")
    return body.decode("utf-8", errors="replace")


def _window(today: date | None = None) -> tuple[datetime, datetime]:
    """The sync window as two aware UTC instants."""
    anchor = today or datetime.now(timezone.utc).date()
    start = datetime.combine(anchor - timedelta(days=WINDOW_BACK_DAYS), time.min, timezone.utc)
    end = datetime.combine(anchor + timedelta(days=WINDOW_FORWARD_DAYS), time.max, timezone.utc)
    return start, end


def _text(value: Any, limit: int) -> str | None:
    """One property of a VEVENT as bounded plain text."""
    if value is None:
        return None
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    # Drop control characters except newline and tab.
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    if not text:
        return None
    return text[:limit]


def _utc_iso(moment: datetime) -> str:
    """A datetime as ISO-8601 UTC with Z. Naive values are taken as campus local time."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=LOCAL_TZ)
    return (
        moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def _instance(component: Any) -> dict[str, Any] | None:
    """One expanded occurrence as a row, or None when it has no UID/start or is cancelled."""
    uid = _text(component.get("UID"), MAX_UID)
    if not uid:
        return None

    status = _text(component.get("STATUS"), 40)
    if status and status.upper() == "CANCELLED":
        return None

    start_prop = component.get("DTSTART")
    if start_prop is None or getattr(start_prop, "dt", None) is None:
        return None
    raw_start = start_prop.dt
    end_prop = component.get("DTEND")
    raw_end = getattr(end_prop, "dt", None) if end_prop is not None else None

    # datetime is a subclass of date, so the timed case has to be tested first.
    if isinstance(raw_start, datetime):
        all_day = 0
        start_at = _utc_iso(raw_start)
        end_at = _utc_iso(raw_end) if isinstance(raw_end, datetime) else None
    elif isinstance(raw_start, date):
        all_day = 1
        start_at = raw_start.isoformat()
        # All-day DTEND is exclusive (as in Google); stored as received.
        end_at = raw_end.isoformat() if isinstance(raw_end, date) else None
    else:
        return None

    return {
        "uid": uid,
        "instance_start": start_at,
        "title": _text(component.get("SUMMARY"), MAX_TITLE),
        "location": _text(component.get("LOCATION"), MAX_LOCATION),
        "description": _text(component.get("DESCRIPTION"), MAX_DESCRIPTION),
        "start_at": start_at,
        "end_at": end_at,
        "all_day": all_day,
    }


def parse_feed(text: str, window_start: datetime, window_end: datetime) -> list[dict[str, Any]]:
    """Expand a feed's recurrences over the window, as rows ready to upsert."""
    try:
        calendar = icalendar.Calendar.from_ical(text)
    except (ValueError, KeyError, TypeError) as exc:
        raise FeedError(f"The feed is not valid iCalendar ({exc}).") from None

    try:
        occurrences = recurring_ical_events.of(calendar, skip_bad_series=True).between(
            window_start, window_end
        )
    except Exception as exc:  # noqa: BLE001 - a third party expander, any failure is data
        raise FeedError(f"The feed's recurrences could not be expanded ({exc}).") from None

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for component in occurrences:
        row = _instance(component)
        if row is None:
            continue
        key = (row["uid"], row["instance_start"])
        if key in seen:
            # Duplicate occurrence (e.g. an override keeping its original start).
            continue
        seen.add(key)
        rows.append(row)
        if len(rows) >= MAX_EVENTS_PER_SYNC:
            break
    return rows


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _write_state(
    conn: sqlite3.Connection,
    source: str,
    *,
    ok: bool,
    error: str | None,
    event_count: int | None,
) -> None:
    """Record the last fetch result. A failure keeps the previous event_count."""
    conn.execute(
        "INSERT INTO ics_sync_state (source, last_sync_at, ok, error, event_count) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(source) DO UPDATE SET "
        "  last_sync_at = excluded.last_sync_at, "
        "  ok = excluded.ok, "
        "  error = excluded.error, "
        "  event_count = COALESCE(excluded.event_count, ics_sync_state.event_count)",
        (source, now_iso(), 1 if ok else 0, error, event_count),
    )


def _store(
    conn: sqlite3.Connection,
    source: str,
    rows: list[dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
) -> dict[str, int]:
    """Upsert this run's occurrences, then retire missing ones.

    Retirement is limited to the expanded window so older rows keep is_active.
    """
    timestamp = now_iso()
    for row in rows:
        conn.execute(
            "INSERT INTO external_events (source, uid, instance_start, title, location, "
            "description, start_at, end_at, all_day, first_seen_at, last_seen_at, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1) "
            "ON CONFLICT(source, uid, instance_start) DO UPDATE SET "
            "  title = excluded.title, "
            "  location = excluded.location, "
            "  description = excluded.description, "
            "  start_at = excluded.start_at, "
            "  end_at = excluded.end_at, "
            "  all_day = excluded.all_day, "
            "  last_seen_at = excluded.last_seen_at, "
            "  is_active = 1",
            (
                source,
                row["uid"],
                row["instance_start"],
                row["title"],
                row["location"],
                row["description"],
                row["start_at"],
                row["end_at"],
                row["all_day"],
                timestamp,
                timestamp,
            ),
        )

    # Bare-date bounds compare correctly against both date and datetime start_at.
    low = window_start.date().isoformat()
    high = (window_end.date() + timedelta(days=1)).isoformat()

    # Keys seen this run. Not a timestamp compare: now_iso() has 1s resolution.
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS ics_seen (uid TEXT, instance_start TEXT)")
    conn.execute("DELETE FROM ics_seen")
    conn.executemany(
        "INSERT INTO ics_seen (uid, instance_start) VALUES (?, ?)",
        [(row["uid"], row["instance_start"]) for row in rows],
    )
    retired = conn.execute(
        "UPDATE external_events SET is_active = 0 "
        "WHERE source = ? AND is_active = 1 AND start_at >= ? AND start_at < ? "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM ics_seen s "
        "  WHERE s.uid = external_events.uid AND s.instance_start = external_events.instance_start"
        ")",
        (source, low, high),
    ).rowcount

    return {"stored": len(rows), "retired": int(retired or 0)}


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

def sync_source(source: str, today: date | None = None) -> dict[str, Any]:
    """Fetch one feed and reconcile it into external_events.

    Feed problems never raise: they are recorded in ics_sync_state and returned.
    """
    if source not in ICS_SOURCES:
        raise SchoolError(
            f"Unknown source '{source}'. Valid values: {', '.join(ICS_SOURCES)}.",
            status_code=422,
        )

    with _locks[source]:
        url = feed_url(source)
        if not url:
            message = (
                f"No URL is set for this feed. Add {config.feed_setting_name(source)} "
                "to read it."
            )
            with get_db() as conn:
                _write_state(conn, source, ok=False, error=message, event_count=None)
                return _state_row(conn, source)

        window_start, window_end = _window(today)
        try:
            text = _fetch(url)
            rows = parse_feed(text, window_start, window_end)
        except FeedError as exc:
            with get_db() as conn:
                _write_state(conn, source, ok=False, error=str(exc), event_count=None)
                return _state_row(conn, source)

        with get_db() as conn:
            counts = _store(conn, source, rows, window_start, window_end)
            _write_state(conn, source, ok=True, error=None, event_count=counts["stored"])
            state = _state_row(conn, source)
        state["retired"] = counts["retired"]
        return state


def sync_all(today: date | None = None) -> dict[str, Any]:
    """Read both feeds now. One failure never stops the other."""
    return {source: sync_source(source, today=today) for source in ICS_SOURCES}


def _state_row(
    conn: sqlite3.Connection, source: str, configured: bool | None = None
) -> dict[str, Any]:
    """One source's last run for the Sync view.

    `configured` overrides the URL check for non-feed sources (school_gcal's pull).
    """
    if configured is None:
        configured = feed_url(source) is not None
    row = conn.execute(
        "SELECT source, last_sync_at, ok, error, event_count FROM ics_sync_state WHERE source = ?",
        (source,),
    ).fetchone()
    if row is None:
        return {
            "source": source,
            "last_sync_at": None,
            "ok": None,
            "error": None,
            "event_count": 0,
            "configured": configured,
        }
    return {
        "source": source,
        "last_sync_at": row["last_sync_at"],
        "ok": bool(row["ok"]) if row["ok"] is not None else None,
        "error": row["error"],
        "event_count": int(row["event_count"] or 0),
        "configured": configured,
    }


def sync_status() -> dict[str, Any]:
    """Both ics_sync_state rows, with the feeds that have never run included."""
    with get_db() as conn:
        return {source: _state_row(conn, source) for source in ICS_SOURCES}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _display(row: sqlite3.Row) -> dict[str, Any]:
    """One stored occurrence converted from UTC to local date and HH:MM."""
    all_day = bool(row["all_day"])
    if all_day:
        day = (row["start_at"] or "")[:10]
        start_hm: str | None = None
        end_hm: str | None = None
    else:
        started = db.parse_iso(row["start_at"])
        if started is None:
            return {}
        local_start = started.astimezone(LOCAL_TZ)
        day = local_start.date().isoformat()
        start_hm = local_start.strftime("%H:%M")
        ended = db.parse_iso(row["end_at"])
        end_hm = ended.astimezone(LOCAL_TZ).strftime("%H:%M") if ended else None

    return {
        "id": int(row["id"]),
        "source": row["source"],
        "title": row["title"],
        "location": row["location"],
        "date": day,
        "start": start_hm,
        "end": end_hm,
        "all_day": 1 if all_day else 0,
        "is_active": int(row["is_active"] or 0),
    }


def _display_school_event(row: sqlite3.Row) -> dict[str, Any]:
    """A school_events row in _display()'s shape, under source 'notes', plus course and notes.

    Cancelled maps to is_active 0; a missing end stays null.
    """
    all_day = bool(row["all_day"])
    if all_day:
        day = (row["start_at"] or "")[:10]
        start_hm: str | None = None
        end_hm: str | None = None
    else:
        started = db.parse_iso(row["start_at"])
        if started is None:
            return {}
        local_start = started.astimezone(LOCAL_TZ)
        day = local_start.date().isoformat()
        start_hm = local_start.strftime("%H:%M")
        ended = db.parse_iso(row["end_at"])
        end_hm = ended.astimezone(LOCAL_TZ).strftime("%H:%M") if ended else None

    return {
        "id": int(row["id"]),
        "source": NOTES_EVENT_SOURCE,
        "title": row["title"],
        "location": row["location"],
        "date": day,
        "start": start_hm,
        "end": end_hm,
        "all_day": 1 if all_day else 0,
        "is_active": 1 if row["status"] == "scheduled" else 0,
        "course_id": row["course_id"],
        "course_code": row["course_code"],
        "notes": row["notes"],
    }


def list_external_events(
    start_raw: str | None,
    end_raw: str | None,
    source: str | None = None,
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    """Occurrences in an inclusive YYYY-MM-DD window (max MAX_SCHEDULE_DAYS), local time, sorted."""
    start = _require_date(start_raw, "start")
    end = _require_date(end_raw, "end")
    if end < start:
        raise SchoolError("'end' cannot be before 'start'.", status_code=422)
    span = (end - start).days + 1
    if span > MAX_SCHEDULE_DAYS:
        raise SchoolError(
            f"The window is {span} days. Ask for at most {MAX_SCHEDULE_DAYS} days at a time.",
            status_code=422,
        )
    # Includes 'gcal' (written by school_gcal) and 'notes' (read from school_events).
    if source is not None and source not in CALENDAR_READ_SOURCES:
        raise SchoolError(
            f"Unknown source '{source}'. Valid values: {', '.join(CALENDAR_READ_SOURCES)}.",
            status_code=422,
        )

    # Pad a day each side: start_at is UTC; the exact local-date filter happens below.
    low = (start - timedelta(days=1)).isoformat()
    high = (end + timedelta(days=2)).isoformat()

    clauses = ["start_at >= ?", "start_at < ?"]
    params: list[Any] = [low, high]
    if source is not None:
        clauses.append("source = ?")
        params.append(source)
    if not include_inactive:
        clauses.append("is_active = 1")

    rows: list[sqlite3.Row] = []
    note_rows: list[sqlite3.Row] = []
    with get_db() as conn:
        if source != NOTES_EVENT_SOURCE:
            rows = conn.execute(
                f"SELECT * FROM external_events WHERE {' AND '.join(clauses)} "
                "ORDER BY start_at, id",
                params,
            ).fetchall()
        if source is None or source == NOTES_EVENT_SOURCE:
            status_sql = "" if include_inactive else " AND e.status = 'scheduled'"
            note_rows = conn.execute(
                "SELECT e.*, c.code AS course_code FROM school_events e "
                "LEFT JOIN courses c ON c.id = e.course_id "
                f"WHERE e.start_at >= ? AND e.start_at < ?{status_sql} "
                "ORDER BY e.start_at, e.id",
                (low, high),
            ).fetchall()

    low_day = start.isoformat()
    high_day = end.isoformat()
    events = []
    for row in rows:
        event = _display(row)
        if not event or not (low_day <= event["date"] <= high_day):
            continue
        events.append(event)
    for row in note_rows:
        event = _display_school_event(row)
        if not event or not (low_day <= event["date"] <= high_day):
            continue
        events.append(event)

    # All-day events (no start) sort first within their day.
    events.sort(key=lambda event: (event["date"], event["start"] or "", event["title"] or ""))
    return events
