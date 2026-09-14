"""Data layer behind /api/school/*: courses, schedule, assignments, todos, events, grades.

Additive (no deletes; status changes instead), closed enums refused with 422
before any write. The schedule and grades are computed on read, never stored.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

import db
from db import (
    ASSIGNMENT_KINDS,
    ASSIGNMENT_STATUSES,
    LOCAL_TZ_NAME,
    COURSE_COLOR_SLOTS,
    SCHOOL_DAY_CODES,
    SCHOOL_EVENT_ORIGINS,
    get_db,
    now_iso,
)

LOCAL_TZ = ZoneInfo(LOCAL_TZ_NAME)

# About one semester; a month view needs 42.
MAX_SCHEDULE_DAYS = 120

MAX_TODO_TITLE = 300
MAX_DUE_AT = 40
MAX_ASSIGNMENT_TITLE = 300
MAX_URL = 2000
MAX_ASSIGNMENT_NOTES = 4000
MAX_LOCATION = 300
MAX_EVENT_TITLE = 300

# due_at -> ends_at. Longer than a day is a mistyped date, not an exam.
MAX_ASSIGNMENT_BLOCK = timedelta(hours=24)
MAX_EVENT_SPAN = timedelta(days=14)

_BARE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_GRADE_VALUE = 1_000_000.0

# Above 100 allowed for extra credit.
MIN_TARGET_PCT = 0.0
MAX_TARGET_PCT = 110.0

# Absorbs float error so item weights summing to 64.9999 still cover a 65% bucket.
WEIGHT_TOLERANCE = 0.01


class SchoolError(Exception):
    """A problem the caller can act on, with the HTTP status it deserves."""

    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _ensure_course_colors(conn: sqlite3.Connection) -> int:
    """Assign a palette slot (by id order) to courses without one; never reassign.

    Called on every course read, so loader-inserted courses get a color lazily.
    """
    rows = conn.execute("SELECT id, color FROM courses ORDER BY id").fetchall()
    assigned = 0
    for index, row in enumerate(rows):
        if row["color"]:
            continue
        conn.execute(
            "UPDATE courses SET color = ? WHERE id = ? AND (color IS NULL OR color = '')",
            (COURSE_COLOR_SLOTS[index % len(COURSE_COLOR_SLOTS)], int(row["id"])),
        )
        assigned += 1
    return assigned


# ---------------------------------------------------------------------------
# Validation helpers (all raise before any write)
# ---------------------------------------------------------------------------

def _require_enum(value: str, allowed: Sequence[str], field: str) -> str:
    if value not in allowed:
        raise SchoolError(
            f"Unknown {field} '{value}'. Valid values: {', '.join(allowed)}.",
            status_code=422,
        )
    return value


def _require_date(value: str | None, field: str) -> date:
    """Parse a YYYY-MM-DD date or raise 422."""
    if not value or not isinstance(value, str):
        raise SchoolError(f"'{field}' is required and must be a YYYY-MM-DD date.", status_code=422)
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise SchoolError(
            f"'{field}' must be a YYYY-MM-DD date, not '{value}'.", status_code=422
        ) from None


def _clean_due_at(value: str | None, field: str = "due_at") -> str | None:
    """Accept a date or ISO-8601 instant, stored as sent (a bare date is not midnight)."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise SchoolError(f"'{field}' must be a date or an ISO-8601 timestamp.", status_code=422)
    text = value.strip()
    if not text:
        return None
    if len(text) > MAX_DUE_AT:
        raise SchoolError(f"'{field}' is too long to be a timestamp.", status_code=422)
    if db.parse_iso(text) is None:
        raise SchoolError(
            f"'{field}' must be a date or an ISO-8601 timestamp, not '{text}'.", status_code=422
        )
    return text


def _clean_title(value: Any, field: str = "title", limit: int = MAX_TODO_TITLE) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchoolError(f"'{field}' is required.", status_code=422)
    title = " ".join(value.split())
    if len(title) > limit:
        raise SchoolError(
            f"'{field}' is too long. Keep it under {limit} characters.", status_code=422
        )
    return title


def _clean_url(value: Any, field: str = "url") -> str | None:
    """An http(s) link, or None. Refuses other schemes (e.g. javascript:) since it renders as a link."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise SchoolError(f"'{field}' must be a string or null.", status_code=422)
    text = value.strip()
    if not text:
        return None
    if len(text) > MAX_URL:
        raise SchoolError(
            f"'{field}' is too long. Keep it under {MAX_URL} characters.", status_code=422
        )
    if not text.lower().startswith(("http://", "https://")):
        raise SchoolError(f"'{field}' must start with http:// or https://.", status_code=422)
    return text


def _clean_grade(value: Any, field: str) -> float | None:
    """A non-negative finite number, or None. Above the max is allowed (extra credit)."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchoolError(f"'{field}' must be a number or null.", status_code=422)
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):  # NaN / infinities
        raise SchoolError(f"'{field}' must be a finite number.", status_code=422)
    if number < 0:
        raise SchoolError(f"'{field}' cannot be negative.", status_code=422)
    if number > MAX_GRADE_VALUE:
        raise SchoolError(
            f"'{field}' is larger than any grade could be ({MAX_GRADE_VALUE:.0f}).",
            status_code=422,
        )
    return number


def _clean_notes(value: Any, field: str = "notes") -> str | None:
    """A bounded note with line breaks kept. None or empty clears it."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise SchoolError(f"'{field}' must be a string or null.", status_code=422)
    text = value.strip()
    if not text:
        return None
    if len(text) > MAX_ASSIGNMENT_NOTES:
        raise SchoolError(
            f"'{field}' is too long. Keep it under {MAX_ASSIGNMENT_NOTES} characters.",
            status_code=422,
        )
    return text


def _clean_location(value: Any, field: str = "location") -> str | None:
    """A one-line location. None or empty clears it."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise SchoolError(f"'{field}' must be a string or null.", status_code=422)
    text = " ".join(value.split())
    if not text:
        return None
    if len(text) > MAX_LOCATION:
        raise SchoolError(
            f"'{field}' is too long. Keep it under {MAX_LOCATION} characters.", status_code=422
        )
    return text


def is_bare_date(value: Any) -> bool:
    """True for a plain YYYY-MM-DD, which means a whole day and no instant."""
    return isinstance(value, str) and _BARE_DATE_RE.match(value.strip()) is not None


def parse_instant(value: Any) -> datetime | None:
    """A stored timestamp as an aware datetime; naive means campus local time.

    Unlike db.parse_iso (naive = UTC), this matches how the browser reads deadlines.
    Bare dates and unparseable values return None.
    """
    if not isinstance(value, str) or not value.strip() or is_bare_date(value):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    return parsed


def utc_z(moment: datetime) -> str:
    """An aware datetime as this database's ISO-8601 UTC string."""
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_ends_at(value: Any, field: str = "ends_at") -> str | None:
    """An instant with a clock time, stored as sent, or None. Bare dates are refused."""
    clean = _clean_due_at(value, field)
    if clean is None:
        return None
    if is_bare_date(clean) or parse_instant(clean) is None:
        raise SchoolError(
            f"'{field}' must be a timestamp with a clock time, like 2026-10-12T22:00:00Z, "
            f"not '{clean}'.",
            status_code=422,
        )
    return clean


def plan_assignment_block(
    current_due: Any,
    current_ends: Any,
    *,
    due_at: Any = None,
    ends_at: Any = None,
    due_at_given: bool = False,
    ends_at_given: bool = False,
) -> str | None:
    """The ends_at after a change, or 422. Shared by PATCH, create and note changesets.

    ends_at needs a timed due_at and must fall within (due_at, due_at + 24h]. If
    due_at moves without ends_at, the block keeps its length (or clears if untimed).
    """
    new_due = _clean_due_at(due_at) if due_at_given else current_due
    if ends_at_given:
        new_ends = _clean_ends_at(ends_at)
    else:
        new_ends = current_ends or None
        if due_at_given and new_ends is not None:
            old_start = parse_instant(current_due)
            new_start = parse_instant(new_due)
            old_end = parse_instant(new_ends)
            if old_start is not None and new_start is not None and old_end is not None:
                new_ends = utc_z(new_start + (old_end - old_start))
            else:
                new_ends = None

    if new_ends is None:
        return None
    start = parse_instant(new_due)
    if start is None:
        raise SchoolError(
            "'ends_at' needs a due_at with a clock time: the block starts at due_at, and a "
            "bare-date or missing deadline has no start time.",
            status_code=422,
        )
    end = parse_instant(new_ends)
    if end is None or end <= start:
        raise SchoolError("'ends_at' must be after 'due_at'.", status_code=422)
    if end - start > MAX_ASSIGNMENT_BLOCK:
        raise SchoolError(
            "'ends_at' is more than 24 hours after 'due_at', which is a mistyped date rather "
            "than an exam.",
            status_code=422,
        )
    return new_ends


def _clean_flag(value: Any, field: str) -> int:
    """A 0 or a 1, and nothing else."""
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int) and value in (0, 1):
        return value
    raise SchoolError(f"'{field}' must be 0 or 1.", status_code=422)


def _require_course(conn: sqlite3.Connection, course_id: int) -> int:
    row = conn.execute("SELECT id FROM courses WHERE id = ?", (course_id,)).fetchone()
    if row is None:
        raise SchoolError(f"No course with id {course_id}.", status_code=404)
    return int(row["id"])


def _require_assignment(conn: sqlite3.Connection, assignment_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
    if row is None:
        raise SchoolError(f"No assignment with id {assignment_id}.", status_code=404)
    return row


# ---------------------------------------------------------------------------
# Response shapes (explicit fields so new columns don't leak into the API)
# ---------------------------------------------------------------------------

def _meeting_payload(row: sqlite3.Row) -> dict[str, Any]:
    meeting = db.meeting_to_dict(row)
    days = meeting.get("days")
    return {
        "id": meeting["id"],
        "kind": meeting["kind"],
        "days": days if isinstance(days, list) else [],
        "start_time": meeting["start_time"],
        "duration_min": meeting["duration_min"],
        "location": meeting["location"],
        "start_date": meeting["start_date"],
        "end_date": meeting["end_date"],
        "crn": meeting["crn"],
    }


def _platform_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "platform": row["platform"],
        "url": row["url"],
        "auth_mode": row["auth_mode"],
        "notes": row["notes"],
        "last_synced_at": row["last_synced_at"],
    }


def _course_payload(
    row: sqlite3.Row,
    meetings: list[dict[str, Any]],
    platforms: list[dict[str, Any]],
) -> dict[str, Any]:
    course = db.course_to_dict(row)
    instructors = course.get("instructors")
    return {
        "id": course["id"],
        "code": course["code"],
        "title": course["title"],
        "credit_hours": course["credit_hours"],
        "instructors": instructors if isinstance(instructors, list) else [],
        "term": course["term"],
        "grading_scheme": course["grading_scheme"],
        "color": course["color"],
        "meetings": meetings,
        "platforms": platforms,
    }


def _assignment_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "course_id": row["course_id"],
        "course_code": row["course_code"],
        "title": row["title"],
        "kind": row["kind"],
        "due_at": row["due_at"],
        "points": row["points"],
        "weight_pct": row["weight_pct"],
        "grade_points": row["grade_points"],
        "grade_max": row["grade_max"],
        "status": row["status"],
        "brief_md": row["brief_md"],
        "notes": row["notes"],
        "url": row["url"],
        "ends_at": row["ends_at"],
        "location": row["location"],
        "updated_at": row["updated_at"],
    }


def _announcement_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "course_id": row["course_id"],
        "course_code": row["course_code"],
        "source": row["source"],
        "title": row["title"],
        "body_md": row["body_md"],
        "url": row["url"],
        "posted_at": row["posted_at"],
        "seen": int(row["seen"] or 0),
    }


def _todo_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "course_id": row["course_id"],
        "course_code": row["course_code"],
        "assignment_id": row["assignment_id"],
        "due_at": row["due_at"],
        "done": int(row["done"] or 0),
        "origin": row["origin"],
        "created_at": row["created_at"],
    }


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------

def list_courses() -> list[dict[str, Any]]:
    """Every course of the term with its meetings and its platforms attached."""
    with get_db() as conn:
        _ensure_course_colors(conn)
        courses = conn.execute("SELECT * FROM courses ORDER BY code").fetchall()

        meetings: dict[int, list[dict[str, Any]]] = {}
        for row in conn.execute(
            "SELECT * FROM course_meetings ORDER BY course_id, start_time, id"
        ).fetchall():
            meetings.setdefault(int(row["course_id"]), []).append(_meeting_payload(row))

        platforms: dict[int, list[dict[str, Any]]] = {}
        for row in conn.execute(
            "SELECT * FROM course_platforms ORDER BY course_id, platform, id"
        ).fetchall():
            platforms.setdefault(int(row["course_id"]), []).append(_platform_payload(row))

    return [
        _course_payload(
            row,
            meetings.get(int(row["id"]), []),
            platforms.get(int(row["id"]), []),
        )
        for row in courses
    ]


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

def _end_time(start_time: str, duration_min: int) -> str:
    """"HH:MM" plus a number of minutes, as "HH:MM"."""
    try:
        start = datetime.strptime(start_time.strip(), "%H:%M")
    except (AttributeError, ValueError):
        return start_time
    return (start + timedelta(minutes=int(duration_min or 0))).strftime("%H:%M")


def _weekday_indexes(days: Any) -> set[int]:
    """Python weekday numbers for a meeting's day letters; unknown letters are skipped."""
    if not isinstance(days, list):
        return set()
    indexes: set[int] = set()
    for code in days:
        if not isinstance(code, str):
            continue
        index = SCHOOL_DAY_CODES.get(code.strip().upper())
        if index is not None:
            indexes.add(index)
    return indexes


def _dates_between(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def expand_schedule(start_raw: str | None, end_raw: str | None) -> list[dict[str, Any]]:
    """Expand weekly meetings into dated sessions inside a window.

    A meeting without start/end dates is treated as running all term.
    """
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

    with get_db() as conn:
        rows = conn.execute(
            "SELECT m.*, c.code AS course_code, c.title AS course_title "
            "FROM course_meetings m JOIN courses c ON c.id = m.course_id "
            "ORDER BY m.start_time, m.id"
        ).fetchall()

    events: list[dict[str, Any]] = []
    for row in rows:
        meeting = db.meeting_to_dict(row)
        weekdays = _weekday_indexes(meeting.get("days"))
        if not weekdays:
            continue

        window_start = start
        window_end = end
        if meeting.get("start_date"):
            try:
                window_start = max(start, _require_date(meeting["start_date"], "start_date"))
            except SchoolError:
                pass  # malformed stored date: no bound
        if meeting.get("end_date"):
            try:
                window_end = min(end, _require_date(meeting["end_date"], "end_date"))
            except SchoolError:
                pass
        if window_end < window_start:
            continue

        start_time = meeting["start_time"]
        end_time = _end_time(start_time, meeting["duration_min"])
        for day in _dates_between(window_start, window_end):
            if day.weekday() not in weekdays:
                continue
            events.append(
                {
                    "meeting_id": meeting["id"],
                    "course_id": meeting["course_id"],
                    "course_code": row["course_code"],
                    "course_title": row["course_title"],
                    "kind": meeting["kind"],
                    "date": day.isoformat(),
                    "start": start_time,
                    "end": end_time,
                    "location": meeting["location"],
                }
            )

    events.sort(key=lambda event: (event["date"], event["start"], event["course_code"]))
    return events


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------

def list_assignments(course_id: int | None = None, status: str | None = None) -> list[dict[str, Any]]:
    """The work, nearest deadline first, with undated items at the end."""
    clauses: list[str] = []
    params: list[Any] = []

    if status is not None:
        _require_enum(status, ASSIGNMENT_STATUSES, "assignment status")
        clauses.append("a.status = ?")
        params.append(status)

    with get_db() as conn:
        if course_id is not None:
            _require_course(conn, course_id)
            clauses.append("a.course_id = ?")
            params.append(course_id)

        where_sql = " AND ".join(clauses) if clauses else "1=1"
        rows = conn.execute(
            "SELECT a.*, c.code AS course_code FROM assignments a "
            "JOIN courses c ON c.id = a.course_id "
            f"WHERE {where_sql} "
            "ORDER BY (a.due_at IS NULL) ASC, a.due_at ASC, a.id ASC",
            params,
        ).fetchall()

    return [_assignment_payload(row) for row in rows]


def _assignment_detail(conn: sqlite3.Connection, assignment_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT a.*, c.code AS course_code FROM assignments a "
        "JOIN courses c ON c.id = a.course_id WHERE a.id = ?",
        (assignment_id,),
    ).fetchone()
    if row is None:
        raise SchoolError(f"No assignment with id {assignment_id}.", status_code=404)
    return _assignment_payload(row)


def get_assignment(assignment_id: int) -> dict[str, Any]:
    """One assignment, whole. 404 when there is no such row."""
    with get_db() as conn:
        return _assignment_detail(conn, assignment_id)


def create_assignment(
    course_id: Any,
    title: Any,
    *,
    kind: Any = None,
    due_at: Any = None,
    points: Any = None,
    url: Any = None,
    notes: Any = None,
    ends_at: Any = None,
    location: Any = None,
) -> dict[str, Any]:
    """Add a manual assignment to a course, validating everything before the INSERT.

    source_id stays NULL so manual rows stay out of the harvester's unique index;
    weight_pct is not settable here (it comes from a syllabus).
    """
    clean_title = _clean_title(title, "title", MAX_ASSIGNMENT_TITLE)
    clean_kind = (
        _require_enum(kind, ASSIGNMENT_KINDS, "assignment kind") if kind is not None else None
    )
    clean_due = _clean_due_at(due_at)
    clean_points = _clean_grade(points, "points")
    clean_url = _clean_url(url)
    clean_notes = _clean_notes(notes)
    clean_ends = plan_assignment_block(
        None, None, due_at=clean_due, ends_at=ends_at, due_at_given=True, ends_at_given=True
    )
    clean_location = _clean_location(location)

    with get_db() as conn:
        if not isinstance(course_id, int) or isinstance(course_id, bool):
            raise SchoolError("'course_id' must be the id of a course.", status_code=422)
        _require_course(conn, course_id)
        timestamp = now_iso()
        cursor = conn.execute(
            "INSERT INTO assignments (course_id, source, source_id, title, kind, due_at, points, "
            "weight_pct, status, brief_md, url, notes, harvested_at, updated_at, ends_at, "
            "location) "
            "VALUES (?, 'manual', NULL, ?, ?, ?, ?, NULL, 'pending', NULL, ?, ?, ?, ?, ?, ?)",
            (
                course_id,
                clean_title,
                clean_kind,
                clean_due,
                clean_points,
                clean_url,
                clean_notes,
                timestamp,
                timestamp,
                clean_ends,
                clean_location,
            ),
        )
        return _assignment_detail(conn, int(cursor.lastrowid))


def update_assignment(
    assignment_id: int,
    *,
    status: Any = None,
    grade_points: Any = None,
    grade_max: Any = None,
    notes: Any = None,
    title: Any = None,
    kind: Any = None,
    due_at: Any = None,
    points: Any = None,
    ends_at: Any = None,
    location: Any = None,
    status_given: bool = False,
    grade_points_given: bool = False,
    grade_max_given: bool = False,
    notes_given: bool = False,
    title_given: bool = False,
    kind_given: bool = False,
    due_at_given: bool = False,
    points_given: bool = False,
    ends_at_given: bool = False,
    location_given: bool = False,
) -> dict[str, Any]:
    """Patch any subset of an assignment's fields; '_given' flags distinguish null from absent.

    A grade on a pending/in_progress item promotes it to 'graded' unless the same
    request sets a status. ends_at rules are plan_assignment_block's.
    """
    updates: dict[str, Any] = {}

    if status_given:
        if not isinstance(status, str):
            raise SchoolError("'status' must be a string.", status_code=422)
        updates["status"] = _require_enum(status, ASSIGNMENT_STATUSES, "assignment status")
    if grade_points_given:
        updates["grade_points"] = _clean_grade(grade_points, "grade_points")
    if grade_max_given:
        updates["grade_max"] = _clean_grade(grade_max, "grade_max")
    if notes_given:
        updates["notes"] = _clean_notes(notes)
    if title_given:
        updates["title"] = _clean_title(title, "title", MAX_ASSIGNMENT_TITLE)
    if kind_given:
        updates["kind"] = (
            _require_enum(kind, ASSIGNMENT_KINDS, "assignment kind") if kind is not None else None
        )
    if due_at_given:
        updates["due_at"] = _clean_due_at(due_at)
    if points_given:
        updates["points"] = _clean_grade(points, "points")
    if location_given:
        updates["location"] = _clean_location(location)

    with get_db() as conn:
        row = _require_assignment(conn, assignment_id)

        if due_at_given or ends_at_given:
            planned_ends = plan_assignment_block(
                row["due_at"],
                row["ends_at"],
                due_at=updates.get("due_at"),
                ends_at=ends_at,
                due_at_given=due_at_given,
                ends_at_given=ends_at_given,
            )
            if ends_at_given or planned_ends != row["ends_at"]:
                updates["ends_at"] = planned_ends

        if (
            not status_given
            and updates.get("grade_points") is not None
            and row["status"] in ("pending", "in_progress")
        ):
            updates["status"] = "graded"

        if updates:
            updates["updated_at"] = now_iso()
            assignments = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"UPDATE assignments SET {assignments} WHERE id = ?",
                list(updates.values()) + [assignment_id],
            )
        return _assignment_detail(conn, assignment_id)


def set_assignment_status(assignment_id: int, status: str) -> dict[str, Any]:
    """Move an assignment along its status enum and nothing else."""
    return update_assignment(assignment_id, status=status, status_given=True)


# ---------------------------------------------------------------------------
# Announcements (read-only except the seen flag)
# ---------------------------------------------------------------------------

def list_announcements(course_id: int | None = None, seen: Any = None) -> list[dict[str, Any]]:
    """Newest first, undated last. Optionally one course, optionally unread."""
    clauses: list[str] = []
    params: list[Any] = []

    if seen is not None:
        clauses.append("COALESCE(n.seen, 0) = ?")
        params.append(_clean_flag(seen, "seen"))

    with get_db() as conn:
        if course_id is not None:
            _require_course(conn, course_id)
            clauses.append("n.course_id = ?")
            params.append(course_id)

        where_sql = " AND ".join(clauses) if clauses else "1=1"
        rows = conn.execute(
            "SELECT n.*, c.code AS course_code FROM announcements n "
            "LEFT JOIN courses c ON c.id = n.course_id "
            f"WHERE {where_sql} "
            "ORDER BY (n.posted_at IS NULL) ASC, n.posted_at DESC, n.id DESC",
            params,
        ).fetchall()

    return [_announcement_payload(row) for row in rows]


def _announcement_detail(conn: sqlite3.Connection, announcement_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT n.*, c.code AS course_code FROM announcements n "
        "LEFT JOIN courses c ON c.id = n.course_id WHERE n.id = ?",
        (announcement_id,),
    ).fetchone()
    if row is None:
        raise SchoolError(f"No announcement with id {announcement_id}.", status_code=404)
    return _announcement_payload(row)


def set_announcement_seen(announcement_id: int, seen: Any) -> dict[str, Any]:
    """Mark one announcement read, or put it back to unread."""
    flag = _clean_flag(seen, "seen")
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM announcements WHERE id = ?", (announcement_id,)
        ).fetchone()
        if row is None:
            raise SchoolError(f"No announcement with id {announcement_id}.", status_code=404)
        conn.execute("UPDATE announcements SET seen = ? WHERE id = ?", (flag, announcement_id))
        return _announcement_detail(conn, announcement_id)


# ---------------------------------------------------------------------------
# Todos
# ---------------------------------------------------------------------------

def list_todos() -> list[dict[str, Any]]:
    """Open work first, each group by deadline, undated last."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT t.*, c.code AS course_code FROM school_todos t "
            "LEFT JOIN courses c ON c.id = t.course_id "
            "ORDER BY t.done ASC, (t.due_at IS NULL) ASC, t.due_at ASC, t.id ASC"
        ).fetchall()
    return [_todo_payload(row) for row in rows]


def _todo_detail(conn: sqlite3.Connection, todo_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT t.*, c.code AS course_code FROM school_todos t "
        "LEFT JOIN courses c ON c.id = t.course_id WHERE t.id = ?",
        (todo_id,),
    ).fetchone()
    if row is None:
        raise SchoolError(f"No todo with id {todo_id}.", status_code=404)
    return _todo_payload(row)


def create_todo(
    title: Any,
    course_id: int | None = None,
    assignment_id: int | None = None,
    due_at: str | None = None,
) -> dict[str, Any]:
    """Add a manual todo, optionally tied to a course and/or an assignment."""
    clean_title = _clean_title(title)
    clean_due = _clean_due_at(due_at)

    with get_db() as conn:
        if course_id is not None:
            _require_course(conn, course_id)
        if assignment_id is not None:
            assignment = _require_assignment(conn, assignment_id)
            if course_id is None:
                course_id = int(assignment["course_id"])

        cursor = conn.execute(
            "INSERT INTO school_todos (title, course_id, assignment_id, due_at, done, origin, "
            "created_at, completed_at) VALUES (?, ?, ?, ?, 0, 'manual', ?, NULL)",
            (clean_title, course_id, assignment_id, clean_due, now_iso()),
        )
        return _todo_detail(conn, int(cursor.lastrowid))


def update_todo(
    todo_id: int,
    *,
    done: bool | None = None,
    title: Any = None,
    due_at: str | None = None,
    title_given: bool = False,
    due_at_given: bool = False,
) -> dict[str, Any]:
    """Tick, rename or reschedule a todo. Completion sets/clears completed_at."""
    updates: dict[str, Any] = {}

    if title_given:
        updates["title"] = _clean_title(title)
    if due_at_given:
        updates["due_at"] = _clean_due_at(due_at)
    if done is not None:
        updates["done"] = 1 if done else 0
        updates["completed_at"] = now_iso() if done else None

    with get_db() as conn:
        row = conn.execute("SELECT id FROM school_todos WHERE id = ?", (todo_id,)).fetchone()
        if row is None:
            raise SchoolError(f"No todo with id {todo_id}.", status_code=404)
        if updates:
            assignments = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"UPDATE school_todos SET {assignments} WHERE id = ?",
                list(updates.values()) + [todo_id],
            )
        return _todo_detail(conn, todo_id)


# ---------------------------------------------------------------------------
# Events: one-off, ungraded calendar items. Cancelling keeps the row.
# ---------------------------------------------------------------------------

def _event_payload(row: sqlite3.Row) -> dict[str, Any]:
    """One school_events row, raw: UTC instants or bare dates, as stored."""
    return {
        "id": row["id"],
        "title": row["title"],
        "course_id": row["course_id"],
        "course_code": row["course_code"],
        "start_at": row["start_at"],
        "end_at": row["end_at"],
        "all_day": int(row["all_day"] or 0),
        "location": row["location"],
        "notes": row["notes"],
        "status": row["status"],
        "origin": row["origin"],
        "note_id": row["note_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "cancelled_at": row["cancelled_at"],
    }


def _clean_all_day(value: Any, field: str = "all_day") -> bool | None:
    """True, False, or None when not stated. Accepts 0/1."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise SchoolError(f"'{field}' must be true or false.", status_code=422)


def plan_event_times(start_at: Any, end_at: Any, all_day: Any) -> tuple[str, str | None, int]:
    """Validate and normalize event times. Returns (start_at, end_at, all_day).

    All day: bare dates, end_at inclusive. Timed: instants normalized to UTC Z.
    all_day defaults to start_at's shape; a mismatch is refused, not reinterpreted.
    """
    if not isinstance(start_at, str) or not start_at.strip():
        raise SchoolError("'start_at' is required.", status_code=422)
    start_text = start_at.strip()
    if len(start_text) > MAX_DUE_AT:
        raise SchoolError("'start_at' is too long to be a timestamp.", status_code=422)
    if end_at is not None and not isinstance(end_at, str):
        raise SchoolError("'end_at' must be a date, a timestamp or null.", status_code=422)
    end_text = end_at.strip() if isinstance(end_at, str) and end_at.strip() else None
    if end_text is not None and len(end_text) > MAX_DUE_AT:
        raise SchoolError("'end_at' is too long to be a timestamp.", status_code=422)

    flag = _clean_all_day(all_day)
    if flag is None:
        flag = is_bare_date(start_text)

    if flag:
        start_day = _require_date(start_text, "start_at") if is_bare_date(start_text) else None
        if start_day is None:
            raise SchoolError(
                "An all day event takes a bare YYYY-MM-DD 'start_at', not a timestamp.",
                status_code=422,
            )
        if end_text is None:
            return start_day.isoformat(), None, 1
        if not is_bare_date(end_text):
            raise SchoolError(
                "An all day event takes a bare YYYY-MM-DD 'end_at' (its last day), not a "
                "timestamp.",
                status_code=422,
            )
        end_day = _require_date(end_text, "end_at")
        if end_day < start_day:
            raise SchoolError("'end_at' cannot be before 'start_at'.", status_code=422)
        if end_day - start_day > MAX_EVENT_SPAN:
            raise SchoolError("The event runs longer than 14 days.", status_code=422)
        return start_day.isoformat(), end_day.isoformat(), 1

    start = parse_instant(start_text)
    if start is None:
        raise SchoolError(
            "A timed event takes an ISO-8601 'start_at' with a clock time, like "
            f"2026-10-12T20:00:00Z, not '{start_text}'. A bare date means all_day true.",
            status_code=422,
        )
    if end_text is None:
        return utc_z(start), None, 0
    end = parse_instant(end_text)
    if end is None:
        raise SchoolError(
            f"A timed event takes an ISO-8601 'end_at' with a clock time, not '{end_text}'.",
            status_code=422,
        )
    if end <= start:
        raise SchoolError("'end_at' must be after 'start_at'.", status_code=422)
    if end - start > MAX_EVENT_SPAN:
        raise SchoolError("The event runs longer than 14 days.", status_code=422)
    return utc_z(start), utc_z(end), 0


def plan_event_update(row: Any, block: dict[str, Any]) -> dict[str, Any]:
    """Columns an event update writes, validated against the stored row. 409 if cancelled.

    A moved start without a new end keeps the duration; a shape change drops the end.
    """
    if row["status"] != "scheduled":
        raise SchoolError(
            f"Event {row['id']} is '{row['status']}', so it cannot be changed.", status_code=409
        )

    updates: dict[str, Any] = {}
    if "title" in block:
        updates["title"] = _clean_title(block["title"], "title", MAX_EVENT_TITLE)
    if "location" in block:
        updates["location"] = _clean_location(block["location"])
    if "notes" in block:
        updates["notes"] = _clean_notes(block["notes"])
    if "course_id" in block:
        course_id = block["course_id"]
        if course_id is not None and (isinstance(course_id, bool) or not isinstance(course_id, int)):
            raise SchoolError("'course_id' must be the id of a course or null.", status_code=422)
        updates["course_id"] = course_id

    if {"start_at", "end_at", "all_day"} & set(block):
        old_all_day = bool(row["all_day"])
        stated = _clean_all_day(block["all_day"]) if "all_day" in block else None
        start = block["start_at"] if "start_at" in block else row["start_at"]
        if stated is not None:
            new_all_day = stated
        elif "start_at" in block:
            new_all_day = is_bare_date(start)
        else:
            new_all_day = old_all_day
        if "end_at" in block:
            end = block["end_at"]
        elif new_all_day != old_all_day:
            end = None
        elif "start_at" in block and row["end_at"]:
            end = _shifted_end(row["start_at"], row["end_at"], start, old_all_day)
        else:
            end = row["end_at"]
        new_start, new_end, new_flag = plan_event_times(start, end, new_all_day)
        updates["start_at"] = new_start
        updates["end_at"] = new_end
        updates["all_day"] = new_flag
    return updates


def _shifted_end(old_start: Any, old_end: Any, new_start: Any, all_day: bool) -> Any:
    """The old end moved by however far the start moved. Unchanged when unreadable."""
    if all_day:
        if not (is_bare_date(old_start) and is_bare_date(old_end) and is_bare_date(new_start)):
            return old_end
        try:
            delta = _require_date(new_start, "start_at") - _require_date(old_start, "start_at")
            return (_require_date(old_end, "end_at") + delta).isoformat()
        except SchoolError:
            return old_end
    before = parse_instant(old_start)
    after = parse_instant(new_start) if isinstance(new_start, str) else None
    end = parse_instant(old_end)
    if before is None or after is None or end is None:
        return old_end
    return utc_z(end + (after - before))


def _require_event(conn: sqlite3.Connection, event_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM school_events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        raise SchoolError(f"No event with id {event_id}.", status_code=404)
    return row


def _event_detail(conn: sqlite3.Connection, event_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT e.*, c.code AS course_code FROM school_events e "
        "LEFT JOIN courses c ON c.id = e.course_id WHERE e.id = ?",
        (event_id,),
    ).fetchone()
    if row is None:
        raise SchoolError(f"No event with id {event_id}.", status_code=404)
    return _event_payload(row)


def get_event(event_id: int) -> dict[str, Any]:
    with get_db() as conn:
        return _event_detail(conn, event_id)


def create_event(
    title: Any,
    start_at: Any,
    *,
    end_at: Any = None,
    all_day: Any = None,
    location: Any = None,
    course_id: Any = None,
    notes: Any = None,
    origin: str = "manual",
    note_id: int | None = None,
) -> dict[str, Any]:
    """Put one event on the semester's calendar. Everything is checked first."""
    clean_title = _clean_title(title, "title", MAX_EVENT_TITLE)
    clean_start, clean_end, flag = plan_event_times(start_at, end_at, all_day)
    clean_location = _clean_location(location)
    clean_notes = _clean_notes(notes)
    _require_enum(origin, SCHOOL_EVENT_ORIGINS, "event origin")

    with get_db() as conn:
        if course_id is not None:
            if isinstance(course_id, bool) or not isinstance(course_id, int):
                raise SchoolError("'course_id' must be the id of a course or null.", status_code=422)
            _require_course(conn, course_id)
        timestamp = now_iso()
        cursor = conn.execute(
            "INSERT INTO school_events (title, course_id, start_at, end_at, all_day, location, "
            "notes, status, origin, note_id, created_at, updated_at, cancelled_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'scheduled', ?, ?, ?, ?, NULL)",
            (
                clean_title,
                course_id,
                clean_start,
                clean_end,
                flag,
                clean_location,
                clean_notes,
                origin,
                note_id,
                timestamp,
                timestamp,
            ),
        )
        return _event_detail(conn, int(cursor.lastrowid))


def update_event(event_id: int, block: dict[str, Any]) -> dict[str, Any]:
    """Change any subset of an event's fields. See plan_event_update for the rules."""
    with get_db() as conn:
        row = _require_event(conn, event_id)
        updates = plan_event_update(row, block)
        if updates.get("course_id") is not None:
            _require_course(conn, updates["course_id"])
        if updates:
            updates["updated_at"] = now_iso()
            assignments = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"UPDATE school_events SET {assignments} WHERE id = ?",
                list(updates.values()) + [event_id],
            )
        return _event_detail(conn, event_id)


def cancel_event(event_id: int) -> dict[str, Any]:
    """Cancel an event (row kept). 409 if already cancelled, so cancelled_at never moves."""
    with get_db() as conn:
        row = _require_event(conn, event_id)
        if row["status"] != "scheduled":
            raise SchoolError(
                f"Event {event_id} is already '{row['status']}'.", status_code=409
            )
        timestamp = now_iso()
        conn.execute(
            "UPDATE school_events SET status = 'cancelled', cancelled_at = ?, updated_at = ? "
            "WHERE id = ?",
            (timestamp, timestamp, event_id),
        )
        return _event_detail(conn, event_id)


def list_events(
    start_raw: str | None = None,
    end_raw: str | None = None,
    include_cancelled: bool = False,
) -> list[dict[str, Any]]:
    """Raw events, soonest first, optionally in a YYYY-MM-DD window.

    The window is padded a day each side since UTC instants may fall on adjacent local days.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if start_raw is not None or end_raw is not None:
        start = _require_date(start_raw, "start")
        end = _require_date(end_raw, "end")
        if end < start:
            raise SchoolError("'end' cannot be before 'start'.", status_code=422)
        clauses.append("e.start_at >= ? AND e.start_at < ?")
        params.extend([(start - timedelta(days=1)).isoformat(), (end + timedelta(days=2)).isoformat()])
    if not include_cancelled:
        clauses.append("e.status = 'scheduled'")
    where_sql = " AND ".join(clauses) if clauses else "1=1"
    with get_db() as conn:
        rows = conn.execute(
            "SELECT e.*, c.code AS course_code FROM school_events e "
            "LEFT JOIN courses c ON c.id = e.course_id "
            f"WHERE {where_sql} ORDER BY e.start_at, e.id LIMIT 2000",
            params,
        ).fetchall()
    return [_event_payload(row) for row in rows]


# ---------------------------------------------------------------------------
# Grades
#
# Categories come from grading_scheme weights, else "(Label)" suffixes on briefs,
# else nothing (unallocated_pct 100). Nothing is invented: a bucket whose split
# is unstated reports split_known false with its whole weight remaining, and an
# ungraded dropped item keeps its weight in remaining.
# ---------------------------------------------------------------------------

# "BIO 110 homework (Lab Activity)." -> "Lab Activity", on the brief's first line.
_CATEGORY_LABEL_RE = re.compile(r"\(([^()]{1,60})\)\s*\.?\s*$")

UNMAPPED_CATEGORY = "Other work"

_ACRONYMS = {
    "sql": "SQL",
    "hw": "HW",
    "ewu": "EWU",
    "erd": "ERD",
    "ai": "AI",
    "nosql": "NoSQL",
    "iclicker": "iClicker",
}
_SMALL_WORDS = frozenset({"and", "or", "of", "the", "per", "to"})

# Fallback when the title matched no bucket; only a unique match counts.
_KIND_KEYWORDS = {
    "hw": ("assignment", "homework", "hw"),
    "quiz": ("quiz",),
    "exam": ("exam", "midterm", "final"),
    "project": ("project",),
    "reading": ("reading",),
    "other": ("participation", "engagement", "attendance"),
}


def _round2(value: float | None) -> float | None:
    """Round to two decimals, normalizing -0.0."""
    if value is None:
        return None
    return round(float(value), 2) + 0.0


def _tokens(text: Any) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", str(text or "").lower()) if token}


def _humanize(key: Any) -> str:
    words = [word for word in re.split(r"[^A-Za-z0-9]+", str(key or "")) if word]
    out: list[str] = []
    for index, word in enumerate(words):
        lower = word.lower()
        if lower in _ACRONYMS:
            out.append(_ACRONYMS[lower])
        elif index and lower in _SMALL_WORDS:
            out.append(lower)
        elif word.isupper():
            out.append(word)
        else:
            out.append(word[:1].upper() + word[1:])
    return " ".join(out) or str(key)


def _label_from_brief(brief_md: Any) -> str | None:
    """The "(Label)" category on the brief's first line, if any."""
    if not isinstance(brief_md, str) or not brief_md.strip():
        return None
    first_line = brief_md.strip().split("\n", 1)[0]
    match = _CATEGORY_LABEL_RE.search(first_line.strip())
    if match is None:
        return None
    label = " ".join(match.group(1).split())
    return label or None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _scheme_weights(scheme: Any) -> dict[str, float]:
    """Named numeric buckets of a grading scheme, in order. Nested maps (per_hw) are skipped."""
    if not isinstance(scheme, dict):
        return {}
    for key in ("weights_pct", "grading_weights_pct", "weights"):
        block = scheme.get(key)
        if isinstance(block, dict):
            return {
                name: value
                for name, raw in block.items()
                if isinstance(name, str) and (value := _number(raw)) is not None
            }
    return {}


def _scheme_points_total(scheme: Any) -> float | None:
    """The point total a course is graded out of, when it says so."""
    if not isinstance(scheme, dict):
        return None
    for key in ("points_total", "total_points"):
        total = _number(scheme.get(key))
        if total is not None and total > 0:
            return total
    return None


def _match_scheme_key(row: sqlite3.Row, buckets: dict[str, float]) -> str | None:
    """The bucket an assignment belongs to, or None when ambiguous.

    First by title tokens (most specific bucket wins, ties match nothing), then by kind.
    """
    title_tokens = _tokens(row["title"])
    best: str | None = None
    best_size = 0
    tied = False
    for key in buckets:
        key_tokens = _tokens(key)
        if not key_tokens or not key_tokens.issubset(title_tokens):
            continue
        if len(key_tokens) > best_size:
            best, best_size, tied = key, len(key_tokens), False
        elif len(key_tokens) == best_size:
            tied = True
    if best is not None and not tied:
        return best

    keywords = _KIND_KEYWORDS.get((row["kind"] or "other"), ())
    candidates = [key for key in buckets if any(word in key.lower() for word in keywords)]
    return candidates[0] if len(candidates) == 1 else None


def _group_assignments(
    course_row: sqlite3.Row,
    rows: Sequence[sqlite3.Row],
) -> list[dict[str, Any]]:
    """Group a course's work into categories; scheme order or first appearance, unmapped last."""
    scheme = (db.course_to_dict(course_row) or {}).get("grading_scheme")
    buckets = _scheme_weights(scheme)
    groups: list[dict[str, Any]] = []
    leftovers: list[sqlite3.Row] = []

    if buckets:
        held: dict[str, list[sqlite3.Row]] = {key: [] for key in buckets}
        for row in rows:
            key = _match_scheme_key(row, buckets)
            (held[key] if key is not None else leftovers).append(row)
        groups = [
            {"name": _humanize(key), "stated_weight": weight, "items": held[key]}
            for key, weight in buckets.items()
        ]
    else:
        labels: dict[str, list[sqlite3.Row]] = {}
        labelled = 0
        for row in rows:
            label = _label_from_brief(row["brief_md"])
            if label is not None:
                labelled += 1
                labels.setdefault(label, []).append(row)
        # Only trust labels if most items carry one.
        if labels and labelled * 2 >= len(rows):
            for row in rows:
                if _label_from_brief(row["brief_md"]) is None:
                    leftovers.append(row)
            groups = [
                {"name": name, "stated_weight": None, "items": items}
                for name, items in labels.items()
            ]
        else:
            by_kind: dict[str, list[sqlite3.Row]] = {}
            for row in rows:
                by_kind.setdefault(row["kind"] or "other", []).append(row)
            groups = [
                {"name": _humanize(kind), "stated_weight": None, "items": items}
                for kind, items in by_kind.items()
            ]

    if leftovers:
        groups.append({"name": UNMAPPED_CATEGORY, "stated_weight": None, "items": leftovers})
    return groups


def _item_weight(row: sqlite3.Row, points_total: float | None) -> float | None:
    """What one piece of work is worth as a percentage of the final grade."""
    weight = _number(row["weight_pct"])
    if weight is not None:
        return weight
    points = _number(row["points"])
    if points is not None and points_total:
        return points / points_total * 100.0
    return None


def _item_grade(row: sqlite3.Row) -> tuple[float, float] | None:
    """(scored, out_of) for a graded item, else None. out_of falls back to `points`."""
    scored = _number(row["grade_points"])
    if scored is None:
        return None
    maximum = _number(row["grade_max"])
    if maximum is None or maximum <= 0:
        maximum = _number(row["points"])
    if maximum is None or maximum <= 0:
        return None
    return scored, maximum


def grade_summary(course_row: sqlite3.Row, rows: Sequence[sqlite3.Row]) -> dict[str, Any]:
    """Per-category and overall secured/lost/remaining percentages of the final grade.

    current_avg_pct is the weighted average over graded work only (null if none).
    """
    scheme = (db.course_to_dict(course_row) or {}).get("grading_scheme")
    points_total = _scheme_points_total(scheme)

    categories: list[dict[str, Any]] = []
    total_secured = 0.0
    total_lost = 0.0
    total_remaining = 0.0
    known_weight = 0.0

    for group in _group_assignments(course_row, rows):
        items = group["items"]
        weights = [_item_weight(row, points_total) for row in items]
        covered = sum(weight for weight in weights if weight is not None)

        weight_pct = group["stated_weight"]
        if weight_pct is None:
            weight_pct = covered if any(w is not None for w in weights) else None

        # Known only when item weights cover the bucket's weight.
        split_known = weight_pct is not None and covered >= weight_pct - WEIGHT_TOLERANCE

        earned_points = 0.0
        earned_max = 0.0
        graded_count = 0
        graded_weight = 0.0
        secured = 0.0

        for row, weight in zip(items, weights):
            grade = _item_grade(row)
            if grade is None:
                continue
            scored, maximum = grade
            graded_count += 1
            earned_points += scored
            earned_max += maximum
            if weight is not None:
                graded_weight += weight
                secured += weight * (scored / maximum)

        lost: float | None = None
        remaining: float | None = None
        if split_known:
            lost = graded_weight - secured
            remaining = (weight_pct or 0.0) - graded_weight
            total_secured += secured
            total_lost += lost
            total_remaining += remaining
        else:
            remaining = weight_pct
            total_remaining += weight_pct or 0.0

        if weight_pct is not None:
            known_weight += weight_pct

        categories.append(
            {
                "name": group["name"],
                "weight_pct": _round2(weight_pct),
                "earned_points": _round2(earned_points),
                "earned_max": _round2(earned_max),
                "graded_count": graded_count,
                "pending_count": len(items) - graded_count,
                "secured_pct": _round2(secured) if split_known else None,
                "lost_pct": _round2(lost) if split_known else None,
                "remaining_pct": _round2(remaining),
                "split_known": bool(split_known),
            }
        )

    graded_total = total_secured + total_lost
    current_avg = (total_secured / graded_total * 100.0) if graded_total > 0 else None

    return {
        "categories": categories,
        "overall": {
            "current_avg_pct": _round2(current_avg),
            "secured_pct": _round2(total_secured),
            "lost_pct": _round2(total_lost),
            "remaining_pct": _round2(total_remaining),
            "unallocated_pct": _round2(100.0 - known_weight),
        },
    }


def _course_assignments(conn: sqlite3.Connection, course_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM assignments WHERE course_id = ? "
        "ORDER BY (due_at IS NULL) ASC, due_at ASC, id ASC",
        (course_id,),
    ).fetchall()


def get_course(course_id: int) -> dict[str, Any]:
    """One course, exactly as the list gives it, plus where its grade stands."""
    with get_db() as conn:
        _ensure_course_colors(conn)
        row = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
        if row is None:
            raise SchoolError(f"No course with id {course_id}.", status_code=404)

        meetings = [
            _meeting_payload(meeting)
            for meeting in conn.execute(
                "SELECT * FROM course_meetings WHERE course_id = ? ORDER BY start_time, id",
                (course_id,),
            ).fetchall()
        ]
        platforms = [
            _platform_payload(platform)
            for platform in conn.execute(
                "SELECT * FROM course_platforms WHERE course_id = ? ORDER BY platform, id",
                (course_id,),
            ).fetchall()
        ]
        summary = grade_summary(row, _course_assignments(conn, course_id))

    payload = _course_payload(row, meetings, platforms)
    payload["grade_summary"] = summary
    return payload


def projection(course_id: Any, target_pct: Any) -> dict[str, Any]:
    """The average remaining work needs to reach target_pct, from grade_summary's totals.

    feasible is false when that needs more than 100%, or nothing remains and the target was missed.
    """
    target = _number(target_pct)
    if target is None:
        raise SchoolError("'target_pct' must be a number.", status_code=422)
    if target < MIN_TARGET_PCT or target > MAX_TARGET_PCT:
        raise SchoolError(
            f"'target_pct' must be between {MIN_TARGET_PCT:.0f} and {MAX_TARGET_PCT:.0f}.",
            status_code=422,
        )

    with get_db() as conn:
        row = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
        if row is None:
            raise SchoolError(f"No course with id {course_id}.", status_code=422)
        summary = grade_summary(row, _course_assignments(conn, int(row["id"])))

    secured = float(summary["overall"]["secured_pct"] or 0.0)
    remaining = float(summary["overall"]["remaining_pct"] or 0.0)
    target = round(target, 2)

    if remaining <= 0:
        needed: float | None = None
        feasible = secured >= target - WEIGHT_TOLERANCE
    else:
        needed = max(0.0, (target - secured) / remaining * 100.0)
        feasible = needed <= 100.0 + WEIGHT_TOLERANCE

    return {
        "target_pct": target,
        "secured_pct": _round2(secured),
        "remaining_pct": _round2(remaining),
        "needed_avg_pct": _round2(needed),
        "feasible": bool(feasible),
    }
