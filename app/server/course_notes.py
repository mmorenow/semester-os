"""Turn course note JSON (a parsed syllabus) into courses, meetings, platforms and assignments.

Writes are additive and idempotent on natural keys. import_values records what a
load wrote, so a field edited by hand afterwards is kept on the next load.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from typing import Any

import db

# Row counts compared before and after load_notes(); a load must never write these.
UNTOUCHED_TABLES = ("school_notes", "actions", "school_events", "external_events")

MAX_COURSE_CODE = 40
MAX_COURSE_TITLE = 200
MAX_INSTRUCTORS = 12
MAX_MEETINGS = 12
# Same ceiling as school.py, so a syllabus cannot write a room the PATCH refuses.
MAX_LOCATION = 300
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# What a load last wrote per (entity, id, field). `value` is JSON so null and "" differ.
IMPORT_VALUES_SQL = """
CREATE TABLE IF NOT EXISTS import_values (
    entity     TEXT NOT NULL,
    entity_id  INTEGER NOT NULL,
    field      TEXT NOT NULL,
    value      TEXT,
    written_at TEXT,
    PRIMARY KEY (entity, entity_id, field)
);
"""

COURSE_FIELDS = ("title", "credit_hours", "instructors", "term")
MEETING_FIELDS = ("duration_min", "location", "start_date", "end_date", "crn")
ASSIGNMENT_FIELDS = ("title", "kind", "due_at", "points", "weight_pct", "brief_md", "ends_at", "location")

ASSIGNMENT_FIELD_LABELS = {"due_at": "due date", "ends_at": "end time", "weight_pct": "weight"}

VERDICTS = ("created", "updated", "unchanged", "kept")


class LoaderError(Exception):
    """A note the loader refuses to guess at."""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the import record if it is missing. Cheap; safe on every call."""
    conn.executescript(IMPORT_VALUES_SQL)


# ---------------------------------------------------------------------------
# Vocabulary mapping: free-text categories to the closed enum, else 'other'
# ---------------------------------------------------------------------------

CATEGORY_KINDS: dict[str, str] = {
    "project": "project",
    "exam": "exam",
    "quiz": "quiz",
    "homework": "hw",
    "hw": "hw",
    "assignment": "hw",
    "lab activity": "hw",
    "case study": "hw",
    "strategic thinking": "hw",
    "reflection": "hw",
    "ewu": "hw",
    "engagement weekly update": "hw",
    "reading": "reading",
    "participation": "other",
}

# Read in order; the first pattern that matches the title wins.
TITLE_KINDS: tuple[tuple[str, str], ...] = (
    (r"\bfinal exam\b|\bmidterm\b|\bexam\b", "exam"),
    (r"\bquiz(zes)?\b", "quiz"),
    (r"\bproject\b|\bsprint\b|\bcharter\b|\bbacklog\b|\bpitch\b", "project"),
    (r"\bhomework\b|\bhw\s*\d*\b|\blab activity\b|\bcase study\b|\breflection\b", "hw"),
    (r"\breading\b", "reading"),
)

KIND_LABELS = {
    "hw": "homework",
    "quiz": "quiz",
    "exam": "exam",
    "project": "project deliverable",
    "reading": "reading",
    "other": "course item",
}

PLATFORM_LABELS = {
    "brightspace": "Brightspace",
    "gradescope": "Gradescope",
    "ed": "Ed",
    "website": "Course website",
    "other": "Other",
}

# Words in a platform's notes that mark it as the submit target. Exams have none.
KIND_PLATFORM_HINTS: dict[str, tuple[str, ...]] = {
    "hw": ("homework", "hw", "submission", "submit", "assignment"),
    "quiz": ("quiz",),
    "project": ("project",),
    "reading": ("reading",),
    "other": ("participation", "iclicker", "attendance"),
    "exam": (),
}

KIND_POLICY_WORDS: dict[str, tuple[str, ...]] = {
    "hw": ("homework", "hw", "assignment"),
    "quiz": ("quiz",),
    "exam": ("exam",),
    "project": ("project",),
    "reading": ("reading",),
    "other": ("participation", "iclicker", "attendance"),
}

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Only fires when "due" introduces the time, so "8:00-9:30 PM, SU 114" is ignored.
DUE_TIME_RE = re.compile(r"due\s*@?\s*(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?", re.IGNORECASE)
END_OF_DAY_RE = re.compile(r"\bend of (the )?day\b|\beod\b", re.IGNORECASE)

MAX_NOTE_CHARS = 240
MAX_POLICY_CHARS = 200


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def slugify(text: str, limit: int = 120) -> str:
    """Stable source_id from a title; the unique index matches on it, so a retitle makes a new row."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit] or "item"


def _norm(value: Any) -> Any:
    """Normalize a value for comparison against what SQLite gave back."""
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return value


def _same(left: Any, right: Any) -> bool:
    left, right = _norm(left), _norm(right)
    if isinstance(left, float) and isinstance(right, float):
        return abs(left - right) < 1e-9
    return left == right


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _platform_label(entry: dict[str, Any]) -> str:
    name = _text(entry.get("name"))
    if name:
        return name
    return PLATFORM_LABELS.get(str(entry.get("platform", "")).lower(), "Other")


# ---------------------------------------------------------------------------
# Reading a note
# ---------------------------------------------------------------------------

def assignment_kind(item: dict[str, Any]) -> str:
    """The closed enum value for one note item: stated, categorized or guessed."""
    stated = str(item.get("kind") or "").strip().lower()
    if stated in db.ASSIGNMENT_KINDS:
        return stated

    category = str(item.get("category") or "").strip().lower()
    if category in CATEGORY_KINDS:
        return CATEGORY_KINDS[category]

    title = str(item.get("title") or "").lower()
    for pattern, kind in TITLE_KINDS:
        if re.search(pattern, title):
            return kind
    return "other"


def assignment_due_at(item: dict[str, Any]) -> str | None:
    """ISO timestamp or bare date. A date gains a time only from due_time, "Due @ 3pm" or end-of-day."""
    raw = item.get("due_at") if item.get("due_at") is not None else item.get("due_date")
    text = _text(raw)
    if text is None:
        return None

    if "T" in text or ":" in text:
        if db.parse_iso(text) is None:
            raise LoaderError(f"'{text}' is not a date or an ISO-8601 timestamp.")
        return text

    try:
        day = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise LoaderError(f"'{text}' is not a YYYY-MM-DD date.") from None

    explicit = _text(item.get("due_time"))
    if explicit:
        return f"{day.isoformat()}T{explicit}"

    notes = _text(item.get("notes")) or ""
    match = DUE_TIME_RE.search(notes)
    if match:
        hour = int(match.group(1)) % 12
        minute = int(match.group(2) or 0)
        if match.group(3).lower() == "p":
            hour += 12
        return f"{day.isoformat()}T{hour:02d}:{minute:02d}"
    if END_OF_DAY_RE.search(notes):
        return f"{day.isoformat()}T23:59"
    return day.isoformat()


def assignment_block(item: dict[str, Any], due_at: str | None) -> tuple[str | None, str | None]:
    """(ends_at, location) for one item. end_time is same-day campus wall time after due_time.

    An end not after the start is refused rather than read as past midnight.
    """
    title = _text(item.get("title")) or "An assignment"
    location = _text(item.get("location"))
    if location is not None and len(location) > MAX_LOCATION:
        raise LoaderError(f"{title}: the location is longer than {MAX_LOCATION} characters.")

    end_time = _text(item.get("end_time"))
    if end_time is None:
        return None, location
    if not _HHMM_RE.match(end_time):
        raise LoaderError(f"{title}: end_time must be 24 hour HH:MM.")
    match = re.match(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})$", due_at or "")
    if match is None:
        raise LoaderError(
            f"{title}: end_time needs a due_date and a due_time, because the block starts at the "
            "due time."
        )
    if end_time <= match.group(2):
        raise LoaderError(f"{title}: end_time {end_time} is not after the due time {match.group(2)}.")
    return f"{match.group(1)}T{end_time}", location


def assignment_weight(item: dict[str, Any], total_points: float | None) -> float | None:
    """Percent of the final grade: stated, or points / total_points. Otherwise None."""
    if "weight_pct" in item and item["weight_pct"] is not None:
        return float(item["weight_pct"])
    points = item.get("points")
    if points is None or not total_points:
        return None
    return round(float(points) / float(total_points) * 100.0, 4)


def submit_target(item: dict[str, Any], kind: str, platforms: list[dict[str, Any]]) -> str | None:
    """Where the work is submitted: explicit `submit`, best hint-matching platforms, or the only platform."""
    explicit = _text(item.get("submit"))
    if explicit:
        return explicit
    hints = KIND_PLATFORM_HINTS.get(kind, ())
    if not hints:
        return None

    scored: list[tuple[int, dict[str, Any]]] = []
    for entry in platforms:
        notes = (_text(entry.get("notes")) or "").lower()
        score = sum(1 for hint in hints if hint in notes)
        if score:
            scored.append((score, entry))

    if scored:
        best = max(score for score, _ in scored)
        winners = [entry for score, entry in scored if score == best]
        if len(winners) <= 3:
            return " or ".join(_platform_label(entry) for entry in winners)
        return None

    if len(platforms) == 1 and kind != "other":
        return _platform_label(platforms[0])
    return None


def _sentence_about(text: str, words: tuple[str, ...]) -> str | None:
    """The policy sentence naming this kind of work; policies often differ per kind."""
    if not words:
        return None
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        lowered = sentence.lower()
        if any(word in lowered for word in words):
            return _clip(sentence, MAX_POLICY_CHARS)
    return None


KIND_LATE_WORDS: dict[str, tuple[str, ...]] = {
    "hw": ("hw", "homework", "assignment"),
    "project": ("document", "project", "deliverable", "report"),
}


def policy_line(note: dict[str, Any], kind: str, item: dict[str, Any]) -> str | None:
    """The one policy sentence this item cannot afford to have forgotten."""
    clauses: list[str] = []

    ai_policy = _text(note.get("ai_policy"))
    if ai_policy:
        sentence = _sentence_about(ai_policy, KIND_POLICY_WORDS.get(kind, ()))
        if sentence:
            clauses.append("AI: " + sentence)

    if item.get("due_at", item.get("due_date")) is not None:
        late = _text(note.get("late_policy"))
        if late:
            sentence = _sentence_about(late, KIND_LATE_WORDS.get(kind, ()))
            if sentence:
                clauses.append("Late: " + sentence)

    if not clauses:
        return None
    return _clip(" · ".join(clauses[:2]), 2 * MAX_POLICY_CHARS)


def format_due(due_at: str | None) -> str:
    if due_at is None:
        return "Due: no fixed date — ongoing."
    day_text, _, time_text = due_at.partition("T")
    try:
        day = datetime.strptime(day_text, "%Y-%m-%d").date()
        stamp = f"{WEEKDAYS[day.weekday()]} {day.isoformat()}"
    except ValueError:
        stamp = day_text
    if not time_text:
        return f"Due: {stamp}."
    hhmm = time_text[:5]
    try:
        hour, minute = (int(part) for part in hhmm.split(":"))
        meridiem = "p" if hour >= 12 else "a"
        hour12 = hour % 12 or 12
        return f"Due: {stamp}, {hour12}:{minute:02d}{meridiem}."
    except ValueError:
        return f"Due: {stamp}, {hhmm}."


def build_brief(
    note: dict[str, Any],
    item: dict[str, Any],
    *,
    course_code: str,
    kind: str,
    due_at: str | None,
    points: float | None,
    weight_pct: float | None,
    platforms: list[dict[str, Any]],
) -> str:
    """Three to six lines from the note: what, worth, when, where, the catch."""
    lines: list[str] = []

    category = _text(item.get("category"))
    label = KIND_LABELS.get(kind, "course item")
    lines.append(f"{course_code} {label}" + (f" ({category})." if category else "."))

    if points is not None and weight_pct is not None:
        worth = f"Worth: {points:g} pts ({weight_pct:g}% of the final grade)."
    elif weight_pct is not None:
        worth = f"Worth: {weight_pct:g}% of the final grade."
    elif points is not None:
        worth = f"Worth: {points:g} pts."
    else:
        worth = "Worth: not published separately."
    lines.append(worth)

    due_line = format_due(due_at)
    confidence = str(item.get("confidence") or "").strip().lower()
    if due_at is not None and confidence and confidence != "high":
        due_line = due_line[:-1] + f" (date confidence: {confidence} — verify before relying on it)."
    lines.append(due_line)

    target = submit_target(item, kind, platforms)
    if target:
        lines.append(f"Submit: {target}.")

    policy = policy_line(note, kind, item)
    if policy:
        lines.append(policy)

    notes = _text(item.get("notes"))
    if notes and len(lines) < 6:
        lines.append("Note: " + _clip(notes, MAX_NOTE_CHARS))

    return "\n".join(lines[:6])


def build_grading_scheme(note: dict[str, Any]) -> Any:
    """The note's grading data for courses.grading_scheme, or None when it has none."""
    if "grading_scheme" in note and note["grading_scheme"] is None:
        return None
    if isinstance(note.get("grading_scheme"), dict):
        return note["grading_scheme"]

    scheme: dict[str, Any] = {}
    weights = note.get("grading_weights_pct")
    if isinstance(weights, dict) and weights:
        scheme["weights_pct"] = weights
    if note.get("total_points"):
        scheme["points_total"] = note["total_points"]
    breakdown = note.get("project_score_breakdown_pts")
    if isinstance(breakdown, dict) and breakdown:
        scheme["project_score_breakdown_pts"] = breakdown
    if _text(note.get("grading_scale")):
        scheme["scale"] = _text(note["grading_scale"])

    policies: dict[str, str] = {}
    for key, name in (
        ("late_policy", "late"),
        ("drop_rules", "drops"),
        ("regrade_policy", "regrade"),
        ("ai_policy", "ai"),
        ("attendance_policy", "attendance"),
        ("peer_eval_policy", "peer_evaluation"),
        ("exams", "exams"),
        ("grading_notes", "grading"),
    ):
        value = _text(note.get(key))
        if value:
            policies[name] = value
    if policies:
        scheme["policies"] = policies

    if not scheme:
        return None

    insights = [
        _text(note.get(key))
        for key in ("grading_insight", "schedule_caveat", "data_quality_warning")
    ]
    insights = [value for value in insights if value]
    if insights:
        scheme["insights"] = insights

    scheme["source_note"] = {
        "file": note.get("_file"),
        "extracted_at": note.get("extracted_at"),
    }
    return scheme


def _scheme_body(scheme: Any) -> Any:
    """A scheme minus its provenance stamp, so a re-extraction alone is not a change."""
    if isinstance(scheme, dict):
        return {key: value for key, value in scheme.items() if key != "source_note"}
    return scheme


# ---------------------------------------------------------------------------
# The import record
# ---------------------------------------------------------------------------

class Counter:
    def __init__(self) -> None:
        self.created = 0
        self.updated = 0
        self.unchanged = 0
        self.kept = 0

    def add(self, verdict: str) -> None:
        setattr(self, verdict, getattr(self, verdict) + 1)

    def as_dict(self) -> dict[str, int]:
        return {verdict: getattr(self, verdict) for verdict in VERDICTS}

    def __str__(self) -> str:
        text = f"{self.created} created / {self.updated} updated / {self.unchanged} unchanged"
        return text + (f" / {self.kept} kept (edited by hand)" if self.kept else "")


class LoadReport:
    """Counts per entity plus `kept`: fields left alone because they were edited by hand."""

    def __init__(self) -> None:
        self.courses = Counter()
        self.meetings = Counter()
        self.platforms = Counter()
        self.grading = Counter()
        self.assignments = Counter()
        self.kept: list[str] = []
        self.course_ids: list[int] = []

    def as_dict(self) -> dict[str, Any]:
        return {
            "courses": self.courses.as_dict(),
            "meetings": self.meetings.as_dict(),
            "platforms": self.platforms.as_dict(),
            "grading_scheme": self.grading.as_dict(),
            "assignments": self.assignments.as_dict(),
            "kept": list(self.kept),
            "course_ids": list(self.course_ids),
        }


def _recorded(conn: sqlite3.Connection, entity: str, entity_id: int, field: str) -> tuple[bool, Any]:
    """(whether a load ever wrote this field, the value it wrote)."""
    row = conn.execute(
        "SELECT value FROM import_values WHERE entity = ? AND entity_id = ? AND field = ?",
        (entity, entity_id, field),
    ).fetchone()
    if row is None:
        return False, None
    try:
        return True, json.loads(row["value"]) if row["value"] is not None else None
    except ValueError:
        return True, row["value"]


def _record(
    conn: sqlite3.Connection, entity: str, entity_id: int, field: str, value: Any, dry: bool
) -> None:
    if dry:
        return
    conn.execute(
        "INSERT INTO import_values (entity, entity_id, field, value, written_at) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(entity, entity_id, field) DO UPDATE SET "
        "value = excluded.value, written_at = excluded.written_at",
        (entity, entity_id, field, json.dumps(value, ensure_ascii=False), db.now_iso()),
    )


# Marks a row typed by hand; every field of it belongs to the student.
MANUAL_MARK = "*"


def _mark_manual(conn: sqlite3.Connection, entity: str, entity_id: int, dry: bool) -> None:
    _record(conn, entity, entity_id, MANUAL_MARK, "manual", dry)


def _is_manual(conn: sqlite3.Connection, entity: str, entity_id: int) -> bool:
    return _recorded(conn, entity, entity_id, MANUAL_MARK)[0]


def _decide(
    conn: sqlite3.Connection,
    entity: str,
    entity_id: int,
    field: str,
    current: Any,
    proposed: Any,
    *,
    unrecorded: str,
    compare: Any = None,
) -> str:
    """'unchanged', 'updated' or 'kept' for one field of an existing row.

    `unrecorded` is the verdict when no load ever wrote the field; `compare` normalizes both sides.
    """
    view = compare or (lambda value: value)
    if _same(view(current), view(proposed)):
        return "unchanged"
    known, written = _recorded(conn, entity, entity_id, field)
    if not known:
        return unrecorded
    return "updated" if _same(view(current), view(written)) else "kept"


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _clean_meeting(raw: Any, code: str, index: int) -> dict[str, Any]:
    """One meeting from a note, checked against the same vocabularies the API uses."""
    where = f"{code} meeting {index + 1}"
    if not isinstance(raw, dict):
        raise LoaderError(f"{where} must be an object.")
    kind = str(raw.get("kind") or "").strip().lower()
    if kind not in db.COURSE_MEETING_KINDS:
        raise LoaderError(f"{where}: kind must be one of {', '.join(db.COURSE_MEETING_KINDS)}.")
    days = raw.get("days")
    if isinstance(days, str):
        days = list(days.replace(" ", ""))
    if not isinstance(days, list) or not days:
        raise LoaderError(f"{where}: days must be a list of day letters such as [\"M\", \"W\", \"F\"].")
    letters = [str(day).strip().upper() for day in days]
    unknown = [day for day in letters if day not in db.SCHOOL_DAY_CODES]
    if unknown:
        raise LoaderError(
            f"{where}: unknown day letter(s) {', '.join(unknown)}. "
            f"Use {' '.join(db.SCHOOL_DAY_CODES)} (R is Thursday, U is Sunday)."
        )
    # Registrar order, so "WM" and "MW" are one key.
    letters = sorted(dict.fromkeys(letters), key=lambda day: db.SCHOOL_DAY_CODES[day])
    start_time = str(raw.get("start_time") or "").strip()
    if not _HHMM_RE.match(start_time):
        raise LoaderError(f"{where}: start_time must be 24 hour HH:MM.")
    duration = raw.get("duration_min")
    if isinstance(duration, bool) or not isinstance(duration, int) or not 5 <= duration <= 600:
        raise LoaderError(f"{where}: duration_min must be a whole number of minutes (5-600).")
    dates = {}
    for key in ("start_date", "end_date"):
        value = _text(raw.get(key))
        if value is not None:
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                raise LoaderError(f"{where}: {key} must be YYYY-MM-DD.") from None
        dates[key] = value
    return {
        "kind": kind,
        "days": letters,
        "start_time": start_time,
        "duration_min": duration,
        "location": _text(raw.get("location")),
        "start_date": dates["start_date"],
        "end_date": dates["end_date"],
        "crn": _text(str(raw["crn"])) if raw.get("crn") is not None else None,
    }


def _clean_course_fields(code: str, note: dict[str, Any]) -> dict[str, Any]:
    """The course row a note describes, validated before anything is written."""
    title = _text(note.get("course_title"))
    if len(code) > MAX_COURSE_CODE or (title is not None and len(title) > MAX_COURSE_TITLE):
        raise LoaderError(f"{code}: the course code or title is too long.")

    credit_hours = note.get("credit_hours")
    if credit_hours is not None and (
        isinstance(credit_hours, bool) or not isinstance(credit_hours, (int, float)) or not 0 <= credit_hours <= 20
    ):
        raise LoaderError(f"{code}: credit_hours must be a number between 0 and 20.")

    instructors = note.get("instructors") or []
    if not isinstance(instructors, list) or len(instructors) > MAX_INSTRUCTORS:
        raise LoaderError(f"{code}: instructors must be a list of at most {MAX_INSTRUCTORS} names.")
    instructors = [name for name in (_text(item) for item in instructors) if name]

    return {
        "title": title,
        "credit_hours": float(credit_hours) if credit_hours is not None else None,
        "instructors": instructors,
        "term": _text(note.get("term")),
    }


def load_course(
    conn: sqlite3.Connection,
    code: str,
    note: dict[str, Any],
    report: LoadReport,
    *,
    dry: bool = False,
    track: bool = True,
) -> int | None:
    """Course id for a note: merged by code, or created when the note has a course_title.

    Dry runs still INSERT inside the caller's rolled-back transaction. `track=False`
    marks the rows manual so no later load overwrites them.
    """
    fields = _clean_course_fields(code, note)
    row = conn.execute("SELECT * FROM courses WHERE code = ?", (code,)).fetchone()

    if row is None:
        if fields["title"] is None:
            return None
        term = fields["term"] or db.SCHOOL_TERM
        cursor = conn.execute(
            "INSERT INTO courses (code, title, credit_hours, instructors, term, grading_scheme, "
            "color, created_at) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?)",
            (
                code,
                fields["title"],
                fields["credit_hours"],
                db.encode_json(fields["instructors"]),
                term,
                db.now_iso(),
            ),
        )
        course_id = int(cursor.lastrowid)
        if track:
            written = {**fields, "term": term}
            for field in COURSE_FIELDS:
                _record(conn, "course", course_id, field, written[field], dry)
        else:
            _mark_manual(conn, "course", course_id, dry)
        report.courses.add("created")
        return course_id

    course_id = int(row["id"])
    current = db.course_to_dict(row) or {}
    track = track and not _is_manual(conn, "course", course_id)
    verdicts: list[str] = []
    for field in COURSE_FIELDS:
        proposed = fields[field]
        if proposed is None or proposed == []:
            continue  # the note is silent; silence never blanks a value
        verdict = _decide(
            conn, "course", course_id, field, current.get(field), proposed, unrecorded="kept"
        )
        if verdict == "unchanged":
            if track:
                _record(conn, "course", course_id, field, proposed, dry)
        elif verdict == "updated":
            if not dry:
                conn.execute(
                    f"UPDATE courses SET {field} = ? WHERE id = ?",  # field is from COURSE_FIELDS
                    (db.encode_json(proposed) if field == "instructors" else proposed, course_id),
                )
            if track:
                _record(conn, "course", course_id, field, proposed, dry)
        else:
            report.kept.append(f"{code}: kept your {field.replace('_', ' ')}.")
        verdicts.append(verdict)

    if "updated" in verdicts:
        report.courses.add("updated")
    elif "kept" in verdicts:
        report.courses.add("kept")
    else:
        report.courses.add("unchanged")
    return course_id


def _meeting_key(meeting: dict[str, Any]) -> tuple[Any, ...]:
    return (meeting["kind"], tuple(meeting["days"]), meeting["start_time"])


def load_meetings(
    conn: sqlite3.Connection,
    course_id: int,
    code: str,
    note: dict[str, Any],
    report: LoadReport,
    *,
    dry: bool = False,
    track: bool = True,
) -> None:
    """Weekly meetings, matched by CRN or (kind, days, start time), merged like a course."""
    meetings_raw = note.get("meetings") or []
    if not isinstance(meetings_raw, list) or len(meetings_raw) > MAX_MEETINGS:
        raise LoaderError(f"{code}: meetings must be a list of at most {MAX_MEETINGS} entries.")
    meetings = [_clean_meeting(item, code, index) for index, item in enumerate(meetings_raw)]

    existing = [
        db.meeting_to_dict(row)
        for row in conn.execute(
            "SELECT * FROM course_meetings WHERE course_id = ? ORDER BY id", (course_id,)
        ).fetchall()
    ]
    for item in existing:
        days = item.get("days") if isinstance(item.get("days"), list) else []
        item["days"] = sorted(
            dict.fromkeys(str(day).upper() for day in days),
            key=lambda day: db.SCHOOL_DAY_CODES.get(day, 9),
        )

    for meeting in meetings:
        match = None
        if meeting["crn"]:
            match = next((row for row in existing if row.get("crn") == meeting["crn"]), None)
        if match is None:
            match = next((row for row in existing if _meeting_key(row) == _meeting_key(meeting)), None)

        if match is None:
            cursor = conn.execute(
                "INSERT INTO course_meetings (course_id, kind, days, start_time, duration_min, "
                "location, start_date, end_date, crn) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    course_id,
                    meeting["kind"],
                    db.encode_json(meeting["days"]),
                    meeting["start_time"],
                    meeting["duration_min"],
                    meeting["location"],
                    meeting["start_date"],
                    meeting["end_date"],
                    meeting["crn"],
                ),
            )
            meeting_id = int(cursor.lastrowid)
            if track:
                for field in MEETING_FIELDS:
                    _record(conn, "meeting", meeting_id, field, meeting[field], dry)
            else:
                _mark_manual(conn, "meeting", meeting_id, dry)
            existing.append({**meeting, "id": meeting_id})
            report.meetings.add("created")
            continue

        meeting_id = int(match["id"])
        tracked = track and not _is_manual(conn, "meeting", meeting_id)
        verdicts: list[str] = []
        for field in MEETING_FIELDS:
            proposed = meeting[field]
            if proposed is None:
                continue
            verdict = _decide(
                conn, "meeting", meeting_id, field, match.get(field), proposed, unrecorded="kept"
            )
            if verdict == "updated" and not dry:
                conn.execute(
                    f"UPDATE course_meetings SET {field} = ? WHERE id = ?",  # from MEETING_FIELDS
                    (proposed, meeting_id),
                )
            if verdict in ("updated", "unchanged") and tracked:
                _record(conn, "meeting", meeting_id, field, proposed, dry)
            if verdict == "kept":
                report.kept.append(
                    f"{code} {meeting['kind']} {''.join(meeting['days'])} {meeting['start_time']}: "
                    f"kept your {field.replace('_', ' ')}."
                )
            verdicts.append(verdict)
        report.meetings.add(
            "updated" if "updated" in verdicts else "kept" if "kept" in verdicts else "unchanged"
        )


def load_platforms(
    conn: sqlite3.Connection, course_id: int, note: dict[str, Any], report: LoadReport, *, dry: bool = False
) -> None:
    """One row per (course, platform, url). auth_mode and notes are refreshed."""
    for entry in note.get("platforms", []) or []:
        platform = str(entry.get("platform") or "").strip().lower()
        if platform not in db.COURSE_PLATFORMS:
            raise LoaderError(f"Unknown platform '{platform}'.")
        url = _text(entry.get("url"))
        auth_mode = _text(entry.get("auth_mode"))
        if auth_mode is not None and auth_mode not in db.COURSE_PLATFORM_AUTH_MODES:
            raise LoaderError(f"Unknown auth_mode '{auth_mode}'.")
        notes = _text(entry.get("notes"))
        # No name column, so a named platform keeps its name in notes.
        name = _text(entry.get("name"))
        if name and notes and not notes.startswith(name):
            notes = f"{name}: {notes}"
        elif name and not notes:
            notes = name

        if url is None:
            row = conn.execute(
                "SELECT * FROM course_platforms WHERE course_id = ? AND platform = ? "
                "AND url IS NULL",
                (course_id, platform),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM course_platforms WHERE course_id = ? AND platform = ? AND url = ?",
                (course_id, platform, url),
            ).fetchone()

        if row is None:
            report.platforms.add("created")
            if not dry:
                conn.execute(
                    "INSERT INTO course_platforms (course_id, platform, url, auth_mode, notes, "
                    "last_synced_at) VALUES (?, ?, ?, ?, ?, NULL)",
                    (course_id, platform, url, auth_mode, notes),
                )
            continue

        if _same(row["auth_mode"], auth_mode) and _same(row["notes"], notes):
            report.platforms.add("unchanged")
            continue
        report.platforms.add("updated")
        if not dry:
            conn.execute(
                "UPDATE course_platforms SET auth_mode = ?, notes = ? WHERE id = ?",
                (auth_mode, notes, row["id"]),
            )


def load_grading_scheme(
    conn: sqlite3.Connection,
    course_id: int,
    code: str,
    note: dict[str, Any],
    report: LoadReport,
    *,
    dry: bool = False,
    track: bool = True,
) -> None:
    scheme = build_grading_scheme(note)
    row = conn.execute("SELECT grading_scheme FROM courses WHERE id = ?", (course_id,)).fetchone()
    decoded = db.row_to_dict(row, ("grading_scheme",)) or {}
    current = decoded.get("grading_scheme")
    if scheme is None:
        report.grading.add("unchanged")
        return
    manual = _is_manual(conn, "course", course_id)
    track = track and not manual
    if current is None:
        verdict = "created"
    else:
        verdict = _decide(
            conn, "course", course_id, "grading_scheme", current, scheme,
            unrecorded="kept" if manual else "updated",
            compare=_scheme_body,
        )
    if verdict == "kept":
        report.kept.append(f"{code}: kept your grading scheme.")
    elif verdict in ("created", "updated") and not dry:
        conn.execute(
            "UPDATE courses SET grading_scheme = ? WHERE id = ?",
            (db.encode_json(scheme), course_id),
        )
    if verdict != "kept" and track:
        _record(conn, "course", course_id, "grading_scheme", _scheme_body(scheme), dry)
    report.grading.add(verdict)


def load_assignments(
    conn: sqlite3.Connection,
    course_id: int,
    course_code: str,
    note: dict[str, Any],
    report: LoadReport,
    *,
    dry: bool = False,
    track: bool = True,
) -> None:
    platforms = [entry for entry in (note.get("platforms") or []) if isinstance(entry, dict)]
    total_points = note.get("total_points")
    timestamp = db.now_iso()
    seen: dict[str, str] = {}

    for item in note.get("assignments", []) or []:
        title = _text(item.get("title"))
        if not title:
            raise LoaderError("An assignment in the note has no title.")

        slug = slugify(title)
        if slug in seen:
            raise LoaderError(
                f"Two assignments slug to '{slug}': '{seen[slug]}' and '{title}'. "
                "Retitle one in the note so the source_id stays unique."
            )
        seen[slug] = title

        kind = assignment_kind(item)
        due_at = assignment_due_at(item)
        ends_at, location = assignment_block(item, due_at)
        points = float(item["points"]) if item.get("points") is not None else None
        weight_pct = assignment_weight(item, total_points)
        brief_md = build_brief(
            note,
            item,
            course_code=course_code,
            kind=kind,
            due_at=due_at,
            points=points,
            weight_pct=weight_pct,
            platforms=platforms,
        )
        values = {
            "title": title,
            "kind": kind,
            "due_at": due_at,
            "points": points,
            "weight_pct": weight_pct,
            "brief_md": brief_md,
            "ends_at": ends_at,
            "location": location,
        }

        row = conn.execute(
            "SELECT * FROM assignments WHERE course_id = ? AND source = 'syllabus' "
            "AND source_id = ?",
            (course_id, slug),
        ).fetchone()

        if row is None:
            report.assignments.add("created")
            if not dry:
                cursor = conn.execute(
                    "INSERT INTO assignments (course_id, source, source_id, title, kind, due_at, "
                    "points, weight_pct, status, brief_md, url, harvested_at, updated_at, ends_at, "
                    "location) VALUES (?, 'syllabus', ?, ?, ?, ?, ?, ?, 'pending', ?, NULL, ?, ?, ?, ?)",
                    (
                        course_id, slug, title, kind, due_at, points, weight_pct,
                        brief_md, timestamp, timestamp, ends_at, location,
                    ),
                )
                if track:
                    for field in ASSIGNMENT_FIELDS:
                        _record(conn, "assignment", int(cursor.lastrowid), field, values[field], dry)
                else:
                    _mark_manual(conn, "assignment", int(cursor.lastrowid), dry)
            continue

        # Rows without a record refresh only if updated_at still equals harvested_at
        # (a later edit moves only updated_at).
        assignment_id = int(row["id"])
        untouched = row["updated_at"] is None or row["updated_at"] == row["harvested_at"]
        manual = _is_manual(conn, "assignment", assignment_id)
        unrecorded = "updated" if untouched and not manual else "kept"

        writes: dict[str, Any] = {}
        verdicts: list[str] = []
        for field in ASSIGNMENT_FIELDS:
            verdict = _decide(
                conn, "assignment", assignment_id, field, row[field], values[field],
                unrecorded=unrecorded,
            )
            if verdict == "updated":
                writes[field] = values[field]
            if verdict in ("updated", "unchanged") and track and not manual:
                _record(conn, "assignment", assignment_id, field, values[field], dry)
            if verdict == "kept" and field != "brief_md":
                report.kept.append(
                    f"{course_code} \"{row['title']}\": kept your "
                    f"{ASSIGNMENT_FIELD_LABELS.get(field, field.replace('_', ' '))}."
                )
            verdicts.append(verdict)

        if not writes:
            report.assignments.add("kept" if "kept" in verdicts else "unchanged")
            continue
        report.assignments.add("updated")
        if not dry:
            assignments = ", ".join(f"{field} = ?" for field in writes)  # from ASSIGNMENT_FIELDS
            conn.execute(
                f"UPDATE assignments SET {assignments}, harvested_at = ?, updated_at = ? WHERE id = ?",
                (*writes.values(), timestamp, timestamp, assignment_id),
            )


def apply_note(
    conn: sqlite3.Connection,
    note: dict[str, Any],
    *,
    report: LoadReport | None = None,
    dry: bool = False,
    track: bool = True,
) -> LoadReport:
    """Load one note inside the caller's transaction. Raises LoaderError.

    Call ensure_schema() first, outside the transaction: executescript() commits.
    """
    report = report or LoadReport()
    code = _text(note.get("course_code"))
    if not code:
        raise LoaderError(f"{note.get('_file') or 'The note'} has no course_code.")
    course_id = load_course(conn, code, note, report, dry=dry, track=track)
    if course_id is None:
        raise LoaderError(
            f"There is no course {code!r} yet and the note has no course_title to create it from."
        )
    load_meetings(conn, course_id, code, note, report, dry=dry, track=track)
    load_platforms(conn, course_id, note, report, dry=dry)
    load_grading_scheme(conn, course_id, code, note, report, dry=dry, track=track)
    load_assignments(conn, course_id, code, note, report, dry=dry, track=track)
    report.course_ids.append(course_id)
    return report


def counts(conn: sqlite3.Connection, tables: tuple[str, ...]) -> dict[str, int]:
    return {table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}


def load_notes(notes: list[dict[str, Any]], *, dry_run: bool = False) -> dict[str, Any]:
    """Load notes in one transaction; any LoaderError rolls back all of them.

    Notes for a missing course with no course_title are skipped. Dry runs roll back.
    """
    db.init_db()
    report = LoadReport()
    skipped: list[str] = []
    loaded: list[str] = []
    with db.get_db() as conn:
        ensure_schema(conn)
        before = counts(conn, UNTOUCHED_TABLES)
        conn.execute("BEGIN")
        try:
            for note in notes:
                name = note.get("_file") or "note"
                code = _text(note.get("course_code"))
                if not code:
                    raise LoaderError(f"{name} has no course_code.")
                exists = conn.execute("SELECT 1 FROM courses WHERE code = ?", (code,)).fetchone()
                if exists is None and _text(note.get("course_title")) is None:
                    skipped.append(
                        f"{name}: no course {code!r} in the database and no course_title in the "
                        "note to create it from - skipped."
                    )
                    continue
                apply_note(conn, note, report=report, dry=dry_run)
                loaded.append(f"{name}: {code} ({len(note.get('assignments') or [])} items in note)")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        conn.execute("ROLLBACK" if dry_run else "COMMIT")
        after = counts(conn, UNTOUCHED_TABLES)
    return {"report": report, "loaded": loaded, "skipped": skipped, "before": before, "after": after}
