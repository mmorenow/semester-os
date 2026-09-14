#!/usr/bin/env python3
"""Load the course notes in data/school/course-notes/ into the database.

Thin wrapper over app/server/course_notes.py. Idempotent; never deletes; keeps values edited in the app.

Usage:
    python3 scripts/load_course_notes.py            # load and report
    python3 scripts/load_course_notes.py --dry-run  # say what would change
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "app" / "server"
NOTES_DIR = REPO_ROOT / "data" / "school" / "course-notes"

sys.path.insert(0, str(SERVER_DIR))

import course_notes  # noqa: E402  (the path has to be set first)
import db  # noqa: E402


def print_report(conn, today: date) -> None:
    print("\nAssignments per course")
    rows = conn.execute(
        "SELECT c.code, COUNT(a.id) AS n, "
        "SUM(CASE WHEN a.id IS NOT NULL AND a.due_at IS NULL THEN 1 ELSE 0 END) AS undated "
        "FROM courses c LEFT JOIN assignments a ON a.course_id = c.id "
        "GROUP BY c.id ORDER BY c.code"
    ).fetchall()
    for row in rows:
        undated = f", {row['undated']} undated" if row["undated"] else ""
        print(f"  {row['code']:<11} {row['n']:>3}{undated}")
    total = conn.execute("SELECT COUNT(*) FROM assignments").fetchone()[0]
    print(f"  {'TOTAL':<11} {total:>3}")

    horizon = today + timedelta(days=7)
    print(f"\nDue in the next 7 days ({today.isoformat()} -> {horizon.isoformat()})")
    due = conn.execute(
        "SELECT c.code, a.title, a.due_at FROM assignments a JOIN courses c ON c.id = a.course_id "
        "WHERE a.due_at IS NOT NULL AND substr(a.due_at, 1, 10) BETWEEN ? AND ? "
        "ORDER BY a.due_at, c.code",
        (today.isoformat(), horizon.isoformat()),
    ).fetchall()
    if not due:
        print("  (nothing)")
    for row in due:
        print(f"  {row['due_at']:<17} {row['code']:<11} {row['title']}")

    todos = conn.execute(
        "SELECT title, due_at FROM school_todos WHERE done = 0 AND due_at IS NOT NULL "
        "AND substr(due_at, 1, 10) BETWEEN ? AND ? ORDER BY due_at",
        (today.isoformat(), horizon.isoformat()),
    ).fetchall()
    print("\nOpen todos in the same window")
    if not todos:
        print("  (nothing)")
    for row in todos:
        print(f"  {row['due_at']:<17} {row['title']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report without writing anything")
    parser.add_argument("--notes-dir", default=str(NOTES_DIR), help="folder of course note JSON")
    parser.add_argument("--today", default=None, help="YYYY-MM-DD for the 7 day window")
    args = parser.parse_args()

    today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else date.today()
    notes_dir = Path(args.notes_dir)
    files = sorted(notes_dir.glob("*.json"))
    if not files:
        print(f"No course notes in {notes_dir}.")
        return 1

    notes = []
    for path in files:
        note = json.loads(path.read_text(encoding="utf-8"))
        note["_file"] = path.name
        notes.append(note)

    result = course_notes.load_notes(notes, dry_run=args.dry_run)
    report = result["report"]

    for line in result["loaded"]:
        print(f"  · {line}")
    for line in result["skipped"]:
        print(f"  ! {line}")

    print()
    print(f"courses           {report.courses}")
    print(f"course_meetings   {report.meetings}")
    print(f"course_platforms  {report.platforms}")
    print(f"grading_scheme    {report.grading}")
    print(f"assignments       {report.assignments}")
    for line in report.kept:
        print(f"  = {line}")
    if args.dry_run:
        print("\n(dry run - nothing was written)")

    before, after = result["before"], result["after"]
    if before == after:
        print("\nNotes, runs and calendar untouched: " + ", ".join(f"{k}={v}" for k, v in before.items()))
    else:
        print("\n!! ROW COUNTS CHANGED IN TABLES THIS SCRIPT MUST NOT WRITE")
        print(f"   before {before}")
        print(f"   after  {after}")
        return 2

    with db.get_db() as conn:
        print_report(conn, today)
    return 0


if __name__ == "__main__":
    sys.exit(main())
