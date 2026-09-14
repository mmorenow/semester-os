"""Notes: one typed sentence turned into a changeset proposal the user confirms.

A background agent (Read-only) answers with JSON ops; this module validates them
against a closed vocabulary, once on write and again on apply, and performs the
writes only after confirmation. Ambiguous notes become a "comment" op.

Op vocabulary:

    {"op": "create_assignment", "course_id": int, "title": str, "kind": str|null,
     "due_at": str|null, "ends_at": str|null, "location": str|null,
     "points": number|null, "url": str|null, "notes": str|null, "summary": str}
    {"op": "update_assignment", "assignment_id": int, "set": {...}, "summary": str}
    {"op": "create_todo", "title": str, "course_id": int|null,
     "assignment_id": int|null, "due_at": str|null, "summary": str}
    {"op": "update_todo", "todo_id": int, "set": {...}, "summary": str}
    {"op": "create_event", "title": str, "start_at": str, "end_at": str|null,
     "all_day": bool, "location": str|null, "course_id": int|null,
     "notes": str|null, "summary": str}
    {"op": "update_event", "event_id": int, "set": {...}, "summary": str}
    {"op": "cancel_event", "event_id": int, "summary": str}
    {"op": "comment", "summary": str}

`summary` is the agent's preview line; `applied_changes` is generated from the
rows actually written.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

import db
import school
import school_gcal
from db import (
    ASSIGNMENT_KINDS,
    ASSIGNMENT_STATUSES,
    encode_json,
    get_db,
    now_iso,
)

# school.py's validators, reused so changesets and hand edits accept the same values.
from school import (  # noqa: PLC2701 - deliberate reuse, see above
    SchoolError,
    _clean_all_day,
    _clean_due_at,
    _clean_grade,
    _clean_location,
    _clean_notes,
    _clean_title,
    _clean_url,
    _require_enum,
)

MAX_NOTE_TEXT = 4000

MAX_SUMMARY = 300

MAX_COMMENTARY = 4000

# More ops than this from one note means the model stopped reading it.
MAX_OPS = 25

OP_NAMES = (
    "create_assignment",
    "update_assignment",
    "create_todo",
    "update_todo",
    "create_event",
    "update_event",
    "cancel_event",
    "comment",
)

# op -> (required, optional) keys; `summary` is checked separately. Unknown keys refuse all.
OP_KEYS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "create_assignment": (
        ("course_id", "title"),
        ("kind", "due_at", "ends_at", "location", "points", "url", "notes"),
    ),
    "update_assignment": (("assignment_id", "set"), ()),
    "create_todo": (("title",), ("course_id", "assignment_id", "due_at")),
    "update_todo": (("todo_id", "set"), ()),
    "create_event": (
        ("title", "start_at"),
        ("end_at", "all_day", "location", "course_id", "notes"),
    ),
    "update_event": (("event_id", "set"), ()),
    "cancel_event": (("event_id",), ()),
    "comment": ((), ()),
}

# Narrower than the columns: weight, brief and source belong to the syllabus import.
ASSIGNMENT_SET_KEYS = (
    "title",
    "kind",
    "due_at",
    "points",
    "status",
    "notes",
    "grade_points",
    "grade_max",
    "ends_at",
    "location",
)
TODO_SET_KEYS = ("title", "due_at", "done")
EVENT_SET_KEYS = ("title", "start_at", "end_at", "all_day", "location", "course_id", "notes")


# ---------------------------------------------------------------------------
# Changeset validation (raises before any write; errors name the op position)
# ---------------------------------------------------------------------------

def _refuse(index: int | None, detail: str) -> SchoolError:
    """A 422 prefixed with the failing op's position."""
    where = f"Operation {index + 1}: " if index is not None else ""
    return SchoolError(f"{where}{detail}", status_code=422)


def _require_int(value: Any, field: str, index: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _refuse(index, f"'{field}' must be an integer id, not {value!r}.")
    return value


def _require_summary(value: Any, index: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _refuse(index, "'summary' is required and must be a sentence.")
    summary = " ".join(value.split())
    if len(summary) > MAX_SUMMARY:
        raise _refuse(index, f"'summary' is longer than {MAX_SUMMARY} characters.")
    return summary


def _known_keys(op: dict[str, Any], name: str, index: int) -> None:
    required, optional = OP_KEYS[name]
    allowed = {"op", "summary", *required, *optional}
    unknown = sorted(set(op) - allowed)
    if unknown:
        raise _refuse(
            index,
            f"'{name}' does not take {', '.join(repr(key) for key in unknown)}. "
            f"Valid keys: {', '.join(sorted(allowed))}.",
        )
    missing = sorted(key for key in required if key not in op)
    if missing:
        raise _refuse(
            index, f"'{name}' is missing {', '.join(repr(key) for key in missing)}."
        )


def _require_set_block(op: dict[str, Any], allowed: tuple[str, ...], index: int) -> dict[str, Any]:
    block = op.get("set")
    if not isinstance(block, dict):
        raise _refuse(index, "'set' must be an object naming the fields to change.")
    if not block:
        raise _refuse(index, "'set' is empty, so this operation would change nothing.")
    unknown = sorted(set(block) - set(allowed))
    if unknown:
        raise _refuse(
            index,
            f"'set' does not take {', '.join(repr(key) for key in unknown)}. "
            f"Valid keys: {', '.join(allowed)}.",
        )
    return block


def _clean_kind(value: Any, index: int) -> str | None:
    if value is None:
        return None
    try:
        return _require_enum(value, ASSIGNMENT_KINDS, "assignment kind")
    except SchoolError as exc:
        raise _refuse(index, exc.detail) from None


def _clean_status(value: Any, index: int) -> str:
    try:
        return _require_enum(value, ASSIGNMENT_STATUSES, "assignment status")
    except SchoolError as exc:
        raise _refuse(index, exc.detail) from None


def _bounded(index: int, function: Any, *args: Any, **kwargs: Any) -> Any:
    """Run one of school.py's validators and re-label its 422 with the op."""
    try:
        return function(*args, **kwargs)
    except SchoolError as exc:
        raise _refuse(index, exc.detail) from None


def _require_row(conn: sqlite3.Connection, table: str, row_id: int, label: str, index: int) -> None:
    row = conn.execute(f"SELECT id FROM {table} WHERE id = ?", (row_id,)).fetchone()
    if row is None:
        raise _refuse(index, f"No {label} with id {row_id}.")


def _validate_create_assignment(
    conn: sqlite3.Connection, op: dict[str, Any], index: int
) -> dict[str, Any]:
    course_id = _require_int(op.get("course_id"), "course_id", index)
    _require_row(conn, "courses", course_id, "course", index)
    due_at = _bounded(index, _clean_due_at, op.get("due_at"))
    return {
        "op": "create_assignment",
        "course_id": course_id,
        "title": _bounded(index, _clean_title, op.get("title"), "title", school.MAX_ASSIGNMENT_TITLE),
        "kind": _clean_kind(op.get("kind"), index),
        "due_at": due_at,
        "ends_at": _bounded(
            index,
            school.plan_assignment_block,
            None,
            None,
            due_at=due_at,
            ends_at=op.get("ends_at"),
            due_at_given=True,
            ends_at_given=True,
        ),
        "location": _bounded(index, _clean_location, op.get("location")),
        "points": _bounded(index, _clean_grade, op.get("points"), "points"),
        "url": _bounded(index, _clean_url, op.get("url")),
        "notes": _bounded(index, _clean_notes, op.get("notes")),
    }


def _validate_update_assignment(
    conn: sqlite3.Connection, op: dict[str, Any], index: int
) -> dict[str, Any]:
    assignment_id = _require_int(op.get("assignment_id"), "assignment_id", index)
    _require_row(conn, "assignments", assignment_id, "assignment", index)
    block = _require_set_block(op, ASSIGNMENT_SET_KEYS, index)
    row = conn.execute(
        "SELECT due_at, ends_at FROM assignments WHERE id = ?", (assignment_id,)
    ).fetchone()

    clean: dict[str, Any] = {}
    for key, value in block.items():
        if key == "title":
            clean[key] = _bounded(
                index, _clean_title, value, "title", school.MAX_ASSIGNMENT_TITLE
            )
        elif key == "kind":
            clean[key] = _clean_kind(value, index)
        elif key == "due_at":
            clean[key] = _bounded(index, _clean_due_at, value)
        elif key == "points":
            clean[key] = _bounded(index, _clean_grade, value, "points")
        elif key == "status":
            clean[key] = _clean_status(value, index)
        elif key == "notes":
            clean[key] = _bounded(index, _clean_notes, value)
        elif key == "location":
            clean[key] = _bounded(index, _clean_location, value)
        elif key == "ends_at":
            clean[key] = _bounded(index, school._clean_ends_at, value)
        else:  # grade_points, grade_max
            clean[key] = _bounded(index, _clean_grade, value, key)
    if "due_at" in clean or "ends_at" in clean:
        # Check the resulting block against the current row (end before start, end on a bare date).
        _bounded(
            index,
            school.plan_assignment_block,
            row["due_at"],
            row["ends_at"],
            due_at=clean.get("due_at"),
            ends_at=clean.get("ends_at"),
            due_at_given="due_at" in clean,
            ends_at_given="ends_at" in clean,
        )
    return {"op": "update_assignment", "assignment_id": assignment_id, "set": clean}


def _validate_create_todo(
    conn: sqlite3.Connection, op: dict[str, Any], index: int
) -> dict[str, Any]:
    course_id = op.get("course_id")
    if course_id is not None:
        course_id = _require_int(course_id, "course_id", index)
        _require_row(conn, "courses", course_id, "course", index)
    assignment_id = op.get("assignment_id")
    if assignment_id is not None:
        assignment_id = _require_int(assignment_id, "assignment_id", index)
        _require_row(conn, "assignments", assignment_id, "assignment", index)
    return {
        "op": "create_todo",
        "title": _bounded(index, _clean_title, op.get("title")),
        "course_id": course_id,
        "assignment_id": assignment_id,
        "due_at": _bounded(index, _clean_due_at, op.get("due_at")),
    }


def _validate_update_todo(
    conn: sqlite3.Connection, op: dict[str, Any], index: int
) -> dict[str, Any]:
    todo_id = _require_int(op.get("todo_id"), "todo_id", index)
    _require_row(conn, "school_todos", todo_id, "todo", index)
    block = _require_set_block(op, TODO_SET_KEYS, index)

    clean: dict[str, Any] = {}
    for key, value in block.items():
        if key == "title":
            clean[key] = _bounded(index, _clean_title, value)
        elif key == "due_at":
            clean[key] = _bounded(index, _clean_due_at, value)
        else:  # done
            if not isinstance(value, bool):
                raise _refuse(index, "'done' must be true or false.")
            clean[key] = value
    return {"op": "update_todo", "todo_id": todo_id, "set": clean}


def _optional_course(conn: sqlite3.Connection, value: Any, index: int) -> int | None:
    if value is None:
        return None
    course_id = _require_int(value, "course_id", index)
    _require_row(conn, "courses", course_id, "course", index)
    return course_id


def _require_scheduled_event(
    conn: sqlite3.Connection, op: dict[str, Any], index: int
) -> sqlite3.Row:
    """The event an op names; it must exist and still be scheduled."""
    event_id = _require_int(op.get("event_id"), "event_id", index)
    row = conn.execute("SELECT * FROM school_events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        raise _refuse(index, f"No event with id {event_id}.")
    if row["status"] != "scheduled":
        raise _refuse(index, f"Event {event_id} is '{row['status']}', so it cannot be changed.")
    return row


def _validate_create_event(
    conn: sqlite3.Connection, op: dict[str, Any], index: int
) -> dict[str, Any]:
    if "all_day" in op and not isinstance(op.get("all_day"), bool):
        raise _refuse(index, "'all_day' must be true or false.")
    start_at, end_at, all_day = _bounded(
        index, school.plan_event_times, op.get("start_at"), op.get("end_at"), op.get("all_day")
    )
    return {
        "op": "create_event",
        "title": _bounded(index, _clean_title, op.get("title"), "title", school.MAX_EVENT_TITLE),
        "start_at": start_at,
        "end_at": end_at,
        "all_day": bool(all_day),
        "location": _bounded(index, _clean_location, op.get("location")),
        "course_id": _optional_course(conn, op.get("course_id"), index),
        "notes": _bounded(index, _clean_notes, op.get("notes")),
    }


def _validate_update_event(
    conn: sqlite3.Connection, op: dict[str, Any], index: int
) -> dict[str, Any]:
    row = _require_scheduled_event(conn, op, index)
    block = _require_set_block(op, EVENT_SET_KEYS, index)
    if "all_day" in block and not isinstance(block["all_day"], bool):
        raise _refuse(index, "'all_day' must be true or false.")
    if "course_id" in block:
        _optional_course(conn, block["course_id"], index)
    # Plan against the current row to refuse bad times now; apply re-plans against the row then.
    _bounded(index, school.plan_event_update, row, block)
    clean: dict[str, Any] = {}
    for key, value in block.items():
        if key == "title":
            clean[key] = _bounded(index, _clean_title, value, "title", school.MAX_EVENT_TITLE)
        elif key == "location":
            clean[key] = _bounded(index, _clean_location, value)
        elif key == "notes":
            clean[key] = _bounded(index, _clean_notes, value)
        elif key == "all_day":
            clean[key] = _bounded(index, _clean_all_day, value)
        elif key == "course_id":
            clean[key] = value
        else:  # start_at, end_at: normalized by the planner at apply time
            clean[key] = value.strip() if isinstance(value, str) else value
    return {"op": "update_event", "event_id": int(row["id"]), "set": clean}


def _validate_cancel_event(
    conn: sqlite3.Connection, op: dict[str, Any], index: int
) -> dict[str, Any]:
    row = _require_scheduled_event(conn, op, index)
    return {"op": "cancel_event", "event_id": int(row["id"])}


_VALIDATORS = {
    "create_assignment": _validate_create_assignment,
    "update_assignment": _validate_update_assignment,
    "create_todo": _validate_create_todo,
    "update_todo": _validate_update_todo,
    "create_event": _validate_create_event,
    "update_event": _validate_update_event,
    "cancel_event": _validate_cancel_event,
}


def validate_ops(conn: sqlite3.Connection, raw: Any) -> list[dict[str, Any]]:
    """Validate a whole changeset and return normalized ops ready to apply.

    Raises SchoolError(422) on the first problem; never returns a partial changeset.
    """
    if not isinstance(raw, list):
        raise _refuse(None, "The changeset must be a list of operations.")
    if not raw:
        raise _refuse(None, "The changeset is empty. Use a 'comment' op to say nothing changed.")
    if len(raw) > MAX_OPS:
        raise _refuse(
            None,
            f"The changeset has {len(raw)} operations, which is more than {MAX_OPS}. "
            "One note does not mean that many changes.",
        )

    clean: list[dict[str, Any]] = []
    for index, op in enumerate(raw):
        if not isinstance(op, dict):
            raise _refuse(index, "Every operation must be an object.")
        name = op.get("op")
        if name not in OP_NAMES:
            raise _refuse(
                index, f"Unknown op {name!r}. Valid values: {', '.join(OP_NAMES)}."
            )
        _known_keys(op, name, index)
        summary = _require_summary(op.get("summary"), index)
        built = (
            {"op": "comment"} if name == "comment" else _VALIDATORS[name](conn, op, index)
        )
        built["summary"] = summary
        clean.append(built)
    return clean


# ---------------------------------------------------------------------------
# The note row
# ---------------------------------------------------------------------------

def _note_payload(row: sqlite3.Row) -> dict[str, Any]:
    """The note's API shape, built field by field so new columns don't leak."""
    note = db.school_note_to_dict(row) or {}
    proposal = note.get("proposal")
    applied = note.get("applied_changes")
    gcal = note.get("gcal")
    return {
        "id": note.get("id"),
        "text": note.get("text"),
        "status": note.get("status"),
        "action_id": note.get("action_id"),
        "proposal": proposal if isinstance(proposal, list) else None,
        "agent_md": note.get("agent_md"),
        "applied_changes": applied if isinstance(applied, list) else None,
        "gcal": gcal if isinstance(gcal, dict) else None,
        "error": note.get("error"),
        "created_at": note.get("created_at"),
        "resolved_at": note.get("resolved_at"),
        "applied_at": note.get("applied_at"),
    }


def _require_note(conn: sqlite3.Connection, note_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM school_notes WHERE id = ?", (note_id,)).fetchone()
    if row is None:
        raise SchoolError(f"No note with id {note_id}.", status_code=404)
    return row


def _detail(conn: sqlite3.Connection, note_id: int) -> dict[str, Any]:
    return _note_payload(_require_note(conn, note_id))


def clean_note_text(value: Any) -> str:
    """The typed note, stripped and length-bounded but otherwise verbatim."""
    if not isinstance(value, str) or not value.strip():
        raise SchoolError("Write the note before sending it.", status_code=422)
    text = value.strip()
    if len(text) > MAX_NOTE_TEXT:
        raise SchoolError(
            f"The note is too long. Keep it under {MAX_NOTE_TEXT} characters.", status_code=422
        )
    return text


def create_note(text: Any) -> dict[str, Any]:
    """Store a note as 'running'. The caller attaches its action before submitting it."""
    clean = clean_note_text(text)
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO school_notes (text, status, created_at) VALUES (?, 'running', ?)",
            (clean, now_iso()),
        )
        return _detail(conn, int(cursor.lastrowid))


def attach_action(note_id: int, action_id: int) -> dict[str, Any]:
    """Record which run is reading this note."""
    with get_db() as conn:
        _require_note(conn, note_id)
        conn.execute(
            "UPDATE school_notes SET action_id = ? WHERE id = ?", (action_id, note_id)
        )
        return _detail(conn, note_id)


def list_notes(limit: int = 200) -> list[dict[str, Any]]:
    """Every note, newest first. Reconciles abandoned runs on the way through."""
    reconcile()
    bounded = max(1, min(int(limit), 500))
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM school_notes ORDER BY id DESC LIMIT ?", (bounded,)
        ).fetchall()
    return [_note_payload(row) for row in rows]


def get_note(note_id: int) -> dict[str, Any]:
    """One note, whole. 404 when there is no such row."""
    reconcile()
    with get_db() as conn:
        return _detail(conn, note_id)


def record_proposal(note_id: int, ops: list[dict[str, Any]], commentary: Any) -> dict[str, Any]:
    """Store an already-validated changeset as the note's proposal. Writes only school_notes."""
    text = commentary if isinstance(commentary, str) else ""
    text = text.strip()[:MAX_COMMENTARY] or None
    with get_db() as conn:
        _require_note(conn, note_id)
        conn.execute(
            "UPDATE school_notes SET status = 'proposed', proposal = ?, agent_md = ?, "
            "error = NULL, resolved_at = ? WHERE id = ?",
            (encode_json(ops), text, now_iso(), note_id),
        )
        return _detail(conn, note_id)


def record_failure(note_id: int, error: Any) -> dict[str, Any]:
    """Mark the note failed with the reason. The row is kept."""
    detail = str(error or "The run produced no usable changeset.").strip()[:2000]
    with get_db() as conn:
        _require_note(conn, note_id)
        conn.execute(
            "UPDATE school_notes SET status = 'failed', error = ?, resolved_at = ? WHERE id = ?",
            (detail, now_iso(), note_id),
        )
        return _detail(conn, note_id)


def discard_note(note_id: int) -> dict[str, Any]:
    """Mark a 'proposed' note discarded, keeping the proposal."""
    with get_db() as conn:
        row = _require_note(conn, note_id)
        if row["status"] != "proposed":
            raise SchoolError(
                f"This note is '{row['status']}', not 'proposed', so there is nothing to "
                "discard.",
                status_code=409,
            )
        conn.execute(
            "UPDATE school_notes SET status = 'discarded', resolved_at = COALESCE(resolved_at, ?) "
            "WHERE id = ?",
            (now_iso(), note_id),
        )
        return _detail(conn, note_id)


# For runs that ended (missing CLI, timeout, cancel, restart) without reaching write-back.
RECONCILE_REASON = (
    "The run that was reading this note ended as '{status}' without returning a "
    "changeset, so nothing was proposed and nothing was written. Send the note "
    "again to spend another run."
)


def reconcile() -> int:
    """Fail 'running' notes whose action failed or was cancelled.

    Called from reads and startup, since these are the cases where write-back never ran.
    """
    with get_db() as conn:
        rows = conn.execute(
            "SELECT n.id AS note_id, a.status AS action_status, a.error AS action_error "
            "FROM school_notes n JOIN actions a ON a.id = n.action_id "
            "WHERE n.status = 'running' AND a.status IN ('failed', 'cancelled')"
        ).fetchall()
        for row in rows:
            detail = (row["action_error"] or "").strip() or RECONCILE_REASON.format(
                status=row["action_status"]
            )
            conn.execute(
                "UPDATE school_notes SET status = 'failed', error = ?, resolved_at = ? "
                "WHERE id = ? AND status = 'running'",
                (detail[:2000], now_iso(), int(row["note_id"])),
            )
    return len(rows)


# ---------------------------------------------------------------------------
# Applying a proposal (only on explicit confirmation)
# ---------------------------------------------------------------------------

# applied_changes sentences use campus wall time and DESIGN.md's compact 12-hour clock.

def _clock(moment: datetime) -> str:
    """`9:30a`, `12:00p`, `11:59p`. No leading zero and no space."""
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02d}{'p' if moment.hour >= 12 else 'a'}"


def _day(value: date) -> str:
    """`Wed Sep 16`, with the year only when it is not this year."""
    text = f"{value.strftime('%a %b')} {value.day}"
    if value.year != datetime.now(school.LOCAL_TZ).year:
        text += f", {value.year}"
    return text


def _human_stamp(value: Any) -> str:
    """`Wed Sep 16, 6:00p`; a bare date reads as the day, unparseable values as stored."""
    if not value:
        return ""
    if school.is_bare_date(value):
        return _day(date.fromisoformat(str(value).strip()))
    moment = school.parse_instant(value)
    if moment is None:
        return str(value)
    local = moment.astimezone(school.LOCAL_TZ)
    return f"{_day(local.date())}, {_clock(local)}"


def _human_span(start: Any, end: Any) -> str:
    """`Wed Sep 16, 6:00-7:30p` on one day (shared meridiem dropped), else "X to Y"."""
    if not end:
        return _human_stamp(start)
    first, last = school.parse_instant(start), school.parse_instant(end)
    if first is not None and last is not None:
        first, last = first.astimezone(school.LOCAL_TZ), last.astimezone(school.LOCAL_TZ)
        if first.date() == last.date():
            opening, closing = _clock(first), _clock(last)
            if opening[-1] == closing[-1]:
                opening = opening[:-1]
            return f"{_day(first.date())}, {opening}-{closing}"
    return f"{_human_stamp(start)} to {_human_stamp(end)}"


def _due_phrase(due_at: Any) -> str:
    return f", due {_human_stamp(due_at)}" if due_at else ", with no deadline"


def _when_phrase(row: dict[str, Any]) -> str:
    """An event row's time as a phrase."""
    if row.get("all_day"):
        if row.get("end_at") and row["end_at"] != row["start_at"]:
            return f"all day {_human_stamp(row['start_at'])} to {_human_stamp(row['end_at'])}"
        return f"all day {_human_stamp(row['start_at'])}"
    if row.get("end_at"):
        return _human_span(row["start_at"], row["end_at"])
    return f"at {_human_stamp(row['start_at'])}"


def _where_phrase(row: dict[str, Any]) -> str:
    return f" in {row['location']}" if row.get("location") else ""


# (kind, id) of a row an op touched that may need a calendar push. Updated assignments
# always count, since an update can remove the date and the event must go.
Touched = tuple[str, int]


def _apply_op(op: dict[str, Any], note_id: int) -> tuple[str, Touched | None]:
    """Perform one validated op. Returns (sentence built from the written row, touched row)."""
    name = op["op"]

    if name == "comment":
        return f"Nothing to write. {op['summary']}", None

    if name == "create_assignment":
        row = school.create_assignment(
            op["course_id"],
            op["title"],
            kind=op.get("kind"),
            due_at=op.get("due_at"),
            points=op.get("points"),
            url=op.get("url"),
            notes=op.get("notes"),
            ends_at=op.get("ends_at"),
            location=op.get("location"),
        )
        when = (
            f", {_human_span(row['due_at'], row['ends_at'])}"
            if row.get("due_at") and row.get("ends_at")
            else _due_phrase(row["due_at"])
        )
        return (
            f"Created assignment {row['id']} \"{row['title']}\" in "
            f"{row['course_code']}{when}{_where_phrase(row)}.",
            ("assignment", int(row["id"])) if row.get("due_at") else None,
        )

    if name == "update_assignment":
        block = op["set"]
        row = school.update_assignment(
            op["assignment_id"],
            title=block.get("title"),
            kind=block.get("kind"),
            due_at=block.get("due_at"),
            points=block.get("points"),
            status=block.get("status"),
            notes=block.get("notes"),
            grade_points=block.get("grade_points"),
            grade_max=block.get("grade_max"),
            ends_at=block.get("ends_at"),
            location=block.get("location"),
            title_given="title" in block,
            kind_given="kind" in block,
            due_at_given="due_at" in block,
            points_given="points" in block,
            status_given="status" in block,
            notes_given="notes" in block,
            grade_points_given="grade_points" in block,
            grade_max_given="grade_max" in block,
            ends_at_given="ends_at" in block,
            location_given="location" in block,
        )
        return (
            f"Updated assignment {row['id']} \"{row['title']}\" in {row['course_code']}: "
            f"{_written_values(row, block)}.",
            ("assignment", int(row["id"])),
        )

    if name == "create_todo":
        row = school.create_todo(
            op["title"],
            course_id=op.get("course_id"),
            assignment_id=op.get("assignment_id"),
            due_at=op.get("due_at"),
        )
        return f"Created todo {row['id']} \"{row['title']}\"{_due_phrase(row['due_at'])}.", None

    if name == "update_todo":
        block = op["set"]
        row = school.update_todo(
            op["todo_id"],
            done=block.get("done"),
            title=block.get("title"),
            due_at=block.get("due_at"),
            title_given="title" in block,
            due_at_given="due_at" in block,
        )
        return (
            f"Updated todo {row['id']} \"{row['title']}\": {_written_values(row, block)}.",
            None,
        )

    if name == "create_event":
        row = school.create_event(
            op["title"],
            op["start_at"],
            end_at=op.get("end_at"),
            all_day=op.get("all_day"),
            location=op.get("location"),
            course_id=op.get("course_id"),
            notes=op.get("notes"),
            origin="note",
            note_id=note_id,
        )
        course = f" for {row['course_code']}" if row.get("course_code") else ""
        return (
            f"Created event {row['id']} \"{row['title']}\"{course}, "
            f"{_when_phrase(row)}{_where_phrase(row)}.",
            ("event", int(row["id"])),
        )

    if name == "update_event":
        block = op["set"]
        row = school.update_event(op["event_id"], block)
        return (
            f"Updated event {row['id']} \"{row['title']}\": {_written_values(row, block)}.",
            ("event", int(row["id"])),
        )

    # cancel_event
    row = school.cancel_event(op["event_id"])
    return (
        f"Cancelled event {row['id']} \"{row['title']}\" ({_when_phrase(row)}). The row is kept.",
        ("event", int(row["id"])),
    )


WRITTEN_ORDER = (
    "title", "kind", "course_id", "due_at", "ends_at", "start_at", "end_at", "all_day",
    "location", "points", "status", "grade_points", "grade_max", "done", "notes",
)

WRITTEN_NOTES_PREVIEW = 80


def _written_values(row: dict[str, Any], block: dict[str, Any]) -> str:
    """Human-readable current values of the fields the op touched, read from the written row.

    A moved start or deadline also reports its end, which may have moved with it.
    """
    keys = set(block)
    if "start_at" in keys and "end_at" in row:
        keys.add("end_at")
    if "due_at" in keys and row.get("ends_at"):
        keys.add("ends_at")

    parts: list[str] = []
    def rank(name: str) -> tuple[int, str]:
        return (WRITTEN_ORDER.index(name) if name in WRITTEN_ORDER else len(WRITTEN_ORDER), name)

    for key in sorted(keys, key=rank):
        value = row.get(key)
        if key == "ends_at" and "due_at" in keys and row.get("due_at") and value:
            continue  # folded into the deadline's span below
        if key == "end_at" and "start_at" in keys and row.get("start_at") and value and not row.get("all_day"):
            continue  # folded into the start's span below
        parts.append(_written_value(row, key, value, keys))
    return ", ".join(parts)


def _written_value(row: dict[str, Any], key: str, value: Any, keys: set[str]) -> str:
    """One field of `_written_values`, as a short phrase."""
    if key == "due_at":
        if not value:
            return "no deadline"
        if "ends_at" in keys and row.get("ends_at"):
            return _human_span(value, row["ends_at"])
        return f"due {_human_stamp(value)}"
    if key == "start_at":
        if "end_at" in keys and row.get("end_at") and not row.get("all_day"):
            return _human_span(value, row["end_at"])
        return f"starts {_human_stamp(value)}"
    if key in ("ends_at", "end_at"):
        return f"ends {_human_stamp(value)}" if value else "no end time"
    if key in ("done", "all_day"):
        label = "done" if key == "done" else "all day"
        return label if value else f"not {label}"
    if key == "course_id":
        return f"course {row['course_code']}" if row.get("course_code") else "no course"
    if key == "location":
        return f"in {value}" if value else "no location"
    if key == "points":
        return f"worth {value} points" if value is not None else "no points"
    if key == "grade_points":
        return f"scored {value}" if value is not None else "no score"
    if key == "grade_max":
        return f"out of {value}" if value is not None else "no maximum score"
    if key == "status":
        return f"status {str(value).replace('_', ' ')}"
    if key == "kind":
        return f"kind {value}" if value else "no kind"
    if key == "notes":
        if not value:
            return "notes cleared"
        text = " ".join(str(value).split())
        if len(text) > WRITTEN_NOTES_PREVIEW:
            text = text[: WRITTEN_NOTES_PREVIEW - 3].rstrip() + "..."
        return f'notes "{text}"'
    if key == "title":
        return f'title "{value}"'
    return f"{key.replace('_', ' ')} {'none' if value is None else value}"


NOT_CONNECTED_DETAIL = (
    "Google Calendar is not connected, so these changes were written to the database only. "
    "They will be uploaded to your Google calendar automatically on the next sync after "
    "you reconnect."
)


def _push_calendar(touched: list[Touched]) -> dict[str, Any] | None:
    """Push every touched assignment/event to Google primary and report the outcome.

    Never raises: rows are already written and the next full sync catches up.
    Returns None when nothing calendar-relevant was touched.
    """
    assignment_ids = sorted({row_id for kind, row_id in touched if kind == "assignment"})
    event_ids = sorted({row_id for kind, row_id in touched if kind == "event"})
    if not assignment_ids and not event_ids:
        return None
    try:
        if not school_gcal.status().get("connected"):
            return {"attempted": False, "ok": None, "detail": NOT_CONNECTED_DETAIL}
    except Exception as exc:  # noqa: BLE001 - a status check may not fail an apply
        return {
            "attempted": False,
            "ok": None,
            "detail": f"Google Calendar status: {exc}. The next sync will upload these changes.",
        }

    try:
        if not school_gcal.armed():
            return {
                "attempted": False,
                "ok": None,
                "detail": (
                    "Written to the database. Nothing has been synced to your Google calendar "
                    "yet; the first sync from the School section will upload these changes."
                ),
            }
    except Exception as exc:  # noqa: BLE001 - a state read may not fail an apply
        return {"attempted": False, "ok": None, "detail": f"Google Calendar state: {exc}"}

    try:
        result = school_gcal.push_changes(assignment_ids=assignment_ids, event_ids=event_ids)
    except Exception as exc:  # noqa: BLE001 - nor may the write itself
        detail = getattr(exc, "detail", None) or str(exc)
        return {"attempted": True, "ok": False, "detail": str(detail)[:1000]}

    totals = {"created": 0, "updated": 0, "unchanged": 0, "removed": 0, "deferred": 0}
    for part in (result or {}).values():
        if isinstance(part, dict):
            for key in totals:
                totals[key] += int(part.get(key) or 0)
    detail = (
        f"{totals['created']} created, {totals['updated']} updated, "
        f"{totals['removed']} removed, {totals['unchanged']} already current on your Google "
        "calendar."
    )
    if totals["deferred"]:
        detail += f" {totals['deferred']} left for the next sync."
    return {"attempted": True, "ok": True, "detail": detail}


def apply_note(note_id: int) -> dict[str, Any]:
    """Re-validate against current rows, apply ops via school.py, then push to Google.

    A 422 on re-validation writes nothing and leaves the note 'proposed'.

    A mid-apply failure is not rolled back: the note becomes 'failed' with the
    sentences that landed, and the caller gets a 500.
    """
    with get_db() as conn:
        row = _require_note(conn, note_id)
        if row["status"] != "proposed":
            raise SchoolError(
                f"This note is '{row['status']}', not 'proposed', so there is nothing to "
                "apply.",
                status_code=409,
            )
        raw = db.school_note_to_dict(row).get("proposal")
        ops = validate_ops(conn, raw)

    applied: list[str] = []
    touched: list[Touched] = []
    try:
        for op in ops:
            sentence, target = _apply_op(op, note_id)
            applied.append(sentence)
            if target is not None:
                touched.append(target)
    except Exception as exc:  # noqa: BLE001 - recorded on the note, then re-raised
        detail = getattr(exc, "detail", None) or str(exc)
        message = (
            f"Operation {len(applied) + 1} failed after {len(applied)} of {len(ops)} had "
            f"already been written: {detail}"
        )
        with get_db() as conn:
            conn.execute(
                "UPDATE school_notes SET status = 'failed', applied_changes = ?, error = ?, "
                "applied_at = ? WHERE id = ?",
                (encode_json(applied), message[:2000], now_iso(), note_id),
            )
        raise SchoolError(message, status_code=500) from exc

    gcal = _push_calendar(touched)

    with get_db() as conn:
        conn.execute(
            "UPDATE school_notes SET status = 'applied', applied_changes = ?, gcal = ?, "
            "error = NULL, applied_at = ? WHERE id = ?",
            (encode_json(applied), encode_json(gcal), now_iso(), note_id),
        )
        return _detail(conn, note_id)


# ---------------------------------------------------------------------------
# The prompt's view of the semester (runner.py owns the wording)
# ---------------------------------------------------------------------------

MAX_PROMPT_COURSES = 40
MAX_PROMPT_ASSIGNMENTS = 120
MAX_PROMPT_TODOS = 80
MAX_PROMPT_EVENTS = 80

PROMPT_EVENTS_BACK_DAYS = 7

# Finished work is left out so the agent doesn't match notes against it.
OPEN_ASSIGNMENT_STATUSES = ("pending", "in_progress", "submitted")


def _line(*parts: Any) -> str:
    return " | ".join("" if part is None else str(part) for part in parts)


def _local_stamp(value: Any) -> str:
    """A stored timestamp as campus wall time."""
    if not value:
        return ""
    if school.is_bare_date(value):
        return str(value)
    moment = school.parse_instant(value)
    if moment is None:
        return str(value)
    return moment.astimezone(school.LOCAL_TZ).strftime("%Y-%m-%d %H:%M")


def _prompt_events() -> list[dict[str, Any]]:
    """Scheduled events from a week ago onward, soonest first, bounded."""
    today = datetime.now(school.LOCAL_TZ).date()
    # One day of margin: start_at is UTC, so a late local event is stored under the next date.
    low = (today - timedelta(days=PROMPT_EVENTS_BACK_DAYS + 1)).isoformat()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT e.*, c.code AS course_code FROM school_events e "
            "LEFT JOIN courses c ON c.id = e.course_id "
            "WHERE e.status = 'scheduled' AND e.start_at >= ? "
            "ORDER BY e.start_at, e.id LIMIT ?",
            (low, MAX_PROMPT_EVENTS),
        ).fetchall()
    return [dict(row) for row in rows]


def state_context() -> str:
    """The ids the agent may reference: courses, open assignments, open todos, upcoming events.

    Assignment times are as stored; event times are campus wall time.
    """
    courses = school.list_courses()[:MAX_PROMPT_COURSES]
    assignments = [
        row
        for row in school.list_assignments()
        if row.get("status") in OPEN_ASSIGNMENT_STATUSES
    ][:MAX_PROMPT_ASSIGNMENTS]
    todos = [row for row in school.list_todos() if not row.get("done")][:MAX_PROMPT_TODOS]

    course_lines = [
        _line(course["id"], course["code"], course["title"]) for course in courses
    ] or ["(no courses)"]
    assignment_lines = [
        _line(
            row["id"],
            row["course_code"],
            row["title"],
            row["kind"] or "no kind",
            row["due_at"] or "no due date",
            row["status"],
            row.get("ends_at") or "-",
            row.get("location") or "-",
        )
        for row in assignments
    ] or ["(no open assignments)"]
    todo_lines = [
        _line(row["id"], row["title"], row["due_at"] or "no due date") for row in todos
    ] or ["(no open todos)"]
    event_lines = [
        _line(
            row["id"],
            row["title"],
            row["course_code"] or "-",
            ("all day " if row["all_day"] else "") + _local_stamp(row["start_at"]),
            _local_stamp(row["end_at"]) or "-",
            row["location"] or "-",
        )
        for row in _prompt_events()
    ] or ["(no scheduled events)"]

    return (
        "COURSES (id | code | title)\n"
        + "\n".join(course_lines)
        + "\n\nOPEN ASSIGNMENTS (id | course | title | kind | due_at | status | ends_at | "
        "location)\n"
        + "\n".join(assignment_lines)
        + "\n\nOPEN TODOS (id | title | due_at)\n"
        + "\n".join(todo_lines)
        + "\n\nSCHEDULED EVENTS from a week ago on (id | title | course | start, campus time | "
        "end, campus time | location)\n"
        + "\n".join(event_lines)
    )


def note_for_action(payload: Any) -> int | None:
    """The note id an action's payload names, or None when it names none."""
    if not isinstance(payload, dict):
        return None
    value = payload.get("note_id")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def note_text(note_id: int) -> str | None:
    """The sentence a note holds, for the prompt builder. None when it is gone."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT text FROM school_notes WHERE id = ?", (note_id,)
        ).fetchone()
    return row["text"] if row else None


def parse_changeset(text: str | None) -> tuple[Any, str, str | None]:
    """Extract (ops, commentary, error) from an agent answer.

    Fenced JSON first, then a bare object with "ops". No match is an error, not an empty changeset.
    """
    candidates: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    body = text or ""

    fence = "```"
    index = 0
    while True:
        start = body.find(fence, index)
        if start == -1:
            break
        newline = body.find("\n", start)
        if newline == -1:
            break
        end = body.find(fence, newline)
        if end == -1:
            break
        block = body[newline + 1:end].strip()
        if block.startswith("{"):
            try:
                value = decoder.decode(block)
            except ValueError:
                value = None
            if isinstance(value, dict):
                candidates.append(value)
        index = end + len(fence)

    if not candidates:
        position = 0
        while True:
            start = body.find("{", position)
            if start == -1:
                break
            try:
                value, offset = decoder.raw_decode(body[start:])
            except ValueError:
                position = start + 1
                continue
            if isinstance(value, dict) and "ops" in value:
                candidates.append(value)
            position = start + offset

    for value in reversed(candidates):
        if "ops" in value:
            commentary = value.get("commentary")
            return value["ops"], (commentary if isinstance(commentary, str) else ""), None
    return None, "", "the answer carried no fenced json block with an 'ops' list"


def write_back(note_id: int, answer: str | None) -> dict[str, Any]:
    """Parse and validate a finished run into a proposal or a failure. Writes only school_notes."""
    ops_raw, commentary, problem = parse_changeset(answer)
    if problem is not None:
        return record_failure(note_id, f"The agent replied, but {problem}.")
    try:
        with get_db() as conn:
            ops = validate_ops(conn, ops_raw)
    except SchoolError as exc:
        return record_failure(
            note_id,
            f"The agent replied with a changeset this server refuses: {exc.detail} "
            "Nothing was written.",
        )
    return record_proposal(note_id, ops, commentary)
