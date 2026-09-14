"""The demo seed builds a whole semester, refuses a real one, and can be repeated.

It exercises the server's own loaders and appliers, so a change that breaks the
README screenshots fails here. Runs against a temporary database.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "app" / "server"))

import db  # noqa: E402
import onboarding  # noqa: E402
import school  # noqa: E402
import school_notes  # noqa: E402


def load_seed():
    spec = importlib.util.spec_from_file_location("seed_demo", REPO_ROOT / "scripts" / "seed_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SeedDemoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.original = (db.DB_PATH, onboarding.SYLLABI_DIR, onboarding.EXTRACT_DIR)
        self.original_push = school_notes._push_calendar
        self.original_urlopen = urllib.request.urlopen
        db.DB_PATH = root / "semester.db"
        onboarding.SYLLABI_DIR = root / "syllabi"
        onboarding.EXTRACT_DIR = root / "extracted"
        self.seed = load_seed()

    def tearDown(self) -> None:
        db.DB_PATH, onboarding.SYLLABI_DIR, onboarding.EXTRACT_DIR = self.original
        school_notes._push_calendar = self.original_push
        urllib.request.urlopen = self.original_urlopen
        self.temp.cleanup()

    def run_seed(self, *args: str) -> int:
        argv = sys.argv
        sys.argv = ["seed_demo.py", "--today", "2026-09-14", "--now", "10:40", *args]
        try:
            return self.seed.main()
        finally:
            sys.argv = argv

    def test_it_seeds_a_complete_semester_and_refuses_to_seed_twice(self) -> None:
        self.assertEqual(self.run_seed(), 0)

        courses = school.list_courses()
        self.assertEqual(len(courses), 5)
        work = school.list_assignments()
        self.assertGreaterEqual(len(work), 30)
        self.assertEqual({row["status"] for row in work}, {"graded", "in_progress", "pending"})
        exam = next(row for row in work if row["course_code"] == "CS 3200" and row["title"] == "Midterm")
        self.assertEqual((exam["due_at"], exam["ends_at"], exam["location"]),
                         ("2026-09-17T19:00", "2026-09-17T21:00", "Brandt Auditorium"))

        cs = next(course for course in courses if course["code"] == "CS 3200")
        overall = school.get_course(cs["id"])["grade_summary"]["overall"]
        self.assertIsNotNone(overall["current_avg_pct"])
        self.assertGreater(overall["remaining_pct"], 0)

        notes = {note["status"] for note in school_notes.list_notes()}
        self.assertEqual(notes, {"applied", "proposed"})
        self.assertEqual(len(school.list_events()), 2)
        sources = onboarding.list_sources()["sources"]
        self.assertEqual([source["status"] for source in sources], ["proposed"])
        self.assertEqual(sources[0]["problems"], [])

        self.assertEqual(self.run_seed(), 1)
        self.assertEqual(len(school.list_assignments()), len(work))

    def test_force_repeats_without_duplicating_anything(self) -> None:
        self.assertEqual(self.run_seed(), 0)
        before = (len(school.list_assignments()), len(school.list_todos()), len(school_notes.list_notes()))
        self.assertEqual(self.run_seed("--force"), 0)
        after = (len(school.list_assignments()), len(school.list_todos()), len(school_notes.list_notes()))
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
