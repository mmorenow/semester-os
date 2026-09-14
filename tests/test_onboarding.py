"""Onboarding: syllabi in, a proposal out, and one confirmed write.

No agent runs: the course-importer's answer is handed to the write-back directly.
Every course and person here is invented; all state lives in a temp directory.
"""

from __future__ import annotations

import asyncio
import json
import socket
import stat
import sys
import tempfile
import unittest
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "app" / "server"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import course_notes  # noqa: E402
import db  # noqa: E402
import onboarding  # noqa: E402
import runner  # noqa: E402
import school  # noqa: E402
from school import SchoolError  # noqa: E402

PDF_BYTES = b"%PDF-1.4\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"


def proposal(**overrides: object) -> dict:
    """A complete, valid proposal for an invented course, with overrides on top."""
    doc = {
        "course_code": "CS 180",
        "course_title": "Problem Solving and Object-Oriented Programming",
        "credit_hours": 4,
        "term": "Fall 2026",
        "instructors": ["Ada Park"],
        "meetings": [
            {"kind": "lecture", "days": ["M", "W", "F"], "start_time": "10:30", "duration_min": 50,
             "location": "Hall 101", "start_date": "2026-08-24", "end_date": "2026-12-11", "crn": None},
            {"kind": "lab", "days": "T", "start_time": "13:30", "duration_min": 110,
             "location": None, "start_date": None, "end_date": None, "crn": "40123"},
        ],
        "platforms": [
            {"platform": "gradescope", "name": None, "url": None, "notes": "Homework submissions"},
            {"platform": "other", "name": "Piazza", "url": None, "notes": "Questions"},
        ],
        "grading_weights_pct": {"Homework": 30, "Labs": 10, "Midterm exams": 30, "Final exam": 30},
        "total_points": None,
        "grading_scale": None,
        "drop_rules": "The lowest homework score is dropped.",
        "late_policy": "10 percent off per day late.",
        "ai_policy": None,
        "attendance_policy": None,
        "regrade_policy": None,
        "assignments": [
            {"title": "Homework 1", "kind": "hw", "category": "Homework", "due_date": "2026-09-04",
             "due_time": "23:59", "points": 20, "weight_pct": None, "notes": None},
            {"title": "Midterm 1", "kind": "exam", "category": "Midterm exams", "due_date": None,
             "due_time": None, "points": None, "weight_pct": 15, "notes": "Week 7."},
        ],
        "uncertain": [
            {"field": "meetings[1].location", "reason": "The lab room is not stated."},
            {"field": "assignments[1].due_date", "reason": "Only week 7 is given."},
        ],
    }
    doc.update(overrides)
    return doc


def answer(doc: object, commentary: str = "Read the whole syllabus.") -> str:
    body = dict(doc) if isinstance(doc, dict) else doc
    if isinstance(body, dict):
        body["commentary"] = commentary
    return f"Here is the proposal.\n\n```json\n{json.dumps(body)}\n```\n"


class OnboardingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.original = (db.DB_PATH, onboarding.SYLLABI_DIR, onboarding.EXTRACT_DIR)
        db.DB_PATH = root / "semester.db"
        db.init_db(db.DB_PATH)
        onboarding.SYLLABI_DIR = root / "syllabi"
        onboarding.EXTRACT_DIR = root / "extracted"

        self.submitted: list[int] = []
        self.original_submit = runner.submit
        self.original_cli = runner.claude_cli_available
        runner.submit = self.submitted.append
        runner.claude_cli_available = lambda: True

    def tearDown(self) -> None:
        runner.submit = self.original_submit
        runner.claude_cli_available = self.original_cli
        db.DB_PATH, onboarding.SYLLABI_DIR, onboarding.EXTRACT_DIR = self.original
        self.temp.cleanup()

    def file_source(self, name: str = "cs180.pdf", data: bytes = PDF_BYTES) -> dict:
        return onboarding.save_upload(name, data)

    def reading(self, name: str = "cs180.pdf", data: bytes = PDF_BYTES) -> dict:
        source = self.file_source(name, data)
        return onboarding.start_reading(source["id"])

    def proposed(self, doc: dict | None = None, name: str = "cs180.pdf", data: bytes = PDF_BYTES) -> dict:
        source = self.reading(name, data)
        result = onboarding.write_back(source["id"], answer(doc or proposal()), action_id=source["action_id"])
        self.assertEqual(result["status"], "proposed", result.get("error"))
        return result

    def course(self, code: str = "CS 180") -> dict:
        return next(course for course in school.list_courses() if course["code"] == code)

    def assignments(self, code: str = "CS 180") -> list[dict]:
        return school.list_assignments(course_id=self.course(code)["id"])


class UploadValidationTests(OnboardingTestCase):
    def test_a_pdf_lands_directly_inside_the_folder_private_and_queued(self) -> None:
        source = self.file_source("CS 180 Syllabus.pdf")

        path = onboarding.SYLLABI_DIR / "CS 180 Syllabus.pdf"
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_bytes(), PDF_BYTES)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(source["status"], "queued")
        self.assertEqual(source["kind"], "file")
        self.assertTrue((onboarding.SYLLABI_DIR / "README.txt").is_file())

    def test_names_that_reach_outside_the_folder_are_refused(self) -> None:
        for name in ("../escape.pdf", "sub/dir.pdf", "..\\escape.pdf", ".hidden.pdf", "a\x00b.pdf", "/etc/x.pdf"):
            with self.subTest(name=name), self.assertRaises(SchoolError) as raised:
                onboarding.save_upload(name, PDF_BYTES)
            self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(
            sorted(path.name for path in Path(self.temp.name).rglob("*.pdf")), []
        )

    def test_unsupported_extensions_are_refused_with_a_way_forward(self) -> None:
        for name in ("syllabus.doc", "syllabus.exe", "syllabus", "slides.pptx"):
            with self.subTest(name=name), self.assertRaises(SchoolError) as raised:
                onboarding.save_upload(name, PDF_BYTES)
            self.assertEqual(raised.exception.status_code, 415)
        with self.assertRaises(SchoolError) as raised:
            onboarding.save_upload("syllabus.pages", PDF_BYTES)
        self.assertIn("PDF", raised.exception.detail)

    def test_the_size_cap_and_empty_files(self) -> None:
        with self.assertRaises(SchoolError) as raised:
            onboarding.save_upload("big.txt", b"a" * (onboarding.MAX_UPLOAD_BYTES + 1))
        self.assertEqual(raised.exception.status_code, 413)
        with self.assertRaises(SchoolError):
            onboarding.save_upload("empty.txt", b"")

    def test_bytes_that_are_not_what_the_extension_claims_are_refused(self) -> None:
        with self.assertRaises(SchoolError):
            onboarding.save_upload("fake.pdf", b"MZ\x90\x00 not a pdf")
        with self.assertRaises(SchoolError):
            onboarding.save_upload("fake.docx", b"plain text")
        with self.assertRaises(SchoolError):
            onboarding.save_upload("binary.txt", b"text\x00with a nul")

    def test_odd_characters_are_repaired_and_nothing_is_ever_overwritten(self) -> None:
        first = self.file_source("Syllabus – Fall ’26.pdf")
        self.assertEqual(first["name"], "Syllabus - Fall -26.pdf")

        same = self.file_source("Syllabus – Fall ’26.pdf")
        self.assertEqual(same["id"], first["id"])  # the same bytes are one source

        other = self.file_source("Syllabus – Fall ’26.pdf", PDF_BYTES + b"% v2\n")
        self.assertEqual(other["name"], "Syllabus - Fall -26-2.pdf")
        self.assertEqual((onboarding.SYLLABI_DIR / first["name"]).read_bytes(), PDF_BYTES)

    def test_the_upload_route_enforces_the_cap_while_reading_the_body(self) -> None:
        from fastapi import HTTPException
        from starlette.requests import Request

        import app as server_app

        def request(body: bytes, declared: int | None) -> Request:
            headers = [] if declared is None else [(b"content-length", str(declared).encode())]
            chunks = [body[i:i + 65536] for i in range(0, len(body), 65536)] or [b""]

            async def receive() -> dict:
                chunk = chunks.pop(0) if chunks else b""
                return {"type": "http.request", "body": chunk, "more_body": bool(chunks)}

            scope = {"type": "http", "method": "POST", "path": "/api/onboarding/uploads",
                     "headers": headers, "query_string": b""}
            return Request(scope, receive)

        created = asyncio.run(server_app.onboarding_upload(request(PDF_BYTES, len(PDF_BYTES)), filename="a.pdf"))
        self.assertEqual(created["status"], "queued")

        with self.assertRaises(HTTPException) as declared:
            asyncio.run(server_app.onboarding_upload(request(b"", onboarding.MAX_UPLOAD_BYTES + 1), filename="b.pdf"))
        self.assertEqual(declared.exception.status_code, 413)

        oversized = b"%PDF-" + b"0" * onboarding.MAX_UPLOAD_BYTES
        with self.assertRaises(HTTPException) as streamed:
            asyncio.run(server_app.onboarding_upload(request(oversized, None), filename="c.pdf"))
        self.assertEqual(streamed.exception.status_code, 413)
        self.assertFalse((onboarding.SYLLABI_DIR / "c.pdf").exists())


class UrlValidationTests(OnboardingTestCase):
    def test_a_course_website_is_normalized_and_registered_once(self) -> None:
        first = onboarding.add_link("  https://cs.example.edu/cs180/#schedule ")
        again = onboarding.add_link("https://cs.example.edu/cs180/")

        self.assertEqual(first["url"], "https://cs.example.edu/cs180/")
        self.assertEqual(first["name"], "cs.example.edu/cs180")
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(first["status"], "queued")

    def test_everything_but_a_public_https_address_is_refused(self) -> None:
        for url in (
            "http://cs.example.edu/cs180",
            "ftp://cs.example.edu/",
            "https://user:pass@cs.example.edu/",
            "https://localhost/syllabus",
            "https://127.0.0.1/",
            "https://10.0.0.5/",
            "https://192.168.1.1/",
            "https://[::1]/",
            "https://169.254.169.254/latest/meta-data",
            "https://printer.local/",
            "https://cs.example.edu/a b",
            "javascript:alert(1)",
            "https://nodot/",
            "",
        ):
            with self.subTest(url=url), self.assertRaises(SchoolError):
                onboarding.add_link(url)

    def test_links_txt_in_the_folder_registers_valid_lines_and_names_the_rest(self) -> None:
        folder = onboarding.ensure_folder()
        (folder / "links.txt").write_text(
            "# course sites\nhttps://math.example.edu/ma265\nhttp://insecure.example.edu/\n",
            encoding="utf-8",
        )
        listing = onboarding.list_sources()

        urls = [source["url"] for source in listing["sources"] if source["kind"] == "url"]
        self.assertEqual(urls, ["https://math.example.edu/ma265"])
        self.assertIn("links.txt line 3", [item["name"] for item in listing["skipped"]])


class FolderScanTests(OnboardingTestCase):
    def test_new_files_are_queued_unsupported_ones_are_named_and_gone_ones_marked(self) -> None:
        folder = onboarding.ensure_folder()
        (folder / "bio110.md").write_text("# BIO 110 syllabus\n", encoding="utf-8")
        (folder / "old.doc").write_bytes(b"\xd0\xcf\x11\xe0")

        listing = onboarding.list_sources()
        names = {source["name"]: source for source in listing["sources"]}
        self.assertEqual(names["bio110.md"]["status"], "queued")
        self.assertEqual([item["name"] for item in listing["skipped"]], ["old.doc"])

        (folder / "bio110.md").unlink()
        after = {source["name"]: source for source in onboarding.list_sources()["sources"]}
        self.assertTrue(after["bio110.md"]["missing"])

    def test_a_changed_file_that_was_already_applied_is_queued_again(self) -> None:
        source = self.proposed(name="cs180.md", data=b"# CS 180\n")
        onboarding.apply_source(source["id"])
        path = onboarding.SYLLABI_DIR / "cs180.md"
        path.write_bytes(b"# CS 180, revised\n")

        refreshed = onboarding.get_source(source["id"])
        self.assertEqual(refreshed["status"], "applied")  # not until the folder is scanned
        onboarding.list_sources()
        self.assertEqual(onboarding.get_source(source["id"])["status"], "queued")


class WriteBackTests(OnboardingTestCase):
    def test_a_good_answer_becomes_a_normalized_proposal_and_writes_nothing_else(self) -> None:
        source = self.proposed()

        self.assertEqual(source["commentary"], "Read the whole syllabus.")
        self.assertEqual(source["proposal"]["meetings"][1]["days"], ["T"])
        self.assertEqual(source["proposal"]["meetings"][1]["crn"], "40123")
        self.assertEqual(len(source["proposal"]["uncertain"]), 2)
        self.assertEqual(source["problems"], [])
        self.assertEqual(source["warnings"], [])
        self.assertIsNone(source["existing_course"])
        self.assertEqual(school.list_courses(), [])

    def test_an_answer_with_no_json_block_fails_with_the_reason(self) -> None:
        source = self.reading()
        failed = onboarding.write_back(source["id"], "I could not open the file, sorry.", action_id=source["action_id"])

        self.assertEqual(failed["status"], "failed")
        self.assertIn("no json block", failed["error"])

    def test_malformed_json_is_a_failure_not_an_empty_proposal(self) -> None:
        source = self.reading()
        failed = onboarding.write_back(
            source["id"], '```json\n{"course_code": "CS 180", "meetings": [\n```', action_id=source["action_id"]
        )
        self.assertEqual(failed["status"], "failed")

    def test_an_unknown_key_anywhere_refuses_the_whole_proposal(self) -> None:
        cases = {
            "top level": proposal(office_hours="Tue 3pm"),
            "meeting": proposal(meetings=[{**proposal()["meetings"][0], "building": "Hall"}]),
            "assignment": proposal(assignments=[{**proposal()["assignments"][0], "rubric": "x"}]),
            "platform": proposal(platforms=[{"platform": "ed", "name": None, "url": None, "notes": None, "id": 3}]),
            "uncertain": proposal(uncertain=[{"field": "term", "reason": "x", "confidence": "low"}]),
        }
        for label, doc in cases.items():
            with self.subTest(label):
                source = self.reading(name=f"{label.replace(' ', '-')}.pdf", data=PDF_BYTES + label.encode())
                failed = onboarding.write_back(source["id"], answer(doc), action_id=source["action_id"])
                self.assertEqual(failed["status"], "failed")
                self.assertIn("does not take", failed["error"])

    def test_values_outside_the_closed_vocabularies_are_refused(self) -> None:
        cases = {
            "meeting kind": proposal(meetings=[{**proposal()["meetings"][0], "kind": "seminar"}]),
            "day letter": proposal(meetings=[{**proposal()["meetings"][0], "days": ["M", "Th"]}]),
            "assignment kind": proposal(assignments=[{**proposal()["assignments"][0], "kind": "lab"}]),
            "platform": proposal(platforms=[{"platform": "canvas", "name": None, "url": None, "notes": None}]),
            "12 hour time": proposal(meetings=[{**proposal()["meetings"][0], "start_time": "10:30 AM"}]),
            "date": proposal(assignments=[{**proposal()["assignments"][0], "due_date": "Sep 4"}]),
            "weight": proposal(grading_weights_pct={"Homework": 130}),
            "uncertain path": proposal(uncertain=[{"field": "assignments[9].due_date", "reason": "x"}]),
        }
        for label, doc in cases.items():
            with self.subTest(label):
                source = self.reading(name=f"{label.replace(' ', '-')}.pdf", data=PDF_BYTES + label.encode())
                failed = onboarding.write_back(source["id"], answer(doc), action_id=source["action_id"])
                self.assertEqual(failed["status"], "failed", label)

    def test_weights_that_do_not_add_up_are_flagged_and_do_not_block(self) -> None:
        source = self.proposed(proposal(grading_weights_pct={"Homework": 30, "Exams": 65}))

        self.assertEqual(source["status"], "proposed")
        self.assertEqual(len(source["warnings"]), 1)
        self.assertIn("95%", source["warnings"][0]["message"])
        self.assertEqual(source["problems"], [])

    def test_missing_values_are_problems_that_block_confirm_not_refusals(self) -> None:
        doc = proposal(
            course_code=None,
            meetings=[{"kind": "lecture", "days": ["T", "R"], "start_time": None, "duration_min": None,
                       "location": None, "start_date": None, "end_date": None, "crn": None}],
            assignments=[
                {"title": "Quiz 1", "kind": "quiz", "category": None, "due_date": None, "due_time": "09:00",
                 "points": None, "weight_pct": None, "notes": None},
                {"title": "quiz 1", "kind": "quiz", "category": None, "due_date": None, "due_time": None,
                 "points": None, "weight_pct": None, "notes": None},
            ],
            uncertain=[],
        )
        source = self.proposed(doc)
        fields = [problem["field"] for problem in source["problems"]]

        self.assertIn("course_code", fields)
        self.assertIn("meetings[0].start_time", fields)
        self.assertIn("assignments[0].due_date", fields)
        self.assertIn("assignments[1].title", fields)
        with self.assertRaises(SchoolError) as raised:
            onboarding.apply_source(source["id"])
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(school.list_courses(), [])

    def test_a_stale_run_cannot_overwrite_the_source(self) -> None:
        source = self.reading()
        result = onboarding.write_back(source["id"], answer(proposal()), action_id=source["action_id"] + 99)

        self.assertEqual(result["status"], "reading")
        self.assertIsNone(result["proposal"])


class ApplyTests(OnboardingTestCase):
    def test_confirming_writes_the_course_its_meetings_weights_and_work(self) -> None:
        source = self.proposed()
        applied = onboarding.apply_source(source["id"])

        self.assertEqual(applied["status"], "applied")
        course = self.course()
        self.assertEqual(applied["applied_course_id"], course["id"])
        self.assertEqual(course["title"], "Problem Solving and Object-Oriented Programming")
        self.assertEqual(course["instructors"], ["Ada Park"])
        self.assertEqual(len(course["meetings"]), 2)
        self.assertEqual(course["grading_scheme"]["weights_pct"]["Homework"], 30)
        self.assertEqual(course["grading_scheme"]["policies"]["drops"], "The lowest homework score is dropped.")
        work = {row["title"]: row for row in self.assignments()}
        self.assertEqual(work["Homework 1"]["due_at"], "2026-09-04T23:59")
        self.assertIsNone(work["Midterm 1"]["due_at"])
        self.assertEqual(applied["applied_changes"]["assignments"]["created"], 2)

    def test_an_exam_with_hours_and_a_room_becomes_a_block_not_a_note(self) -> None:
        exam = {"title": "Midterm 2", "kind": "exam", "category": "Midterm exams", "due_date": "2026-11-12",
                "due_time": "20:00", "end_time": "22:00", "location": "Hall 200", "points": None,
                "weight_pct": 15, "notes": None}
        doc = proposal(assignments=[*proposal()["assignments"], exam])
        source = self.proposed(doc)
        self.assertEqual(source["proposal"]["assignments"][2]["end_time"], "22:00")
        self.assertEqual(source["proposal"]["assignments"][0]["end_time"], None)

        onboarding.apply_source(source["id"])
        work = {row["title"]: row for row in self.assignments()}
        self.assertEqual(work["Midterm 2"]["due_at"], "2026-11-12T20:00")
        self.assertEqual(work["Midterm 2"]["ends_at"], "2026-11-12T22:00")
        self.assertEqual(work["Midterm 2"]["location"], "Hall 200")
        self.assertIsNone(work["Midterm 2"]["notes"])
        self.assertNotIn("Hall 200", work["Midterm 2"]["brief_md"])
        self.assertIsNone(work["Homework 1"]["ends_at"])
        self.assertIsNone(work["Homework 1"]["location"])
        # The block reads back as campus time, two hours long, like one typed by hand.
        start = school.parse_instant(work["Midterm 2"]["due_at"])
        end = school.parse_instant(work["Midterm 2"]["ends_at"])
        self.assertEqual((end - start).total_seconds(), 7200)

    def test_an_end_time_needs_a_start_time_and_has_to_come_after_it(self) -> None:
        base = {"title": "Final exam", "kind": "exam", "category": "Final exam", "due_date": "2026-12-15",
                "due_time": None, "end_time": "10:00", "location": "Hall 1", "points": None,
                "weight_pct": 30, "notes": None}
        cases = {
            "no start": (base, "assignments[0].due_time"),
            "backwards": ({**base, "due_time": "10:00", "end_time": "08:00"}, "assignments[0].end_time"),
        }
        for label, (item, field) in cases.items():
            with self.subTest(label):
                source = self.proposed(
                    proposal(assignments=[item], uncertain=[]),
                    name=f"{label.replace(' ', '-')}.pdf",
                    data=PDF_BYTES + label.encode(),
                )
                self.assertIn(field, [problem["field"] for problem in source["problems"]])
                with self.assertRaises(SchoolError):
                    onboarding.apply_source(source["id"])
        with self.subTest("malformed end time is refused outright"):
            source = self.reading(name="bad-end.pdf", data=PDF_BYTES + b"bad end")
            failed = onboarding.write_back(
                source["id"], answer(proposal(assignments=[{**base, "end_time": "10pm"}], uncertain=[])),
                action_id=source["action_id"],
            )
            self.assertEqual(failed["status"], "failed")

    def test_a_room_moved_by_hand_survives_a_reimport(self) -> None:
        exam = {"title": "Midterm 2", "kind": "exam", "category": "Midterm exams", "due_date": "2026-11-12",
                "due_time": "20:00", "end_time": "22:00", "location": "Hall 200", "points": None,
                "weight_pct": 15, "notes": None}
        onboarding.apply_source(self.proposed(proposal(assignments=[exam], uncertain=[]))["id"])
        midterm = self.assignments()[0]
        school.update_assignment(midterm["id"], location="Annex 3", location_given=True)

        moved = {**exam, "end_time": "21:30"}
        again = self.proposed(proposal(assignments=[moved], uncertain=[]), name="v2.pdf", data=PDF_BYTES + b"v2")
        report = onboarding.apply_source(again["id"])["applied_changes"]

        row = self.assignments()[0]
        self.assertEqual(row["location"], "Annex 3")
        self.assertEqual(row["ends_at"], "2026-11-12T21:30")
        self.assertIn('CS 180 "Midterm 2": kept your location.', report["kept"])

    def test_editing_before_confirming_is_validated_and_what_is_confirmed(self) -> None:
        source = self.proposed()
        edited = dict(source["proposal"])
        edited["course_title"] = "Problem Solving and OOP"
        edited["assignments"] = [*edited["assignments"], {
            "title": "Final exam", "kind": "exam", "category": "Final exam", "due_date": "2026-12-15",
            "due_time": "08:00", "points": None, "weight_pct": 30, "notes": None}]

        with self.assertRaises(SchoolError):
            onboarding.update_proposal(source["id"], {**edited, "surprise": 1})
        onboarding.apply_source(source["id"], edited)

        self.assertEqual(self.course()["title"], "Problem Solving and OOP")
        self.assertIn("Final exam", [row["title"] for row in self.assignments()])
        self.assertEqual(onboarding.get_source(source["id"])["proposal"]["course_title"], "Problem Solving and OOP")

    def test_confirm_and_discard_only_from_proposed(self) -> None:
        source = self.proposed()
        onboarding.discard_source(source["id"])
        for action in (onboarding.apply_source, onboarding.discard_source):
            with self.subTest(action.__name__), self.assertRaises(SchoolError) as raised:
                action(source["id"])
            self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(school.list_courses(), [])

    def test_reimporting_the_same_course_updates_instead_of_duplicating(self) -> None:
        first = self.proposed()
        onboarding.apply_source(first["id"])

        revised = proposal()
        revised["assignments"][0]["due_date"] = "2026-09-05"
        revised["assignments"].append({"title": "Homework 2", "kind": "hw", "category": "Homework",
                                       "due_date": "2026-09-11", "due_time": "23:59", "points": 20,
                                       "weight_pct": None, "notes": None})
        revised["meetings"][0]["location"] = "Hall 202"
        second = self.proposed(revised, name="cs180-v2.pdf", data=PDF_BYTES + b"% v2")
        self.assertEqual(second["existing_course"]["code"], "CS 180")
        applied = onboarding.apply_source(second["id"])

        self.assertEqual(len([c for c in school.list_courses() if c["code"] == "CS 180"]), 1)
        work = {row["title"]: row for row in self.assignments()}
        self.assertEqual(len(work), 3)
        self.assertEqual(work["Homework 1"]["due_at"], "2026-09-05T23:59")
        meetings = self.course()["meetings"]
        self.assertEqual(len(meetings), 2)
        self.assertIn("Hall 202", [meeting["location"] for meeting in meetings])
        self.assertEqual(applied["applied_changes"]["assignments"]["created"], 1)
        self.assertEqual(applied["applied_changes"]["kept"], [])

    def test_applying_the_same_proposal_twice_changes_nothing_the_second_time(self) -> None:
        onboarding.apply_source(self.proposed()["id"])
        before = {row["id"]: row["updated_at"] for row in self.assignments()}

        again = self.proposed(name="copy.pdf", data=PDF_BYTES + b"% copy")
        report = onboarding.apply_source(again["id"])["applied_changes"]

        self.assertEqual(report["assignments"], {"created": 0, "updated": 0, "unchanged": 2, "kept": 0})
        self.assertEqual(report["meetings"]["created"], 0)
        self.assertEqual(report["grading_scheme"]["updated"], 0)
        self.assertEqual({row["id"]: row["updated_at"] for row in self.assignments()}, before)


class ManualEditsPreservedTests(OnboardingTestCase):
    def test_a_value_changed_by_hand_survives_a_reimport_and_the_rest_follows_the_syllabus(self) -> None:
        onboarding.apply_source(self.proposed()["id"])
        homework = next(row for row in self.assignments() if row["title"] == "Homework 1")
        # The student moved the deadline through a confirmed note, and fixed
        # the lecture room directly.
        school.update_assignment(homework["id"], due_at="2026-09-06T12:00", due_at_given=True)
        course = self.course()
        lecture = next(m for m in course["meetings"] if m["kind"] == "lecture")
        with db.get_db() as conn:
            conn.execute("UPDATE course_meetings SET location = 'Annex 3' WHERE id = ?", (lecture["id"],))
            conn.execute("UPDATE courses SET title = 'CS 180 (my name for it)' WHERE id = ?", (course["id"],))

        revised = proposal(course_title="Problem Solving and OOP, revised", credit_hours=3)
        revised["assignments"][0]["due_date"] = "2026-09-05"
        revised["assignments"][0]["points"] = 25
        revised["meetings"][0]["location"] = "Hall 303"
        second = self.proposed(revised, name="v2.pdf", data=PDF_BYTES + b"% v2")
        report = onboarding.apply_source(second["id"])["applied_changes"]

        homework = next(row for row in self.assignments() if row["title"] == "Homework 1")
        self.assertEqual(homework["due_at"], "2026-09-06T12:00")  # kept
        self.assertEqual(homework["points"], 25.0)  # not edited, so it follows
        course = self.course()
        self.assertEqual(course["title"], "CS 180 (my name for it)")  # kept
        self.assertEqual(course["credit_hours"], 3.0)  # not edited, so it follows
        self.assertIn("Annex 3", [m["location"] for m in course["meetings"]])
        self.assertEqual(len(report["kept"]), 3)

    def test_a_course_typed_in_by_hand_is_never_overwritten_by_a_later_syllabus(self) -> None:
        runner.claude_cli_available = lambda: False
        manual = onboarding.create_manual("CS 180", "My CS course")
        with self.assertRaises(SchoolError) as raised:
            onboarding.start_reading(manual["id"])
        self.assertEqual(raised.exception.status_code, 503)

        draft = dict(manual["proposal"])
        draft["meetings"] = [{"kind": "lecture", "days": ["M", "W", "F"], "start_time": "10:30",
                              "duration_min": 50, "location": "My room", "start_date": None,
                              "end_date": None, "crn": None}]
        onboarding.apply_source(manual["id"], draft)
        self.assertEqual(self.course()["title"], "My CS course")

        runner.claude_cli_available = lambda: True
        onboarding.apply_source(self.proposed()["id"])

        course = self.course()
        self.assertEqual(course["title"], "My CS course")
        self.assertEqual([m["location"] for m in course["meetings"] if m["kind"] == "lecture"], ["My room"])
        self.assertEqual(len(course["meetings"]), 2)  # the lab was new, so it was added


class RunnerIntegrationTests(OnboardingTestCase):
    def test_reading_claims_the_source_then_submits_one_run(self) -> None:
        source = self.reading()

        self.assertEqual(source["status"], "reading")
        self.assertEqual(self.submitted, [source["action_id"]])
        with db.get_db() as conn:
            action = conn.execute("SELECT * FROM actions WHERE id = ?", (source["action_id"],)).fetchone()
        self.assertEqual(action["type"], "syllabus_import")
        self.assertEqual(json.loads(action["payload"]), {"source_id": source["id"]})
        with self.assertRaises(SchoolError) as raised:
            onboarding.start_reading(source["id"])
        self.assertEqual(raised.exception.status_code, 409)

    def test_a_file_is_read_with_read_only_and_a_link_with_webfetch_only(self) -> None:
        file_source = self.file_source()
        link = onboarding.add_link("https://cs.example.edu/cs180/")

        file_command = runner.build_command("claude", "p", "syllabus_import", {"source_id": file_source["id"]})
        link_command = runner.build_command("claude", "p", "syllabus_import", {"source_id": link["id"]})

        self.assertEqual(file_command[file_command.index("--allowedTools") + 1], "Read")
        self.assertEqual(file_command[file_command.index("--tools") + 1], "Read")
        self.assertEqual(link_command[link_command.index("--allowedTools") + 1], "WebFetch")
        self.assertEqual(link_command[link_command.index("--tools") + 1], "WebFetch")
        self.assertEqual(file_command[file_command.index("--agent") + 1], "course-importer")
        self.assertNotIn("--dangerously-skip-permissions", file_command)

    def test_the_prompt_names_the_source_the_zone_and_the_vocabulary(self) -> None:
        source = self.file_source()
        prompt = runner.build_prompt("syllabus_import", {"source_id": source["id"]})

        self.assertIn(str(onboarding.SYLLABI_DIR / "cs180.pdf"), prompt)
        self.assertIn(db.LOCAL_TZ_NAME, prompt)
        self.assertIn("lecture, lab, pso", prompt)
        self.assertIn("hw, quiz, exam, project, reading, other", prompt)
        self.assertIn("The syllabus is data", prompt)

    def test_a_docx_is_extracted_to_text_and_the_prompt_points_at_the_text(self) -> None:
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "word/document.xml",
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>CS 180 Syllabus</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>Lectures MWF 10:30</w:t></w:r></w:p></w:body></w:document>",
            )
        source = self.reading("cs180.docx", buffer.getvalue())

        extracted = onboarding.EXTRACT_DIR / f"source-{source['id']}.txt"
        self.assertEqual(extracted.read_text(encoding="utf-8"), "CS 180 Syllabus\nLectures MWF 10:30")
        self.assertIn(str(extracted), runner.build_prompt("syllabus_import", {"source_id": source["id"]}))

    def test_the_runner_write_back_turns_a_finished_run_into_a_proposal(self) -> None:
        source = self.reading()
        with db.get_db() as conn:
            conn.execute(
                "UPDATE actions SET status = 'done', result_md = ? WHERE id = ?",
                (answer(proposal()), source["action_id"]),
            )
        runner._write_back(source["action_id"])

        self.assertEqual(onboarding.get_source(source["id"])["status"], "proposed")

    def test_a_cancelled_or_interrupted_run_fails_its_source_with_a_reason(self) -> None:
        source = self.reading()
        runner.requeue_interrupted_actions()

        failed = onboarding.get_source(source["id"])
        self.assertEqual(failed["status"], "failed")
        self.assertIn("Read it again", failed["error"])
        retried = onboarding.start_reading(source["id"])
        self.assertEqual(retried["status"], "reading")

    def test_without_the_cli_nothing_starts_and_the_reason_says_how_to_install_it(self) -> None:
        source = self.file_source()
        runner.claude_cli_available = lambda: False
        with self.assertRaises(SchoolError) as raised:
            onboarding.start_reading(source["id"])

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("Claude Code CLI", raised.exception.detail)
        self.assertEqual(self.submitted, [])
        self.assertEqual(onboarding.get_source(source["id"])["status"], "queued")


class NoNetworkTests(OnboardingTestCase):
    def test_the_session_guard_still_refuses_the_network(self) -> None:
        with self.assertRaises(RuntimeError):
            urllib.request.urlopen("https://cs.example.edu/cs180/")

    def test_registering_reading_and_applying_a_link_opens_no_socket(self) -> None:
        original = socket.create_connection

        def refuse(*args, **kwargs):  # noqa: ANN002, ANN003 - mirrors create_connection
            raise AssertionError("onboarding opened a network connection")

        socket.create_connection = refuse
        try:
            link = onboarding.add_link("https://cs.example.edu/cs180/")
            started = onboarding.start_reading(link["id"])
            onboarding.write_back(link["id"], answer(proposal()), action_id=started["action_id"])
            onboarding.apply_source(link["id"])
        finally:
            socket.create_connection = original
        self.assertEqual(self.course()["code"], "CS 180")


class CommandLineLoaderTests(OnboardingTestCase):
    def test_the_thin_wrapper_path_loads_and_a_second_run_is_unchanged(self) -> None:
        note = {**proposal(), "_file": "cs180.json"}
        note.pop("uncertain")
        first = course_notes.load_notes([note])
        second = course_notes.load_notes([dict(note)])

        self.assertEqual(first["report"].assignments.created, 2)
        self.assertEqual(second["report"].assignments.as_dict(), {"created": 0, "updated": 0, "unchanged": 2, "kept": 0})
        self.assertEqual(first["before"], first["after"])

    def test_the_loader_refuses_an_end_time_it_cannot_anchor(self) -> None:
        item = {"title": "Midterm 1", "kind": "exam", "due_date": "2026-10-01", "end_time": "22:00"}
        with self.assertRaises(course_notes.LoaderError):
            course_notes.assignment_block(item, course_notes.assignment_due_at(item))
        timed = {**item, "due_time": "20:00", "location": "  Hall   200 "}
        self.assertEqual(
            course_notes.assignment_block(timed, course_notes.assignment_due_at(timed)),
            ("2026-10-01T22:00", "Hall 200"),
        )
        self.assertEqual(course_notes.assignment_block({"title": "HW 1"}, "2026-09-04"), (None, None))

    def test_a_note_for_a_missing_course_without_a_title_is_skipped(self) -> None:
        result = course_notes.load_notes([{"course_code": "BIO 110", "_file": "bio.json"}])
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(school.list_courses(), [])


if __name__ == "__main__":
    unittest.main()
