"""The Notes contract: a closed vocabulary, two validations, and one write.

No agent runs: a changeset is handed to the write-back directly. db.DB_PATH points
at a temp file, which covers school, school_notes and runner at once since they
resolve DB_PATH at call time.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "app" / "server"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import db  # noqa: E402
import fixtures  # noqa: E402
import runner  # noqa: E402
import school  # noqa: E402
import school_gcal  # noqa: E402
import school_notes  # noqa: E402
from school import SchoolError  # noqa: E402


def op(name: str, **fields: object) -> dict[str, object]:
    """One operation with a summary already on it, since every op needs one."""
    return {"op": name, "summary": f"summary for {name}", **fields}


def answer(ops: list[dict[str, object]], commentary: str = "matched one thing") -> str:
    """An agent reply in the shape the contract asks for: prose plus one block."""
    body = json.dumps({"ops": ops, "commentary": commentary})
    return f"Here is what I found.\n\n```json\n{body}\n```\n"


class SchoolNotesTestCase(unittest.TestCase):
    """A temporary semester: five invented courses, one assignment, one todo."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "semester.db"
        self.original_db_path = db.DB_PATH
        db.DB_PATH = self.db_path
        db.init_db(self.db_path)
        fixtures.seed_semester()

        self.course_id = next(
            course["id"] for course in school.list_courses() if course["code"] == "CS 101"
        )
        self.assignment = school.create_assignment(
            self.course_id, "HW 2", kind="hw", due_at="2026-09-09T23:59:00Z", points=20
        )
        self.todo = school.create_todo("Email the TA", course_id=self.course_id)

        # Default to "not connected", which the apply path must handle without failing.
        self.original_status = school_gcal.status
        self.original_push = school_gcal.push_changes
        self.original_armed = school_gcal.armed
        school_gcal.status = lambda: {"configured": False, "connected": False}
        school_gcal.push_changes = self._forbidden_push

    def tearDown(self) -> None:
        school_gcal.status = self.original_status
        school_gcal.push_changes = self.original_push
        school_gcal.armed = self.original_armed
        db.DB_PATH = self.original_db_path
        self.temp.cleanup()

    def _forbidden_push(self, assignment_ids=(), event_ids=()):  # noqa: ANN001 - test double
        raise AssertionError("push_changes was called while Google was not connected.")

    def proposed_note(self, ops: list[dict[str, object]], text: str = "a note") -> dict:
        """A note that has already come back from a run with this changeset."""
        note = school_notes.create_note(text)
        return school_notes.write_back(note["id"], answer(ops))

    def snapshot(self) -> dict[str, list]:
        """Everything a changeset could possibly write, as it stands right now."""
        with db.get_db(self.db_path) as conn:
            return {
                "assignments": [
                    dict(row) for row in conn.execute("SELECT * FROM assignments ORDER BY id")
                ],
                "todos": [
                    dict(row) for row in conn.execute("SELECT * FROM school_todos ORDER BY id")
                ],
            }


class VocabularyTests(SchoolNotesTestCase):
    """What validate_ops accepts, and what it refuses the whole changeset for."""

    def validate(self, ops: object) -> list[dict]:
        with db.get_db(self.db_path) as conn:
            return school_notes.validate_ops(conn, ops)

    def refusal(self, ops: object) -> SchoolError:
        with self.assertRaises(SchoolError) as raised:
            self.validate(ops)
        self.assertEqual(raised.exception.status_code, 422)
        return raised.exception

    def test_every_op_in_the_vocabulary_passes(self) -> None:
        clean = self.validate(
            [
                op(
                    "create_assignment",
                    course_id=self.course_id,
                    title="Midterm 1",
                    kind="exam",
                    due_at="2026-10-12T20:00:00Z",
                    points=100,
                    url="https://example.edu/midterm",
                    notes="KLR 214",
                ),
                op(
                    "update_assignment",
                    assignment_id=self.assignment["id"],
                    set={"due_at": "2026-09-11T23:59:00Z", "status": "submitted"},
                ),
                op("create_todo", title="Print the reference sheet", course_id=self.course_id),
                op("update_todo", todo_id=self.todo["id"], set={"done": True}),
                op("comment"),
            ]
        )
        self.assertEqual(
            [entry["op"] for entry in clean],
            [
                "create_assignment",
                "update_assignment",
                "create_todo",
                "update_todo",
                "comment",
            ],
        )
        # Optional keys the op did not name come back explicitly null rather
        # than absent, so the apply never has to guess what was meant.
        self.assertIsNone(clean[2]["assignment_id"])
        self.assertEqual(clean[0]["kind"], "exam")

    def test_an_unknown_op_is_refused(self) -> None:
        error = self.refusal([op("delete_assignment", assignment_id=self.assignment["id"])])
        self.assertIn("delete_assignment", error.detail)

    def test_an_unknown_key_is_refused(self) -> None:
        error = self.refusal(
            [op("create_todo", title="Read chapter 4", priority="high")]
        )
        self.assertIn("priority", error.detail)

    def test_an_unknown_set_key_is_refused(self) -> None:
        error = self.refusal(
            [op("update_assignment", assignment_id=self.assignment["id"], set={"weight_pct": 10})]
        )
        self.assertIn("weight_pct", error.detail)

    def test_a_missing_id_is_refused(self) -> None:
        error = self.refusal([op("update_assignment", set={"status": "submitted"})])
        self.assertIn("assignment_id", error.detail)

    def test_an_id_that_does_not_exist_is_refused(self) -> None:
        error = self.refusal([op("update_todo", todo_id=9999, set={"done": True})])
        self.assertIn("9999", error.detail)

    def test_a_bad_status_is_refused(self) -> None:
        error = self.refusal(
            [op("update_assignment", assignment_id=self.assignment["id"], set={"status": "done"})]
        )
        self.assertIn("done", error.detail)

    def test_a_bad_kind_is_refused(self) -> None:
        error = self.refusal(
            [op("create_assignment", course_id=self.course_id, title="Lab 1", kind="laboratory")]
        )
        self.assertIn("laboratory", error.detail)

    def test_a_malformed_due_date_is_refused(self) -> None:
        error = self.refusal(
            [op("update_assignment", assignment_id=self.assignment["id"], set={"due_at": "Friday"})]
        )
        self.assertIn("Friday", error.detail)

    def test_a_missing_summary_is_refused(self) -> None:
        error = self.refusal([{"op": "comment"}])
        self.assertIn("summary", error.detail)

    def test_an_empty_set_block_is_refused(self) -> None:
        error = self.refusal([op("update_assignment", assignment_id=self.assignment["id"], set={})])
        self.assertIn("empty", error.detail)

    def test_an_empty_changeset_is_refused(self) -> None:
        self.refusal([])

    def test_a_changeset_that_is_not_a_list_is_refused(self) -> None:
        self.refusal({"op": "comment", "summary": "one op, not a list"})

    def test_a_changeset_above_the_ceiling_is_refused(self) -> None:
        error = self.refusal([op("comment")] * (school_notes.MAX_OPS + 1))
        self.assertIn(str(school_notes.MAX_OPS), error.detail)

    def test_the_error_names_which_operation_failed(self) -> None:
        error = self.refusal([op("comment"), op("comment"), op("nonsense")])
        self.assertIn("Operation 3", error.detail)


class WriteBackTests(SchoolNotesTestCase):
    """What a finished run does to the note row, and to nothing else."""

    def test_a_valid_answer_becomes_a_proposal_and_writes_nothing_else(self) -> None:
        before = self.snapshot()
        note = self.proposed_note(
            [
                op(
                    "update_assignment",
                    assignment_id=self.assignment["id"],
                    set={"due_at": "2026-09-11T23:59:00Z"},
                )
            ]
        )

        self.assertEqual(note["status"], "proposed")
        self.assertEqual(len(note["proposal"]), 1)
        self.assertEqual(note["agent_md"], "matched one thing")
        self.assertIsNotNone(note["resolved_at"])
        self.assertIsNone(note["error"])
        self.assertIsNone(note["applied_changes"])
        self.assertEqual(self.snapshot(), before)

    def test_an_answer_with_no_json_block_fails_the_note_and_writes_nothing(self) -> None:
        before = self.snapshot()
        note = school_notes.create_note("the crypto hw2 moved to Friday")

        note = school_notes.write_back(note["id"], "I could not work out which homework that is.")

        self.assertEqual(note["status"], "failed")
        self.assertIsNone(note["proposal"])
        self.assertIn("no fenced json block", note["error"])
        self.assertEqual(self.snapshot(), before)

    def test_an_invalid_changeset_fails_the_note_and_leaves_the_database_untouched(self) -> None:
        before = self.snapshot()
        note = school_notes.create_note("mark everything done")

        note = school_notes.write_back(
            note["id"],
            answer([op("update_assignment", assignment_id=4242, set={"status": "graded"})]),
        )

        self.assertEqual(note["status"], "failed")
        self.assertIsNone(note["proposal"])
        self.assertIn("4242", note["error"])
        self.assertEqual(self.snapshot(), before)

    def test_a_run_that_returned_nothing_fails_the_note(self) -> None:
        note = school_notes.create_note("a note")

        note = school_notes.write_back(note["id"], "")

        self.assertEqual(note["status"], "failed")
        self.assertIn("no fenced json block", note["error"])

    def test_a_note_keeps_its_row_and_its_text_whatever_happens(self) -> None:
        note = school_notes.create_note("ya entregué el lab 3")
        school_notes.write_back(note["id"], "not json at all")

        stored = school_notes.get_note(note["id"])

        self.assertEqual(stored["text"], "ya entregué el lab 3")
        self.assertEqual(stored["status"], "failed")


class ApplyTests(SchoolNotesTestCase):
    """The one path that writes, end to end, from a proposal nobody generated."""

    def test_applying_writes_every_op_and_records_what_it_wrote(self) -> None:
        note = self.proposed_note(
            [
                op(
                    "create_assignment",
                    course_id=self.course_id,
                    title="Midterm 1",
                    kind="exam",
                    due_at="2026-10-12T20:00:00Z",
                    points=100,
                ),
                op(
                    "update_assignment",
                    assignment_id=self.assignment["id"],
                    set={"status": "submitted"},
                ),
                op("create_todo", title="Print the reference sheet", course_id=self.course_id),
                op("update_todo", todo_id=self.todo["id"], set={"done": True}),
                op("comment"),
            ]
        )

        applied = school_notes.apply_note(note["id"])

        self.assertEqual(applied["status"], "applied")
        self.assertIsNotNone(applied["applied_at"])
        self.assertIsNone(applied["error"])
        self.assertEqual(len(applied["applied_changes"]), 5)

        titles = {row["title"]: row for row in school.list_assignments()}
        self.assertIn("Midterm 1", titles)
        self.assertEqual(titles["Midterm 1"]["kind"], "exam")
        self.assertEqual(titles["Midterm 1"]["due_at"], "2026-10-12T20:00:00Z")
        self.assertEqual(titles["HW 2"]["status"], "submitted")

        todos = {row["title"]: row for row in school.list_todos()}
        self.assertIn("Print the reference sheet", todos)
        self.assertEqual(todos["Email the TA"]["done"], 1)

        # The sentences describe the rows, not the proposal: they carry the ids
        # the database actually allocated.
        joined = " ".join(applied["applied_changes"])
        self.assertIn(f"assignment {titles['Midterm 1']['id']}", joined)
        self.assertIn("Nothing to write.", joined)

    def test_a_comment_only_proposal_applies_and_changes_nothing(self) -> None:
        before = self.snapshot()
        note = self.proposed_note([op("comment")])

        applied = school_notes.apply_note(note["id"])

        self.assertEqual(applied["status"], "applied")
        self.assertEqual(self.snapshot(), before)
        self.assertIsNone(applied["gcal"])

    def test_applying_from_the_wrong_status_answers_409_and_writes_nothing(self) -> None:
        note = self.proposed_note(
            [op("update_assignment", assignment_id=self.assignment["id"], set={"status": "graded"})]
        )
        school_notes.apply_note(note["id"])
        before = self.snapshot()

        with self.assertRaises(SchoolError) as raised:
            school_notes.apply_note(note["id"])

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.snapshot(), before)

    def test_applying_a_running_note_answers_409(self) -> None:
        note = school_notes.create_note("still running")

        with self.assertRaises(SchoolError) as raised:
            school_notes.apply_note(note["id"])

        self.assertEqual(raised.exception.status_code, 409)

    def test_the_changeset_is_validated_again_against_the_state_at_apply_time(self) -> None:
        """A proposal that no longer fits the database is refused, not forced.

        Deleting the row by hand stands in for the semester changing between proposal and apply.
        """
        note = self.proposed_note(
            [op("update_assignment", assignment_id=self.assignment["id"], set={"status": "graded"})]
        )
        with db.get_db(self.db_path) as conn:
            conn.execute("DELETE FROM assignments WHERE id = ?", (self.assignment["id"],))
        before = self.snapshot()

        with self.assertRaises(SchoolError) as raised:
            school_notes.apply_note(note["id"])

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(self.snapshot(), before)
        # Still proposed, so the user can read the reason and try again.
        self.assertEqual(school_notes.get_note(note["id"])["status"], "proposed")

    def test_a_deadline_with_google_disconnected_is_written_and_reported(self) -> None:
        note = self.proposed_note(
            [
                op(
                    "update_assignment",
                    assignment_id=self.assignment["id"],
                    set={"due_at": "2026-09-11T23:59:00Z"},
                )
            ]
        )

        applied = school_notes.apply_note(note["id"])

        self.assertEqual(
            school.get_assignment(self.assignment["id"])["due_at"], "2026-09-11T23:59:00Z"
        )
        self.assertEqual(applied["gcal"]["attempted"], False)
        self.assertIsNone(applied["gcal"]["ok"])
        self.assertIn("not connected", applied["gcal"]["detail"])

    def test_a_google_failure_never_fails_the_apply(self) -> None:
        def explode(assignment_ids=(), event_ids=()):  # noqa: ANN001 - test double
            raise RuntimeError("Google said no")

        school_gcal.status = lambda: {"configured": True, "connected": True}
        school_gcal.armed = lambda: True
        school_gcal.push_changes = explode

        note = self.proposed_note(
            [
                op(
                    "update_assignment",
                    assignment_id=self.assignment["id"],
                    set={"due_at": "2026-09-11T23:59:00Z"},
                )
            ]
        )
        applied = school_notes.apply_note(note["id"])

        self.assertEqual(applied["status"], "applied")
        self.assertEqual(
            school.get_assignment(self.assignment["id"])["due_at"], "2026-09-11T23:59:00Z"
        )
        self.assertEqual(applied["gcal"], {"attempted": True, "ok": False, "detail": "Google said no"})

    def test_a_connected_google_receives_only_the_dated_assignments(self) -> None:
        seen: list[tuple[list[int], list[int]]] = []

        school_gcal.status = lambda: {"configured": True, "connected": True}
        school_gcal.armed = lambda: True
        school_gcal.push_changes = lambda assignment_ids=(), event_ids=(): (
            seen.append((list(assignment_ids), list(event_ids)))
            or {"deadlines": {"created": 1, "updated": 0, "unchanged": 0, "removed": 0}}
        )

        note = self.proposed_note(
            [
                op("create_assignment", course_id=self.course_id, title="Reading 1"),
                op(
                    "create_assignment",
                    course_id=self.course_id,
                    title="Midterm 1",
                    due_at="2026-10-12T20:00:00Z",
                ),
                op("create_todo", title="Buy a blue book"),
            ]
        )
        applied = school_notes.apply_note(note["id"])

        self.assertEqual(len(seen), 1)
        midterm = next(row for row in school.list_assignments() if row["title"] == "Midterm 1")
        self.assertEqual(seen[0], ([midterm["id"]], []))
        self.assertEqual(applied["gcal"]["ok"], True)
        self.assertIn("1 created", applied["gcal"]["detail"])


class AppliedSentenceTests(SchoolNotesTestCase):
    """`applied_changes` sentences use campus time, 12-hour, no ISO.

    Instants are fixed in UTC and expectations computed in the configured zone,
    so the tests hold on any machine.
    """

    # Sep 16, 2026 is a Wednesday; the year is appended only outside 2026.
    day = "Wed Sep 16" if datetime.now().year == 2026 else "Wed Sep 16, 2026"

    ISO_INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")

    @staticmethod
    def campus(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(school.LOCAL_TZ)

    @staticmethod
    def clock(moment: datetime) -> str:
        return f"{moment.hour % 12 or 12}:{moment.minute:02d}{'p' if moment.hour >= 12 else 'a'}"

    def applied(self, ops: list[dict[str, object]]) -> list[str]:
        return school_notes.apply_note(self.proposed_note(ops)["id"])["applied_changes"]

    def test_event_times_are_campus_wall_time_not_utc(self) -> None:
        start, end = "2026-09-16T22:00:00Z", "2026-09-16T23:30:00Z"
        (line,) = self.applied(
            [op("create_event", title="Review session", start_at=start, end_at=end, location="KLR 214")]
        )
        self.assertIsNone(self.ISO_INSTANT.search(line), line)
        self.assertNotIn("Z ", line)
        first, last = self.campus(start), self.campus(end)
        self.assertIn(f"{first.strftime('%a %b')} {first.day}", line)
        self.assertIn(self.clock(last), line)
        self.assertIn(" in KLR 214.", line)
        self.assertNotIn("\u2013", line)
        self.assertNotIn("\u2014", line)

    def test_a_same_day_range_drops_the_shared_meridiem(self) -> None:
        self.assertEqual(
            school_notes._human_span(  # noqa: SLF001 - the formatter is the contract here
                datetime(2026, 9, 16, 18, 0, tzinfo=school.LOCAL_TZ).isoformat(),
                datetime(2026, 9, 16, 19, 30, tzinfo=school.LOCAL_TZ).isoformat(),
            ),
            f"{self.day}, 6:00-7:30p",
        )
        self.assertEqual(
            school_notes._human_span(  # noqa: SLF001
                datetime(2026, 9, 16, 11, 30, tzinfo=school.LOCAL_TZ).isoformat(),
                datetime(2026, 9, 16, 13, 20, tzinfo=school.LOCAL_TZ).isoformat(),
            ),
            f"{self.day}, 11:30a-1:20p",
        )

    def test_a_bare_date_and_an_unparseable_value_are_kept_readable(self) -> None:
        self.assertEqual(school_notes._human_stamp("2026-09-16"), self.day)  # noqa: SLF001
        self.assertEqual(school_notes._human_stamp("whenever"), "whenever")  # noqa: SLF001
        self.assertEqual(school_notes._human_stamp(None), "")  # noqa: SLF001

    def test_an_updated_deadline_reads_as_words_not_key_value_pairs(self) -> None:
        due = "2026-09-24T23:00:00Z"
        (line,) = self.applied(
            [op("update_assignment", assignment_id=self.assignment["id"], set={"due_at": due, "location": None})]
        )
        self.assertIsNone(self.ISO_INSTANT.search(line), line)
        self.assertNotIn("=", line)
        self.assertIn(f"due {self.campus(due).strftime('%a %b')}", line)
        self.assertIn(self.clock(self.campus(due)), line)
        self.assertIn("no location", line)

    def test_a_todo_marked_done_says_done(self) -> None:
        (line,) = self.applied([op("update_todo", todo_id=self.todo["id"], set={"done": True})])
        self.assertTrue(line.endswith(": done."), line)


class DiscardTests(SchoolNotesTestCase):
    def test_discarding_keeps_the_row_and_the_proposal(self) -> None:
        before = self.snapshot()
        note = self.proposed_note(
            [op("update_assignment", assignment_id=self.assignment["id"], set={"status": "graded"})]
        )

        discarded = school_notes.discard_note(note["id"])

        self.assertEqual(discarded["status"], "discarded")
        self.assertEqual(len(discarded["proposal"]), 1)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(school_notes.list_notes()), 1)

    def test_discarding_from_the_wrong_status_answers_409(self) -> None:
        note = school_notes.create_note("still running")

        with self.assertRaises(SchoolError) as raised:
            school_notes.discard_note(note["id"])

        self.assertEqual(raised.exception.status_code, 409)

    def test_a_discarded_note_cannot_then_be_applied(self) -> None:
        note = self.proposed_note([op("comment")])
        school_notes.discard_note(note["id"])

        with self.assertRaises(SchoolError) as raised:
            school_notes.apply_note(note["id"])

        self.assertEqual(raised.exception.status_code, 409)


class RunnerIntegrationTests(SchoolNotesTestCase):
    """A school note flows through the action machinery."""

    def test_a_school_note_action_is_created_pending_with_its_payload(self) -> None:
        note = school_notes.create_note("the crypto hw2 moved to Friday")

        action_id = runner.create_action("school_note", {"note_id": note["id"]})
        attached = school_notes.attach_action(note["id"], action_id)

        with db.get_db(self.db_path) as conn:
            row = conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
        self.assertEqual(row["status"], "pending")
        self.assertEqual(json.loads(row["payload"]), {"note_id": note["id"]})
        self.assertEqual(row["type"], "school_note")
        self.assertEqual(attached["action_id"], action_id)

    def test_the_prompt_carries_the_note_and_every_id_the_agent_may_name(self) -> None:
        note = school_notes.create_note("the crypto hw2 moved to Friday")

        prompt = runner.build_prompt("school_note", {"note_id": note["id"]})

        self.assertIn("the crypto hw2 moved to Friday", prompt)
        self.assertIn(db.LOCAL_TZ_NAME, prompt)
        self.assertIn("CS 101", prompt)
        self.assertIn(f"{self.assignment['id']} | CS 101 | HW 2", prompt)
        self.assertIn(f"{self.todo['id']} | Email the TA", prompt)

    def test_a_prompt_for_a_note_that_is_gone_is_refused_rather_than_invented(self) -> None:
        with self.assertRaises(ValueError):
            runner.build_prompt("school_note", {"note_id": 9999})

    def test_the_write_back_turns_a_finished_action_into_a_proposal(self) -> None:
        note = school_notes.create_note("the crypto hw2 moved to Friday")
        action_id = runner.create_action("school_note", {"note_id": note["id"]})
        school_notes.attach_action(note["id"], action_id)
        result = answer(
            [
                op(
                    "update_assignment",
                    assignment_id=self.assignment["id"],
                    set={"due_at": "2026-09-11T23:59:00Z"},
                )
            ]
        )
        with db.get_db(self.db_path) as conn:
            conn.execute(
                "UPDATE actions SET status = 'done', result_md = ? WHERE id = ?",
                (result, action_id),
            )

        runner._write_back(action_id)

        stored = school_notes.get_note(note["id"])
        self.assertEqual(stored["status"], "proposed")
        self.assertEqual(len(stored["proposal"]), 1)
        # Still only a proposal: the write-back never applies anything.
        self.assertEqual(
            school.get_assignment(self.assignment["id"])["due_at"], "2026-09-09T23:59:00Z"
        )


class ReconcileTests(SchoolNotesTestCase):
    """A run that ended without a write-back must not leave a note spinning."""

    def test_a_failed_action_fails_its_note_with_the_reason(self) -> None:
        note = school_notes.create_note("a note")
        action_id = runner.create_action("school_note", {"note_id": note["id"]})
        school_notes.attach_action(note["id"], action_id)
        with db.get_db(self.db_path) as conn:
            conn.execute(
                "UPDATE actions SET status = 'failed', error = ? WHERE id = ?",
                ("The agent run exceeded 600 seconds and was stopped.", action_id),
            )

        stored = school_notes.get_note(note["id"])

        self.assertEqual(stored["status"], "failed")
        self.assertIn("600 seconds", stored["error"])

    def test_a_running_action_leaves_its_note_alone(self) -> None:
        note = school_notes.create_note("a note")
        action_id = runner.create_action("school_note", {"note_id": note["id"]})
        school_notes.attach_action(note["id"], action_id)

        self.assertEqual(school_notes.get_note(note["id"])["status"], "running")

    def test_reconciling_never_touches_a_note_that_already_resolved(self) -> None:
        note = self.proposed_note([op("comment")])
        with db.get_db(self.db_path) as conn:
            conn.execute("UPDATE school_notes SET action_id = NULL WHERE id = ?", (note["id"],))

        school_notes.reconcile()

        self.assertEqual(school_notes.get_note(note["id"])["status"], "proposed")


class EndpointTests(SchoolNotesTestCase):
    """The four routes, called directly. No agent is ever started."""

    def setUp(self) -> None:
        super().setUp()
        import app as server_app

        self.server_app = server_app
        self.submitted: list[int] = []
        self.original_submit = runner.submit
        self.original_cli_available = runner.claude_cli_available
        runner.submit = self.submitted.append
        runner.claude_cli_available = lambda: True

    def tearDown(self) -> None:
        runner.submit = self.original_submit
        runner.claude_cli_available = self.original_cli_available
        super().tearDown()

    def test_creating_a_note_stores_it_attaches_a_run_and_submits_it(self) -> None:
        note = self.server_app.create_school_note(
            self.server_app.NoteCreate(text="add OS midterm Oct 12 8pm in KLR 214")
        )

        self.assertEqual(note["status"], "running")
        self.assertIsNotNone(note["action_id"])
        self.assertIsNone(note["proposal"])
        # Attached before submitted: the run can never start against a row that
        # does not yet know which run is reading it.
        self.assertEqual(self.submitted, [note["action_id"]])

    def test_an_empty_note_is_refused_before_any_row_exists(self) -> None:
        with self.assertRaises(SchoolError) as raised:
            self.server_app.create_school_note(self.server_app.NoteCreate(text="   "))

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(school_notes.list_notes(), [])
        self.assertEqual(self.submitted, [])

    def test_the_listing_is_newest_first(self) -> None:
        first = self.server_app.create_school_note(self.server_app.NoteCreate(text="one"))
        second = self.server_app.create_school_note(self.server_app.NoteCreate(text="two"))

        listing = self.server_app.school_notes_list()["notes"]

        self.assertEqual([note["id"] for note in listing], [second["id"], first["id"]])

    def test_the_note_shape_is_exactly_the_contract(self) -> None:
        note = self.server_app.create_school_note(self.server_app.NoteCreate(text="one"))

        self.assertEqual(
            sorted(note),
            sorted(
                [
                    "id",
                    "text",
                    "status",
                    "action_id",
                    "proposal",
                    "agent_md",
                    "applied_changes",
                    "gcal",
                    "error",
                    "created_at",
                    "resolved_at",
                    "applied_at",
                ]
            ),
        )

    def test_apply_and_discard_go_through_the_routes(self) -> None:
        note = self.proposed_note([op("create_todo", title="Buy a blue book")])

        applied = self.server_app.apply_school_note(note["id"])
        self.assertEqual(applied["status"], "applied")

        other = self.proposed_note([op("comment")])
        discarded = self.server_app.discard_school_note(other["id"])
        self.assertEqual(discarded["status"], "discarded")

        fetched = self.server_app.school_note(note["id"])
        self.assertEqual(fetched["id"], note["id"])

    def test_without_the_claude_cli_a_note_is_refused_with_how_to_install_it(self) -> None:
        from fastapi import HTTPException

        runner.claude_cli_available = lambda: False
        with self.assertRaises(HTTPException) as raised:
            self.server_app.create_school_note(self.server_app.NoteCreate(text="hw2 moved"))

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("Claude Code CLI", raised.exception.detail)
        # Nothing was written: no note to fail later, no run to start.
        self.assertEqual(school_notes.list_notes(), [])
        self.assertEqual(self.submitted, [])

    def test_a_run_without_the_cli_fails_its_note_with_the_install_hint(self) -> None:
        note = school_notes.create_note("hw2 moved")
        action_id = runner.create_action("school_note", {"note_id": note["id"]})
        school_notes.attach_action(note["id"], action_id)
        original_binary = runner.claude_binary
        runner.claude_binary = lambda: None
        try:
            runner._execute(action_id)
        finally:
            runner.claude_binary = original_binary

        stored = school_notes.get_note(note["id"])
        self.assertEqual(stored["status"], "failed")
        self.assertEqual(stored["error"], runner.CLI_MISSING_ERROR)


if __name__ == "__main__":
    unittest.main()
