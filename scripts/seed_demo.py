#!/usr/bin/env python3
"""Fill an empty Semester OS with an invented mid-semester, dated so today is week 7.

Seeds five courses, graded assignments, todos, feed events, three notes with canned
agent replies and a syllabus ready to review, through the server's own functions.
Refuses a non-empty database or syllabi folder unless --force (safe to repeat).
No network: urllib is loopback-only and the Google Calendar push is disabled.

Usage, from the repository root:

    app/server/.venv/bin/python scripts/seed_demo.py
    app/server/.venv/bin/python scripts/seed_demo.py --today 2026-10-05   # pin the date
    app/server/.venv/bin/python scripts/seed_demo.py --force              # add to a non-empty one

To remove it, delete data/semester.db (plus -wal/-shm) and syllabi/cs2100-syllabus.md.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "app" / "server"))

import course_notes  # noqa: E402
import db  # noqa: E402
import onboarding  # noqa: E402
import runner  # noqa: E402
import school  # noqa: E402
import school_notes  # noqa: E402

EXAMPLE_SYLLABUS = REPO_ROOT / "examples" / "syllabi" / "cs2100-syllabus.md"
SCHOOL = "Example State University"

# Tables whose rows mean "somebody already has a semester in here".
OCCUPIED_TABLES = (
    "courses", "assignments", "school_todos", "school_notes", "school_events", "external_events",
)


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

def refuse_network() -> None:
    """Loopback-only urllib, the same guard the test suite uses."""
    real = urllib.request.urlopen

    def guarded(request, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003 - mirrors urlopen
        url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
        host = urllib.parse.urlsplit(url).hostname or ""
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise RuntimeError(f"The demo seed never reaches the network (attempted {host}).")
        return real(request, *args, **kwargs)

    urllib.request.urlopen = guarded
    # Applying a note pushes to Google when a connection exists. A demo must not.
    school_notes._push_calendar = lambda touched: None  # noqa: SLF001 - deliberate, see docstring


def what_is_there() -> list[str]:
    """Why this database or folder is not empty, one line per reason."""
    found: list[str] = []
    if Path(db.DB_PATH).exists():
        with db.get_db() as conn:
            tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            for table in (*OCCUPIED_TABLES, "syllabus_sources"):
                if table in tables:
                    count = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                    if count:
                        found.append(f"{table}: {count} rows in {db.DB_PATH}")
    folder = Path(onboarding.SYLLABI_DIR)
    if folder.is_dir():
        extra = [
            entry.name for entry in folder.iterdir()
            if entry.name not in (onboarding.README_NAME, onboarding.LINKS_NAME) and not entry.name.startswith(".")
        ]
        if extra:
            found.append(f"{folder}: {', '.join(sorted(extra))}")
    return found


# ---------------------------------------------------------------------------
# The calendar of an invented term, relative to today
# ---------------------------------------------------------------------------

class Term:
    """Week 1 began six weeks before this week's Monday, so today is in week 7."""

    def __init__(self, today: date, now: datetime) -> None:
        self.today = today
        self.now = now
        self.week1 = today - timedelta(days=today.weekday()) - timedelta(weeks=6)
        self.first_day = self.week1
        self.last_day = self.week1 + timedelta(weeks=15, days=4)
        middle = self.week1 + timedelta(weeks=4)
        season = "Spring" if middle.month <= 5 else "Summer" if middle.month <= 7 else "Fall"
        self.name = f"{season} {middle.year}"

    def day(self, week: int, weekday: int) -> date:
        """The date of a weekday (0 is Monday) in a week of the term (1 is the first)."""
        return self.week1 + timedelta(weeks=week - 1, days=weekday)

    def local(self, day: date, hhmm: str) -> datetime:
        hour, minute = (int(part) for part in hhmm.split(":"))
        return datetime.combine(day, time(hour, minute), tzinfo=school.LOCAL_TZ)

    def utc(self, day: date, hhmm: str) -> str:
        return school.utc_z(self.local(day, hhmm))

    def stamp(self, moment: datetime) -> str:
        """A stored timestamp, never later than the demo's own now."""
        return school.utc_z(min(moment, self.now))


MON, TUE, WED, THU, FRI = range(5)


# ---------------------------------------------------------------------------
# The five courses
#
# Assignment: (title, kind, category, week, weekday, due, end, location, weight_pct, grade).
# grade is (scored, out of), applied only to past work; past work without one is
# submitted. `open` marks work in progress.
# ---------------------------------------------------------------------------

COURSES: list[dict[str, Any]] = [
    {
        "course_code": "CS 3200",
        "course_title": "Data Structures and Algorithms",
        "credit_hours": 4,
        "instructors": ["Elena Marsh"],
        "meetings": [
            ("lecture", ["M", "W", "F"], "10:30", 50, "Halvorsen Hall 140", "31408"),
            ("lab", ["T"], "13:30", 110, "Sorrel Hall G56", "31415"),
        ],
        "platforms": [
            {"platform": "brightspace", "name": None, "url": None, "notes": "Grades and announcements."},
            {"platform": "gradescope", "name": None, "url": None, "notes": "Homework and project submission."},
            {"platform": "ed", "name": None, "url": None, "notes": "Questions and lab section changes."},
        ],
        "grading_weights_pct": {"Homework": 30, "Projects": 20, "Midterm": 20, "Final exam": 30},
        "grading_scale": "A 90 and above, B 80 to 89.99, C 70 to 79.99, D 60 to 69.99, F below 60.",
        "drop_rules": None,
        "late_policy": "Homework up to 24 hours late loses 20 percent; nothing is accepted after that.",
        "ai_policy": "AI tools may explain concepts but may not write code you submit for homework or projects.",
        "attendance_policy": "Lab attendance is required.",
        "regrade_policy": "Regrade requests go through Gradescope within one week of grades being released.",
        "assignments": [
            ("Homework 1", "hw", "Homework", 2, FRI, "23:59", None, None, 7.5, (92, 100)),
            ("Homework 2", "hw", "Homework", 4, FRI, "23:59", None, None, 7.5, (85, 100)),
            ("Project 1: Hash map", "project", "Projects", 5, WED, "23:59", None, None, 10, (47, 50)),
            ("Homework 3", "hw", "Homework", 6, FRI, "23:59", None, None, 7.5, (78, 100)),
            ("Midterm", "exam", "Midterm", 7, THU, "19:00", "21:00", "Brandt Auditorium", 20, None),
            ("Homework 4", "hw", "Homework", 8, FRI, "23:59", None, None, 7.5, "open"),
            ("Project 2: Graph search", "project", "Projects", 11, WED, "23:59", None, None, 10, None),
            ("Final exam", "exam", "Final exam", 17, MON, "08:00", "10:00", None, 30, None),
        ],
    },
    {
        "course_code": "MATH 2700",
        "course_title": "Linear Algebra",
        "credit_hours": 3,
        "instructors": ["Tomas Reyes"],
        "meetings": [
            ("lecture", ["T", "R"], "09:00", 75, "Larkin Hall 210", "22017"),
            ("pso", ["W"], "15:30", 50, "Larkin Hall 118", "22024"),
        ],
        "platforms": [
            {"platform": "brightspace", "name": None, "url": None, "notes": "Quizzes, grades and lecture notes."},
            {"platform": "other", "name": "Campuswire", "url": None, "notes": "Questions."},
        ],
        "grading_weights_pct": {"Quizzes": 20, "Midterm 1": 20, "Midterm 2": 20, "Final exam": 40},
        "grading_scale": "A 93, A- 90, B+ 87, B 83, B- 80, C+ 77, C 70, D 60.",
        "drop_rules": None,
        "late_policy": "Quizzes are taken in recitation and cannot be made up without an excused absence.",
        "ai_policy": None,
        "attendance_policy": None,
        "regrade_policy": None,
        "assignments": [
            ("Quiz 1", "quiz", "Quizzes", 2, THU, "09:00", None, None, 5, (9, 10)),
            ("Quiz 2", "quiz", "Quizzes", 4, THU, "09:00", None, None, 5, (8, 10)),
            ("Midterm 1", "exam", "Midterm 1", 5, TUE, "19:00", "20:30", "Larkin Hall 100", 20, (84, 100)),
            ("Quiz 3", "quiz", "Quizzes", 6, THU, "09:00", None, None, 5, (10, 10)),
            ("Quiz 4", "quiz", "Quizzes", 7, THU, "09:00", None, None, 5, None),
            ("Midterm 2", "exam", "Midterm 2", 10, TUE, "19:00", "20:30", "Larkin Hall 100", 20, None),
            ("Final exam", "exam", "Final exam", 17, WED, "13:00", "15:00", None, 40, None),
        ],
    },
    {
        "course_code": "PHYS 2210",
        "course_title": "Physics II: Electricity and Magnetism",
        "credit_hours": 4,
        "instructors": ["Hannah Velez"],
        "meetings": [
            ("lecture", ["M", "W", "F"], "12:30", 50, "Keller Hall 150", "40311"),
            ("lab", ["R"], "11:00", 110, "Keller Hall B12", "40326"),
        ],
        "platforms": [
            {"platform": "gradescope", "name": None, "url": None, "notes": "Problem set submission."},
            {"platform": "brightspace", "name": None, "url": None, "notes": "Grades, pre-lab quizzes."},
        ],
        "grading_weights_pct": {"Problem sets": 30, "Exam 1": 20, "Exam 2": 20, "Final exam": 30},
        "grading_scale": "A 90, B 80, C 70, D 60.",
        "drop_rules": "The lowest problem set score is replaced by the average of the others.",
        "late_policy": "Problem sets close at 5 PM on Friday; late work is not accepted.",
        "ai_policy": None,
        "attendance_policy": "Labs are required and cannot be made up.",
        "regrade_policy": None,
        "assignments": [
            ("Problem Set 1", "hw", "Problem sets", 2, FRI, "17:00", None, None, 6, (18, 20)),
            ("Problem Set 2", "hw", "Problem sets", 4, FRI, "17:00", None, None, 6, (17, 20)),
            ("Exam 1", "exam", "Exam 1", 6, WED, "18:30", "20:00", "Keller Hall 150", 20, (71, 100)),
            ("Problem Set 3", "hw", "Problem sets", 6, FRI, "17:00", None, None, 6, (19, 20)),
            ("Problem Set 4", "hw", "Problem sets", 7, FRI, "17:00", None, None, 6, "open"),
            ("Problem Set 5", "hw", "Problem sets", 9, FRI, "17:00", None, None, 6, None),
            ("Problem Set 6", "hw", "Problem sets", 12, FRI, "17:00", None, None, 6, None),
            ("Exam 2", "exam", "Exam 2", 12, WED, "18:30", "20:00", "Keller Hall 150", 20, None),
            ("Final exam", "exam", "Final exam", 17, TUE, "10:00", "12:00", None, 30, None),
        ],
    },
    {
        "course_code": "ECON 2010",
        "course_title": "Principles of Microeconomics",
        "credit_hours": 3,
        "instructors": ["Daniel Ashford"],
        "meetings": [
            ("lecture", ["T", "R"], "15:30", 75, "Weller Hall 101", "51102"),
        ],
        "platforms": [
            {"platform": "brightspace", "name": None, "url": None, "notes": "Reading responses and grades."},
        ],
        "grading_weights_pct": {"Reading responses": 10, "Problem sets": 20, "Midterm": 30, "Final exam": 40},
        "grading_scale": None,
        "drop_rules": None,
        "late_policy": "Reading responses close at the start of class.",
        "ai_policy": None,
        "attendance_policy": None,
        "regrade_policy": None,
        "assignments": [
            ("Reading response 1", "reading", "Reading responses", 3, TUE, "15:30", None, None, 5, (10, 10)),
            ("Problem set A", "hw", "Problem sets", 5, MON, "23:59", None, None, 10, (88, 100)),
            ("Reading response 2", "reading", "Reading responses", 7, TUE, "15:30", None, None, 5, None),
            ("Midterm", "exam", "Midterm", 8, THU, "15:30", "16:45", "Weller Hall 101", 30, None),
            ("Problem set B", "hw", "Problem sets", 10, MON, "23:59", None, None, 10, None),
            ("Final exam", "exam", "Final exam", 17, FRI, "15:00", "17:00", None, 40, None),
        ],
    },
    {
        "course_code": "DSGN 2300",
        "course_title": "Interaction Design Studio",
        "credit_hours": 3,
        "instructors": ["Ines Calloway"],
        "meetings": [
            ("lecture", ["M"], "15:00", 50, "Arden Hall 204", None),
            ("lab", ["F"], "14:00", 170, "Arden Studio 2", None),
        ],
        "platforms": [
            {"platform": "website", "name": None, "url": "https://design.example.edu/dsgn2300",
             "notes": "Briefs and critique schedule."},
        ],
        "grading_weights_pct": {"Studio participation": 10, "Project 1": 20, "Project 2": 25, "Final portfolio": 45},
        "grading_scale": None,
        "drop_rules": None,
        "late_policy": "Projects are presented at critique; a missed critique needs a make-up slot.",
        "ai_policy": "Generative tools are allowed for exploration and must be credited in the process book.",
        "attendance_policy": None,
        "regrade_policy": None,
        "assignments": [
            ("Project 1: Campus wayfinding", "project", "Project 1", 5, FRI, "14:00", None, "Arden Studio 2", 20, (91, 100)),
            ("Project 2: Transit app prototype", "project", "Project 2", 10, FRI, "14:00", None, "Arden Studio 2", 25, "open"),
            ("Final portfolio", "project", "Final portfolio", 16, FRI, "17:00", None, None, 45, None),
            ("Studio participation", "other", "Studio participation", None, None, None, None, None, 10, None),
        ],
    },
]


def course_note(term: Term, spec: dict[str, Any]) -> dict[str, Any]:
    """One course as the course-notes document a confirmed syllabus becomes."""
    meetings = []
    for kind, days, start, minutes, room, crn in spec["meetings"]:
        first = min(term.day(1, db.SCHOOL_DAY_CODES[letter]) for letter in days)
        last = max(term.day(16, db.SCHOOL_DAY_CODES[letter]) for letter in days)
        if kind != "lecture":  # labs and recitations start in week 2 and end a week early
            first += timedelta(weeks=1)
            last -= timedelta(weeks=1)
        meetings.append({
            "kind": kind, "days": days, "start_time": start, "duration_min": minutes, "location": room,
            "start_date": first.isoformat(), "end_date": last.isoformat(), "crn": crn,
        })
    assignments = []
    for title, kind, category, week, weekday, due, end, room, weight, _ in spec["assignments"]:
        assignments.append({
            "title": title, "kind": kind, "category": category,
            "due_date": term.day(week, weekday).isoformat() if week else None,
            "due_time": due, "end_time": end, "location": room,
            "points": None, "weight_pct": weight, "notes": None,
        })
    note = {key: value for key, value in spec.items() if key not in ("meetings", "assignments")}
    note.update({
        "term": term.name, "meetings": meetings, "assignments": assignments, "total_points": None,
        "_file": f"{spec['course_code'].replace(' ', '').lower()}-syllabus.pdf",
        "extracted_at": term.stamp(term.local(term.day(1, SUN_BEFORE), "20:00")),
    })
    return note


SUN_BEFORE = -1  # the Sunday before week 1, when the syllabi were read


def seed_courses(term: Term) -> dict[str, int]:
    notes = [course_note(term, spec) for spec in COURSES]
    with db.get_db() as conn:
        course_notes.ensure_schema(conn)
        conn.execute("BEGIN")
        try:
            for note in notes:
                course_notes.apply_note(conn, note)
        except Exception:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        # Created a week before classes, like a student setting up the term.
        conn.execute("UPDATE courses SET created_at = ?", (term.stamp(term.local(term.day(1, SUN_BEFORE), "20:05")),))
        return {row["code"]: int(row["id"]) for row in conn.execute("SELECT id, code FROM courses")}


def seed_progress(term: Term, course_ids: dict[str, int]) -> dict[str, int]:
    """Statuses and grades relative to the demo's now, so nothing future is graded."""
    counts = {"graded": 0, "submitted": 0, "in_progress": 0, "pending": 0}
    for spec in COURSES:
        course_id = course_ids[spec["course_code"]]
        rows = {row["title"]: row for row in school.list_assignments(course_id=course_id)}
        for title, _, _, week, weekday, due, _, _, _, grade in spec["assignments"]:
            row = rows[title]
            if week is None:
                counts["pending"] += 1
                continue
            due_at = term.local(term.day(week, weekday), due)
            if due_at < term.now and isinstance(grade, tuple):
                returned = due_at + timedelta(days=3, hours=-2)
                school.update_assignment(
                    row["id"], status="graded", status_given=True,
                    grade_points=grade[0], grade_points_given=True, grade_max=grade[1], grade_max_given=True,
                )
                touched = term.stamp(returned if returned < term.now else term.now - timedelta(hours=2))
                counts["graded"] += 1
            elif due_at < term.now:
                school.update_assignment(row["id"], status="submitted", status_given=True)
                touched = term.stamp(due_at - timedelta(hours=3))
                counts["submitted"] += 1
            elif grade == "open":
                school.update_assignment(row["id"], status="in_progress", status_given=True)
                touched = term.stamp(term.now - timedelta(days=1, hours=4))
                counts["in_progress"] += 1
            else:
                counts["pending"] += 1
                continue
            with db.get_db() as conn:
                conn.execute("UPDATE assignments SET updated_at = ? WHERE id = ?", (touched, row["id"]))
    return counts


def assignment_id(course_ids: dict[str, int], code: str, title: str) -> int:
    return next(row["id"] for row in school.list_assignments(course_id=course_ids[code]) if row["title"] == title)


def seed_todos(term: Term, course_ids: dict[str, int]) -> int:
    existing = {row["title"] for row in school.list_todos()}
    wanted = [
        ("Finish the CS 3200 practice midterm", "CS 3200", ("CS 3200", "Midterm"), term.day(7, WED), "17:00", False),
        ("Sketch three layouts for the transit app", "DSGN 2300",
         ("DSGN 2300", "Project 2: Transit app prototype"), term.day(7, FRI), "12:00", False),
        ("Ask Prof. Reyes about the Quiz 2 regrade", "MATH 2700", None, term.day(7, TUE), "09:00", False),
        ("Buy a bound lab notebook", "PHYS 2210", None, None, None, True),
        ("Renew the library study room for Thursday", None, None, term.day(7, WED), None, False),
    ]
    created = 0
    for title, code, work, day, hhmm, done in wanted:
        if title in existing:
            continue
        due = None if day is None else (term.utc(day, hhmm) if hhmm else day.isoformat())
        todo = school.create_todo(
            title,
            course_id=course_ids[code] if code else None,
            assignment_id=assignment_id(course_ids, *work) if work else None,
            due_at=due,
        )
        created += 1
        with db.get_db() as conn:
            created_at = term.stamp(term.now - timedelta(days=2, hours=created * 3))
            conn.execute(
                "UPDATE school_todos SET created_at = ?, done = ?, completed_at = ? WHERE id = ?",
                (created_at, 1 if done else 0, term.stamp(term.now - timedelta(hours=20)) if done else None, todo["id"]),
            )
    return created


# ---------------------------------------------------------------------------
# Notes, each answered by a canned agent reply
# ---------------------------------------------------------------------------

def _fenced(ops: list[dict[str, Any]], commentary: str) -> str:
    return "```json\n" + json.dumps({"ops": ops, "commentary": commentary}, indent=2) + "\n```\n"


def _note(term: Term, text: str, answer: str, created: datetime, *, apply: bool) -> str:
    """Create one note, attach a finished run that 'answered', and write it back."""
    with db.get_db() as conn:
        row = conn.execute("SELECT id, status FROM school_notes WHERE text = ?", (text,)).fetchone()
    if row is not None:
        return f"kept note {row['id']} ({row['status']})"

    note = school_notes.create_note(text)
    action_id = runner.create_action("school_note", {"note_id": note["id"]})
    school_notes.attach_action(note["id"], action_id)
    answered = created + timedelta(seconds=19)
    with db.get_db() as conn:
        conn.execute(
            "UPDATE actions SET status = 'done', result_md = ?, created_at = ?, started_at = ?, finished_at = ? "
            "WHERE id = ?",
            (answer, term.stamp(created), term.stamp(created), term.stamp(answered), action_id),
        )
    result = school_notes.write_back(note["id"], answer)
    if result["status"] != "proposed":
        raise SystemExit(f"The canned answer for {text!r} was refused: {result.get('error')}")
    if apply:
        result = school_notes.apply_note(note["id"])
    with db.get_db() as conn:
        conn.execute(
            "UPDATE school_notes SET created_at = ?, resolved_at = ?, applied_at = ? WHERE id = ?",
            (
                term.stamp(created),
                term.stamp(answered),
                term.stamp(answered + timedelta(minutes=2)) if apply else None,
                note["id"],
            ),
        )
        if apply:
            conn.execute(
                "UPDATE school_events SET created_at = ?, updated_at = ? WHERE note_id = ?",
                (term.stamp(answered + timedelta(minutes=2)),) * 2 + (note["id"],),
            )
    return f"note {note['id']} {result['status']}"


def seed_notes(term: Term, course_ids: dict[str, int]) -> list[str]:
    cs, phys = course_ids["CS 3200"], course_ids["PHYS 2210"]
    review_day, fair_day = term.day(7, WED), term.day(7, THU)
    friday, next_monday = term.day(7, FRI), term.day(10, MON)
    ps5 = assignment_id(course_ids, "PHYS 2210", "Problem Set 5")

    def spoken(day: date) -> str:
        return f"{day.strftime('%a %b')} {day.day}"

    outcomes = []
    outcomes.append(_note(
        term,
        "the TA is running a CS 3200 midterm review Wednesday 6-7:30pm in Halvorsen 140. "
        "also the career fair is Thursday 5 to 7 in the Student Union ballroom",
        _fenced(
            [
                {"op": "create_event", "title": "Midterm review session",
                 "start_at": term.utc(review_day, "18:00"), "end_at": term.utc(review_day, "19:30"),
                 "all_day": False, "location": "Halvorsen Hall 140", "course_id": cs, "notes": "Run by the TAs.",
                 "summary": f"Add CS 3200 midterm review session, {spoken(review_day)}, 6:00-7:30 PM, Halvorsen Hall 140"},
                {"op": "create_event", "title": "Career fair",
                 "start_at": term.utc(fair_day, "17:00"), "end_at": term.utc(fair_day, "19:00"),
                 "all_day": False, "location": "Student Union ballroom", "course_id": None, "notes": None,
                 "summary": f"Add Career fair, {spoken(fair_day)}, 5:00-7:00 PM, Student Union ballroom"},
            ],
            "Two calendar events. The review session is tied to CS 3200 because the note names the course "
            "and its midterm; the career fair belongs to no course. Wednesday and Thursday resolve to this week.",
        ),
        term.local(term.day(6, FRI), "21:14"),
        apply=True,
    ))
    outcomes.append(_note(
        term,
        "move the midterm to next thursday",
        _fenced(
            [
                {"op": "comment",
                 "summary": "Two midterms could be meant: CS 3200 Midterm and ECON 2010 Midterm. Which one moved?"},
            ],
            "Nothing was changed. CS 3200 has a Midterm this Thursday and ECON 2010 has a Midterm the Thursday "
            "after, so \"the midterm\" matches both. Send the note again with the course, for example "
            "\"the ECON midterm moved to next Thursday\".",
        ),
        term.local(term.today - timedelta(days=1), "22:05"),
        apply=False,
    ))
    outcomes.append(_note(
        term,
        "Dr. Velez added extra office hours Friday 10-11am in Keller 214, and PS 5 is now due the Monday after "
        "at noon",
        _fenced(
            [
                {"op": "create_event", "title": "Extra office hours",
                 "start_at": term.utc(friday, "10:00"), "end_at": term.utc(friday, "11:00"),
                 "all_day": False, "location": "Keller Hall 214", "course_id": phys, "notes": None,
                 "summary": f"Add PHYS 2210 extra office hours, {spoken(friday)}, 10:00-11:00 AM, Keller Hall 214"},
                {"op": "update_assignment", "assignment_id": ps5,
                 "set": {"due_at": term.utc(next_monday, "12:00")},
                 "summary": f"Move Problem Set 5 (PHYS 2210) due date to {spoken(next_monday)}, 12:00 PM"},
            ],
            "Dr. Velez teaches PHYS 2210, so both changes are in that course. \"The Monday after\" is read as "
            f"the Monday after Problem Set 5's current Friday deadline, {spoken(next_monday)}.",
        ),
        term.local(term.today, "08:52") if term.now.time() > time(8, 52) else term.now - timedelta(minutes=40),
        apply=False,
    ))
    return outcomes


# ---------------------------------------------------------------------------
# Imported calendar feeds
# ---------------------------------------------------------------------------

def seed_external_events(term: Term) -> int:
    """A few events as if the Brightspace and Outlook feeds had just been read."""
    events = [
        ("outlook", "Robotics club meeting", term.day(7, MON), "16:30", "17:30", "Halvorsen Hall 402", False),
        ("outlook", "Advising appointment", term.day(7, TUE), "11:00", "11:30", "Student Success Center", False),
        ("outlook", "Robotics club meeting", term.day(7, FRI), "09:00", "09:45", "Halvorsen Hall 402", False),
        ("brightspace", "PHYS 2210: Pre-lab quiz 7 closes", term.day(7, THU), "08:00", "08:00", "PHYS 2210", False),
        ("brightspace", "DSGN 2300: Critique sign-up opens", term.day(7, WED), None, None, "DSGN 2300", True),
        ("brightspace", "ECON 2010: Midterm study guide posted", term.day(7, MON), None, None, "ECON 2010", True),
    ]
    seen = term.stamp(term.now - timedelta(minutes=9))
    with db.get_db() as conn:
        for index, (source, title, day, start, end, where, all_day) in enumerate(events):
            if all_day:
                start_at, end_at = day.isoformat(), (day + timedelta(days=1)).isoformat()
            else:
                start_at, end_at = term.utc(day, start), term.utc(day, end)
            conn.execute(
                "INSERT INTO external_events (source, uid, instance_start, title, location, description, start_at, "
                "end_at, all_day, first_seen_at, last_seen_at, is_active) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, 1) "
                "ON CONFLICT(source, uid, instance_start) DO NOTHING",
                (source, f"demo-{source}-{index}@example.edu", start_at, title, where, start_at, end_at,
                 1 if all_day else 0, seen, seen),
            )
        for source in ("outlook", "brightspace"):
            count = sum(1 for event in events if event[0] == source)
            conn.execute(
                "INSERT INTO ics_sync_state (source, last_sync_at, ok, error, event_count) VALUES (?, ?, 1, NULL, ?) "
                "ON CONFLICT(source) DO UPDATE SET last_sync_at = excluded.last_sync_at, ok = 1, error = NULL, "
                "event_count = excluded.event_count",
                (source, seen, count),
            )
    return len(events)


# ---------------------------------------------------------------------------
# A syllabus waiting on Set up
# ---------------------------------------------------------------------------

CS2100_PROPOSAL: dict[str, Any] = {
    "course_code": "CS 2100",
    "course_title": "Object-Oriented Programming in Java",
    "credit_hours": 4,
    "term": "Fall 2026",
    "instructors": ["Ada Park"],
    "meetings": [
        {"kind": "lecture", "days": ["M", "W", "F"], "start_time": "10:30", "duration_min": 50,
         "location": "Keating Hall 1142", "start_date": "2026-08-24", "end_date": "2026-12-11", "crn": "20417"},
        {"kind": "lab", "days": ["T"], "start_time": "13:30", "duration_min": 110,
         "location": "Sorrel Hall G56", "start_date": "2026-09-01", "end_date": "2026-12-08", "crn": "20433"},
    ],
    "platforms": [
        {"platform": "brightspace", "name": None, "url": None, "notes": "Grades, announcements and lecture recordings."},
        {"platform": "gradescope", "name": None, "url": None, "notes": "Every homework and project is submitted here."},
        {"platform": "ed", "name": None, "url": None, "notes": "Questions, clarifications and lab section changes."},
    ],
    "grading_weights_pct": {"Homework": 25, "Labs": 10, "Quizzes": 10, "Midterm 1": 15, "Midterm 2": 15,
                            "Final exam": 25},
    "total_points": None,
    "grading_scale": "A 90 and above, B 80 to 89.99, C 70 to 79.99, D 60 to 69.99, F below 60. Cutoffs may be "
                     "lowered at the end of the semester, never raised.",
    "drop_rules": "The two lowest lab scores and the lowest quiz score are dropped. No homework score is dropped.",
    "late_policy": "Homework up to 24 hours late loses 20 percent; nothing is accepted after 24 hours. Two free "
                   "24-hour extensions per semester, requested on Ed before the deadline.",
    "ai_policy": "Generative AI may explain concepts but may not write code submitted for homework, labs or exams.",
    "attendance_policy": "Lab attendance is required; a missed lab scores zero unless excused.",
    "regrade_policy": "Regrade requests go through Gradescope within one week of grades being released.",
    "assignments": [
        {"title": "Homework 1", "kind": "hw", "category": "Homework", "due_date": "2026-09-04", "due_time": "23:59",
         "end_time": None, "location": None, "points": None, "weight_pct": None, "notes": None},
        {"title": "Homework 2", "kind": "hw", "category": "Homework", "due_date": "2026-09-11", "due_time": "23:59",
         "end_time": None, "location": None, "points": None, "weight_pct": None, "notes": None},
        {"title": "Homework 3", "kind": "hw", "category": "Homework", "due_date": "2026-09-25", "due_time": "23:59",
         "end_time": None, "location": None, "points": None, "weight_pct": None,
         "notes": "The schedule says \"Friday of week 5\"."},
        {"title": "Midterm 1", "kind": "exam", "category": "Midterm 1", "due_date": "2026-10-01", "due_time": "20:00",
         "end_time": "22:00", "location": None, "points": None, "weight_pct": 15, "notes": None},
        {"title": "Homework 4", "kind": "hw", "category": "Homework", "due_date": "2026-10-09", "due_time": "23:59",
         "end_time": None, "location": None, "points": None, "weight_pct": None, "notes": None},
        {"title": "Homework 5", "kind": "hw", "category": "Homework", "due_date": "2026-10-23", "due_time": "23:59",
         "end_time": None, "location": None, "points": None, "weight_pct": None, "notes": None},
        {"title": "Project 1", "kind": "project", "category": None, "due_date": "2026-10-28", "due_time": None,
         "end_time": None, "location": None, "points": None, "weight_pct": None, "notes": None},
        {"title": "Homework 6", "kind": "hw", "category": "Homework", "due_date": "2026-11-06", "due_time": "23:59",
         "end_time": None, "location": None, "points": None, "weight_pct": None, "notes": None},
        {"title": "Midterm 2", "kind": "exam", "category": "Midterm 2", "due_date": "2026-11-12", "due_time": "20:00",
         "end_time": "22:00", "location": None, "points": None, "weight_pct": 15, "notes": None},
        {"title": "Homework 7", "kind": "hw", "category": "Homework", "due_date": "2026-11-20", "due_time": "23:59",
         "end_time": None, "location": None, "points": None, "weight_pct": None, "notes": None},
        {"title": "Homework 8", "kind": "hw", "category": "Homework", "due_date": "2026-12-04", "due_time": "23:59",
         "end_time": None, "location": None, "points": None, "weight_pct": None, "notes": None},
        {"title": "Project 2", "kind": "project", "category": None, "due_date": None, "due_time": None,
         "end_time": None, "location": None, "points": None, "weight_pct": None,
         "notes": "Listed in week 16 with the due date to be announced."},
        {"title": "Final exam", "kind": "exam", "category": "Final exam", "due_date": None, "due_time": None,
         "end_time": None, "location": None, "points": None, "weight_pct": 25,
         "notes": "Cumulative. Scheduled by the registrar during finals week, December 14-19."},
    ],
    "uncertain": [
        {"field": "meetings[1].start_date", "reason": "Labs start in week 2; the first Tuesday of week 2 was used."},
        {"field": "assignments[2].due_date",
         "reason": "Computed from \"Friday of week 5\", with week 1 beginning Monday, August 24."},
        {"field": "assignments[3].location", "reason": "The room is posted on Brightspace, not in the syllabus."},
        {"field": "assignments[6].due_time", "reason": "No time is given for projects; homework is due at 11:59 PM."},
        {"field": "assignments[8].location", "reason": "The room is posted on Brightspace, not in the syllabus."},
        {"field": "assignments[11].due_date", "reason": "The due date is to be announced."},
        {"field": "assignments[12].due_date", "reason": "Set by the registrar once finals are scheduled."},
    ],
}

CS2100_COMMENTARY = (
    "Read the whole syllabus. CS 2100 meets Monday, Wednesday and Friday at 10:30 with a two-hour Tuesday lab "
    "that starts in week 2. The grade is 25% homework, 10% labs, 10% quizzes, two midterms at 15% each and a 25% "
    "final. Eight homeworks and both midterms are dated; both midterms are evening exams whose rooms are only "
    "posted on Brightspace. Project 2 and the final exam have no date yet."
)


def seed_syllabus(term: Term) -> str:
    onboarding.ensure_folder()
    source = onboarding.save_upload(EXAMPLE_SYLLABUS.name, EXAMPLE_SYLLABUS.read_bytes())
    if source["status"] != "queued":
        return f"kept source {source['id']} ({source['status']})"
    answer = "```json\n" + json.dumps({**CS2100_PROPOSAL, "commentary": CS2100_COMMENTARY}, indent=2) + "\n```\n"
    action_id = runner.create_action("syllabus_import", {"source_id": source["id"]})
    read_at = term.now - timedelta(minutes=25)
    with db.get_db() as conn:
        conn.execute(
            "UPDATE actions SET status = 'done', result_md = ?, created_at = ?, started_at = ?, finished_at = ? "
            "WHERE id = ?",
            (answer, term.stamp(read_at), term.stamp(read_at), term.stamp(read_at + timedelta(seconds=48)), action_id),
        )
        conn.execute(
            "UPDATE syllabus_sources SET status = 'reading', action_id = ?, read_started_at = ? WHERE id = ?",
            (action_id, term.stamp(read_at), source["id"]),
        )
    result = onboarding.write_back(source["id"], answer, action_id=action_id)
    if result["status"] != "proposed":
        raise SystemExit(f"The canned syllabus proposal was refused: {result.get('error')}")
    with db.get_db() as conn:
        conn.execute(
            "UPDATE syllabus_sources SET created_at = ?, resolved_at = ?, updated_at = ? WHERE id = ?",
            (term.stamp(read_at - timedelta(minutes=1)), term.stamp(read_at + timedelta(seconds=48)),
             term.stamp(read_at + timedelta(seconds=48)), source["id"]),
        )
    return f"source {source['id']} ready to review"


# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--today", help="Pretend today is this YYYY-MM-DD (the demo is dated around it).")
    parser.add_argument("--now", default=None, help="Local HH:MM for 'now' on that day (default: the real time).")
    parser.add_argument("--force", action="store_true", help="Seed even though the database or folder is not empty.")
    args = parser.parse_args()

    local_now = datetime.now(school.LOCAL_TZ)
    today = date.fromisoformat(args.today) if args.today else local_now.date()
    clock = time.fromisoformat(args.now) if args.now else local_now.time().replace(microsecond=0)
    now = datetime.combine(today, clock, tzinfo=school.LOCAL_TZ)
    if now.astimezone(timezone.utc) > datetime.now(timezone.utc) + timedelta(days=45):
        print("--today is more than 45 days ahead; timestamps are capped at that day anyway.")

    refuse_network()
    db.init_db()
    if not args.force:
        occupied = what_is_there()
        if occupied:
            print("Refusing to seed: this is not an empty Semester OS.", file=sys.stderr)
            for line in occupied:
                print(f"  {line}", file=sys.stderr)
            print("Use a throwaway checkout or database, or pass --force to add the demo anyway.", file=sys.stderr)
            return 1

    term = Term(today, now)
    print(f"Seeding {SCHOOL}, {term.name}: week 1 began {term.week1:%a %b %d}, today is {today:%a %b %d} (week 7).")
    print(f"  database  {db.DB_PATH}")
    print(f"  syllabi   {onboarding.SYLLABI_DIR}")
    course_ids = seed_courses(term)
    print(f"  courses   {', '.join(course_ids)}")
    print(f"  progress  {seed_progress(term, course_ids)}")
    print(f"  todos     {seed_todos(term, course_ids)} created")
    for outcome in seed_notes(term, course_ids):
        print(f"  notes     {outcome}")
    print(f"  calendar  {seed_external_events(term)} imported events")
    print(f"  set up    {seed_syllabus(term)}")
    print("Done. Start the app with ./semester-os and open Today.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
