"""SQLite access layer: data/semester.db, idempotent schema run on every startup.

Additive: rows are retired by status, never deleted. JSON is stored as TEXT and
decoded on the way out. Timestamps are ISO-8601 UTC ending in "Z".
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

from config import CONFIG, REPO_ROOT

DATA_DIR = REPO_ROOT / "data"

# SEMESTER_OS_DB points local checks at a throwaway database.
DB_PATH = Path(os.environ.get("SEMESTER_OS_DB") or (DATA_DIR / "semester.db"))

SCHEMA_SQL = """
-- One row per agent run. The only kind today is 'school_note': a typed note
-- read by the school-editor agent through the Claude Code CLI (see runner.py).
-- The row keeps the raw answer the agent printed in result_md, next to the
-- structured proposal the note row carries, so a proposal that looks wrong can
-- be traced back to what the agent actually said.
--
-- Additive like everything else here. A run is never deleted: a failed or
-- cancelled one keeps its row and its reason.
CREATE TABLE IF NOT EXISTS actions (
    id          INTEGER PRIMARY KEY,
    type        TEXT NOT NULL,
    payload     TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    result_md   TEXT,
    error       TEXT,
    created_at  TEXT,
    started_at  TEXT,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status);
"""

# --- School -----------------------------------------------------------------
# JSON TEXT columns: courses.instructors and courses.grading_scheme (objects),
# course_meetings.days (array of SCHOOL_DAY_CODES letters).

SCHOOL_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS courses (
    id             INTEGER PRIMARY KEY,
    code           TEXT NOT NULL UNIQUE,
    title          TEXT NOT NULL,
    credit_hours   REAL,
    instructors    TEXT,
    term           TEXT,
    grading_scheme TEXT,
    color          TEXT,
    created_at     TEXT
);

-- A weekly recurrence, stored the way the registrar states it: which days, at
-- what time, for how long, between two dates. The server expands it into dated
-- events on request; no calendar row is ever materialized here.
CREATE TABLE IF NOT EXISTS course_meetings (
    id           INTEGER PRIMARY KEY,
    course_id    INTEGER NOT NULL REFERENCES courses(id),
    kind         TEXT NOT NULL,
    days         TEXT NOT NULL,
    start_time   TEXT NOT NULL,
    duration_min INTEGER NOT NULL,
    location     TEXT,
    start_date   TEXT,
    end_date     TEXT,
    crn          TEXT
);

CREATE TABLE IF NOT EXISTS course_platforms (
    id             INTEGER PRIMARY KEY,
    course_id      INTEGER NOT NULL REFERENCES courses(id),
    platform       TEXT NOT NULL,
    url            TEXT,
    auth_mode      TEXT,
    notes          TEXT,
    last_synced_at TEXT
);

CREATE TABLE IF NOT EXISTS assignments (
    id            INTEGER PRIMARY KEY,
    course_id     INTEGER NOT NULL REFERENCES courses(id),
    source        TEXT,
    source_id     TEXT,
    title         TEXT NOT NULL,
    kind          TEXT,
    due_at        TEXT,
    points        REAL,
    weight_pct    REAL,
    grade_points  REAL,
    grade_max     REAL,
    status        TEXT NOT NULL DEFAULT 'pending',
    brief_md      TEXT,
    url           TEXT,
    notes         TEXT,
    gcal_event_id TEXT,
    harvested_at  TEXT,
    updated_at    TEXT,
    ends_at       TEXT,
    location      TEXT
);

CREATE TABLE IF NOT EXISTS announcements (
    id           INTEGER PRIMARY KEY,
    course_id    INTEGER REFERENCES courses(id),
    source       TEXT,
    title        TEXT,
    body_md      TEXT,
    url          TEXT,
    posted_at    TEXT,
    seen         INTEGER DEFAULT 0,
    harvested_at TEXT
);

CREATE TABLE IF NOT EXISTS school_todos (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL,
    course_id     INTEGER REFERENCES courses(id),
    assignment_id INTEGER REFERENCES assignments(id),
    due_at        TEXT,
    done          INTEGER DEFAULT 0,
    origin        TEXT DEFAULT 'manual',
    created_at    TEXT,
    completed_at  TEXT
);

-- A sentence the user typed about their semester, and what came of it.
--
-- The row is the whole life of one note. It arrives as `text` and nothing else,
-- with status 'running', because the agent that reads it is started in the same
-- request. When that agent answers, the parsed and validated changeset lands in
-- `proposal` and the status becomes 'proposed'; when it does not answer, or
-- answers something this server refuses, the reason lands in `error` and the
-- status becomes 'failed'. Neither of those writes a single row anywhere else:
-- a proposal is a suggestion, and only the user confirming it turns it into
-- assignments and todos, at which point `applied_changes` records what was
-- actually written and `gcal` records what Google did or did not do with it.
--
-- Additive, like everything else here. A note that failed keeps its row and its
-- reason, and a proposal the user did not want becomes 'discarded' rather than
-- disappearing: the semester is a record of what was asked as well as of what
-- was done.
--
-- action_id points at the run that produced the proposal, so the raw agent
-- answer stays readable on the action row next to the structured result. It
-- is nullable because the note row exists before the action does.
CREATE TABLE IF NOT EXISTS school_notes (
    id              INTEGER PRIMARY KEY,
    text            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'running',
    action_id       INTEGER REFERENCES actions(id),
    proposal        TEXT,
    agent_md        TEXT,
    applied_changes TEXT,
    gcal            TEXT,
    error           TEXT,
    created_at      TEXT,
    resolved_at     TEXT,
    applied_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_school_notes_status ON school_notes(status, id DESC);
CREATE INDEX IF NOT EXISTS idx_school_notes_action ON school_notes(action_id);

-- A one-off thing on the calendar that is not a piece of graded work: office
-- hours, a meeting with an advisor, a study session, a talk, anything the user
-- said "put this on my calendar" about. Graded work with a time and a room (an
-- exam, a presentation) is an assignment with due_at and ends_at instead; see
-- .claude/agents/school-editor.md for where that line is drawn.
--
-- Additive, like every other table in this section. Cancelling an event is a
-- status change with the moment it happened, never a DELETE: the row stays so
-- the semester can be read back, and the Google copy is what disappears.
--
-- Times. A timed event stores start_at and end_at as ISO-8601 UTC instants with
-- a Z suffix, normalized on the way in. An all day event (all_day = 1) stores
-- bare YYYY-MM-DD dates, and end_at is then the LAST day of the event,
-- inclusive, because that is how a person says "Oct 12 to Oct 14". The Google
-- projection turns it into the exclusive end Google expects. A timed event with
-- no end is projected as one hour; an all day event with no end is that one day.
--
-- origin says who created the row ('note' through an applied note, 'manual'
-- through anything else), and note_id points at the note when there is one.
CREATE TABLE IF NOT EXISTS school_events (
    id           INTEGER PRIMARY KEY,
    title        TEXT NOT NULL,
    course_id    INTEGER REFERENCES courses(id),
    start_at     TEXT NOT NULL,
    end_at       TEXT,
    all_day      INTEGER DEFAULT 0,
    location     TEXT,
    notes        TEXT,
    status       TEXT NOT NULL DEFAULT 'scheduled',
    origin       TEXT DEFAULT 'note',
    note_id      INTEGER REFERENCES school_notes(id),
    created_at   TEXT,
    updated_at   TEXT,
    cancelled_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_school_events_window ON school_events(status, start_at);

CREATE INDEX IF NOT EXISTS idx_course_meetings_course  ON course_meetings(course_id);
CREATE INDEX IF NOT EXISTS idx_course_platforms_course ON course_platforms(course_id);
CREATE INDEX IF NOT EXISTS idx_assignments_course      ON assignments(course_id, due_at);
CREATE INDEX IF NOT EXISTS idx_assignments_status      ON assignments(status);
CREATE INDEX IF NOT EXISTS idx_assignments_due         ON assignments(due_at);
CREATE INDEX IF NOT EXISTS idx_announcements_course    ON announcements(course_id, posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_school_todos_open       ON school_todos(done, due_at);
CREATE INDEX IF NOT EXISTS idx_school_todos_assignment ON school_todos(assignment_id);
-- A harvester that reads the same page twice must not create the item twice.
-- Rows typed by hand have no source_id and are left out of the constraint.
CREATE UNIQUE INDEX IF NOT EXISTS idx_assignments_source
    ON assignments(course_id, source, source_id) WHERE source_id IS NOT NULL;
"""

# --- Calendar ---------------------------------------------------------------
# external_events is our copy of the feeds: rows are never deleted, only marked
# is_active = 0. Key (source, uid, instance_start): one row per occurrence.
# All-day rows store bare dates, and end_at keeps the feed's exclusive DTEND.
CALENDAR_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS external_events (
    id             INTEGER PRIMARY KEY,
    source         TEXT NOT NULL,
    uid            TEXT NOT NULL,
    instance_start TEXT NOT NULL,
    title          TEXT,
    location       TEXT,
    description    TEXT,
    start_at       TEXT,
    end_at         TEXT,
    all_day        INTEGER DEFAULT 0,
    first_seen_at  TEXT,
    last_seen_at   TEXT,
    is_active      INTEGER DEFAULT 1
);

-- One row per feed: whether the last fetch worked, when, and what it saw. The
-- Sync view reads this and nothing else, so a feed that has been failing for a
-- week says so instead of quietly showing a stale calendar.
CREATE TABLE IF NOT EXISTS ics_sync_state (
    source       TEXT PRIMARY KEY,
    last_sync_at TEXT,
    ok           INTEGER,
    error        TEXT,
    event_count  INTEGER
);

-- The little that has to survive a restart on the Google side: the ids of the
-- calendars earlier versions created (kept only so status() can name them as
-- legacy; nothing writes to them now), the last sync, and the last error the
-- OAuth flow produced.
-- The tokens themselves live in data/.google_token.json with 0600 permissions,
-- never in the database, which has no such protection.
CREATE TABLE IF NOT EXISTS gcal_state (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT
);

-- The instance key is the identity of a row, so the database enforces it rather
-- than the sync remembering to.
CREATE UNIQUE INDEX IF NOT EXISTS idx_external_events_key
    ON external_events(source, uid, instance_start);
CREATE INDEX IF NOT EXISTS idx_external_events_window
    ON external_events(source, start_at);
CREATE INDEX IF NOT EXISTS idx_external_events_active
    ON external_events(is_active, start_at);
"""

# Nullable columns added to `assignments` after it shipped. `notes` is the user's
# own note (brief_md is the syllabus's). `ends_at` only makes sense with a timed
# due_at; school.py enforces that.
ASSIGNMENT_ADDED_COLUMNS = (
    ("notes", "TEXT"),
    ("ends_at", "TEXT"),
    ("location", "TEXT"),
)

# Columns whose TEXT payload holds serialized JSON.
ACTION_JSON_FIELDS = ("payload",)
COURSE_JSON_FIELDS = ("instructors", "grading_scheme")
MEETING_JSON_FIELDS = ("days",)

ACTION_STATUSES = ("pending", "running", "done", "failed", "cancelled")

# Closed vocabularies; anything else is a 422 at the API edge.
COURSE_MEETING_KINDS = ("lecture", "lab", "pso")
COURSE_PLATFORMS = ("brightspace", "gradescope", "ed", "website", "other")
COURSE_PLATFORM_AUTH_MODES = ("browser", "api", "public")
ASSIGNMENT_SOURCES = ("manual", "brightspace", "gradescope", "ed", "website", "syllabus")
ASSIGNMENT_KINDS = ("hw", "quiz", "exam", "project", "reading", "other")
ASSIGNMENT_STATUSES = ("pending", "in_progress", "submitted", "graded", "dropped")
SCHOOL_TODO_ORIGINS = ("manual", "agent", "assignment")

# Note lifecycle: running -> proposed | failed, proposed -> applied | discarded.
# Any other transition is a 409.
SCHOOL_NOTE_STATUSES = ("running", "proposed", "failed", "applied", "discarded")

SCHOOL_NOTE_JSON_FIELDS = ("proposal", "applied_changes", "gcal")

SCHOOL_EVENT_STATUSES = ("scheduled", "cancelled")

SCHOOL_EVENT_ORIGINS = ("note", "manual")

# Color tokens the frontend themes. Assigned once in course id order, never rewritten.
COURSE_COLOR_SLOTS = (
    "course-1",
    "course-2",
    "course-3",
    "course-4",
    "course-5",
    "course-6",
)

ICS_SOURCES = ("outlook", "brightspace")

# Google primary, pulled by school_gcal.sync_pull(). Shares external_events but
# is not an ICS feed, so it is kept out of ICS_SOURCES.
GCAL_SOURCE = "gcal"
EXTERNAL_EVENT_SOURCES = ICS_SOURCES + (GCAL_SOURCE,)

# Read-side label for school_events served beside the feeds. Not a row owner in
# external_events, so it stays out of EXTERNAL_EVENT_SOURCES.
NOTES_EVENT_SOURCE = "notes"
CALENDAR_READ_SOURCES = EXTERNAL_EVENT_SOURCES + (NOTES_EVENT_SOURCE,)

# Stored UTC instants are shown in this zone, never the server clock's.
LOCAL_TZ_NAME = CONFIG.timezone

# Default term for new courses; None when config.yaml names none.
SCHOOL_TERM = CONFIG.term

# Registrar day letters (R = Thursday, U = Sunday) mapped to date.weekday().
SCHOOL_DAY_CODES = {"M": 0, "T": 1, "W": 2, "R": 3, "F": 4, "S": 5, "U": 6}


def now_iso() -> str:
    """Current UTC instant as an ISO-8601 string with a Z suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str | None) -> datetime | None:
    """Parse one of our ISO-8601 strings. Returns None when unparseable."""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection with the pragmas this project relies on."""
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


@contextmanager
def get_db(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """Short lived connection. One per request or per background job."""
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def _migrate_assignments(conn: sqlite3.Connection) -> None:
    """Add ASSIGNMENT_ADDED_COLUMNS that are missing. Idempotent, never drops."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(assignments)").fetchall()}
    if not columns:  # no table yet; the caller has not run SCHOOL_SCHEMA_SQL
        return
    for name, definition in ASSIGNMENT_ADDED_COLUMNS:
        if name not in columns:
            conn.execute(f"ALTER TABLE assignments ADD COLUMN {name} {definition}")


def init_db(db_path: Path | str | None = None) -> None:
    """Create the schema if it is missing. Safe to call on every startup."""
    with get_db(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(SCHOOL_SCHEMA_SQL)
        _migrate_assignments(conn)
        conn.executescript(CALENDAR_SCHEMA_SQL)


def _decode(value: Any) -> Any:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        # Tolerate hand edited rows: return the raw text instead of failing.
        return value


def encode_json(value: Any) -> str | None:
    """Serialize a Python value for a JSON TEXT column."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def row_to_dict(row: sqlite3.Row | None, json_fields: Sequence[str] = ()) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    for field in json_fields:
        if field in data:
            data[field] = _decode(data[field])
    return data


def action_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return row_to_dict(row, ACTION_JSON_FIELDS)


def course_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return row_to_dict(row, COURSE_JSON_FIELDS)


def meeting_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return row_to_dict(row, MEETING_JSON_FIELDS)


def school_note_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return row_to_dict(row, SCHOOL_NOTE_JSON_FIELDS)
