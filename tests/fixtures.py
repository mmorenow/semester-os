"""An invented test semester: five courses, seven weekly meetings.

The shapes are varied on purpose (lecture only, lecture+pso, lecture+lab, MWF and
TR patterns, a 75 minute block). The application itself seeds nothing.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import school
from db import encode_json, get_db, now_iso

TEST_TERM = "Fall 2026"

COURSES: tuple[dict[str, Any], ...] = (
    {
        "code": "CS 101",
        "title": "Introduction to Computing",
        "credit_hours": 3.0,
        "instructors": ["Ada Example"],
        "meetings": (
            {"kind": "lecture", "days": ["M", "W", "F"], "start_time": "11:30", "duration_min": 50,
             "location": "Room 101", "start_date": "2026-08-24", "end_date": "2026-12-12", "crn": "10001"},
        ),
    },
    {
        "code": "ENGL 106",
        "title": "First-Year Composition",
        "credit_hours": 3.0,
        "instructors": ["Grace Sample"],
        "meetings": (
            {"kind": "lecture", "days": ["M", "W", "F"], "start_time": "12:30", "duration_min": 50,
             "location": "Room 102", "start_date": "2026-08-24", "end_date": "2026-12-11", "crn": "10002"},
        ),
    },
    {
        "code": "CS 250",
        "title": "Data Structures",
        "credit_hours": 3.0,
        "instructors": ["Alan Placeholder"],
        "meetings": (
            {"kind": "lecture", "days": ["M", "W", "F"], "start_time": "13:30", "duration_min": 50,
             "location": "Room 103", "start_date": "2026-08-24", "end_date": "2026-12-11", "crn": "10003"},
            {"kind": "pso", "days": ["W"], "start_time": "14:30", "duration_min": 50,
             "location": "Room 104", "start_date": "2026-08-26", "end_date": "2026-12-09", "crn": "10004"},
        ),
    },
    {
        "code": "BIO 110",
        "title": "Introductory Biology",
        "credit_hours": 3.0,
        "instructors": ["Rosalind Test", "Barbara Mock"],
        "meetings": (
            {"kind": "lecture", "days": ["T", "R"], "start_time": "08:30", "duration_min": 50,
             "location": "Room 105", "start_date": "2026-08-25", "end_date": "2026-12-10", "crn": "10005"},
            {"kind": "lab", "days": ["T"], "start_time": "09:30", "duration_min": 110,
             "location": "Lab 106", "start_date": "2026-08-25", "end_date": "2026-12-08", "crn": "10006"},
        ),
    },
    {
        "code": "MATH 265",
        "title": "Linear Algebra",
        "credit_hours": 3.0,
        "instructors": ["Emmy Fixture"],
        "meetings": (
            {"kind": "lecture", "days": ["T", "R"], "start_time": "13:30", "duration_min": 75,
             "location": "Room 107", "start_date": "2026-08-25", "end_date": "2026-12-10", "crn": "10007"},
        ),
    },
)


def seed_semester(conn: sqlite3.Connection | None = None) -> dict[str, int]:
    """Insert the test semester into db.DB_PATH; idempotent by code and CRN+kind."""
    if conn is None:
        with get_db() as owned:
            return seed_semester(owned)

    created_courses = 0
    created_meetings = 0
    timestamp = now_iso()
    for course in COURSES:
        row = conn.execute("SELECT id FROM courses WHERE code = ?", (course["code"],)).fetchone()
        if row is None:
            cursor = conn.execute(
                "INSERT INTO courses (code, title, credit_hours, instructors, term, "
                "grading_scheme, color, created_at) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?)",
                (course["code"], course["title"], course["credit_hours"],
                 encode_json(course["instructors"]), TEST_TERM, timestamp),
            )
            course_id = int(cursor.lastrowid)
            created_courses += 1
        else:
            course_id = int(row["id"])

        for meeting in course["meetings"]:
            existing = conn.execute(
                "SELECT id FROM course_meetings WHERE course_id = ? AND kind = ? AND crn = ?",
                (course_id, meeting["kind"], meeting["crn"]),
            ).fetchone()
            if existing is not None:
                continue
            conn.execute(
                "INSERT INTO course_meetings (course_id, kind, days, start_time, duration_min, "
                "location, start_date, end_date, crn) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (course_id, meeting["kind"], encode_json(meeting["days"]), meeting["start_time"],
                 meeting["duration_min"], meeting["location"], meeting["start_date"],
                 meeting["end_date"], meeting["crn"]),
            )
            created_meetings += 1

    school._ensure_course_colors(conn)
    return {"courses_created": created_courses, "meetings_created": created_meetings}
