"""Google Calendar projection onto primary, and the notes that feed it.

school_gcal._request is replaced by FakeGoogle, an in-memory primary calendar
that records every call, so tests can assert a dry run or a person's own event
was never written. The database is a temporary file.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "app" / "server"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import db  # noqa: E402
import fixtures  # noqa: E402
import school  # noqa: E402
import school_gcal  # noqa: E402
import school_ics  # noqa: E402
import school_notes  # noqa: E402
from school import SchoolError  # noqa: E402

CAMPUS = ZoneInfo(db.LOCAL_TZ_NAME)


def utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def op(name: str, **fields: object) -> dict[str, object]:
    return {"op": name, "summary": f"summary for {name}", **fields}


def answer(ops: list[dict[str, object]]) -> str:
    return "```json\n" + json.dumps({"ops": ops, "commentary": "ok"}) + "\n```\n"


def tagged(key: str, kind: str, event_id: str, summary: str = "ours", **extra: object) -> dict:
    return {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": "2026-09-20T15:00:00Z"},
        "end": {"dateTime": "2026-09-20T16:00:00Z"},
        "extendedProperties": {
            "private": {school_gcal.PROPERTY_KEY: key, school_gcal.KIND_PROPERTY: kind}
        },
        **extra,
    }


class FakeGoogle:
    """An in-memory primary calendar speaking the subset of the API we use."""

    def __init__(self) -> None:
        self.events: dict[str, dict] = {}
        self.instances: list[dict] = []
        self.calls: list[tuple[str, str, dict | None]] = []
        self._next = 1

    def add(self, event: dict) -> dict:
        self.events[event["id"]] = event
        return event

    @property
    def writes(self) -> list[tuple[str, str, dict | None]]:
        return [call for call in self.calls if call[0] != "GET"]

    def __call__(self, method, url, *, token=None, params=None, json_body=None, form=None):  # noqa: ANN001
        method = method.upper()
        self.calls.append((method, url, json_body))
        path = urllib.parse.urlsplit(url).path
        assert "/calendars/primary/events" in path, f"unexpected calendar in {url}"
        tail = path.split("/calendars/primary/events", 1)[1].strip("/")
        event_id = urllib.parse.unquote(tail) if tail else None

        if method == "GET" and event_id is None:
            params = params or {}
            if params.get("singleEvents") == "true":
                return 200, {"items": list(self.instances)}
            wanted = params.get("privateExtendedProperty")
            items = []
            for event in self.events.values():
                private = (event.get("extendedProperties") or {}).get("private") or {}
                if wanted:
                    name, value = wanted.split("=", 1)
                    if private.get(name) != value:
                        continue
                items.append(event)
            return 200, {"items": items}
        if method == "POST" and event_id is None:
            created = dict(json_body)
            created["id"] = f"g{self._next}"
            self._next += 1
            self.events[created["id"]] = created
            return 200, created
        if method == "PATCH" and event_id in self.events:
            self.events[event_id].update(json_body)
            return 200, self.events[event_id]
        if method == "DELETE":
            if self.events.pop(event_id, None) is None:
                return 404, None
            return 204, None
        raise AssertionError(f"FakeGoogle does not handle {method} {url}")


class PrimaryTestCase(unittest.TestCase):
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

        self.now = datetime.now(CAMPUS).replace(second=0, microsecond=0)
        self.google = FakeGoogle()
        self.saved = {
            name: getattr(school_gcal, name)
            for name in ("_request", "_access_token", "status", "_state_set")
        }
        school_gcal._request = self.google
        school_gcal._access_token = lambda force_refresh=False: "test-token"
        school_gcal.status = lambda: {"configured": True, "connected": False}

    def tearDown(self) -> None:
        for name, value in self.saved.items():
            setattr(school_gcal, name, value)
        db.DB_PATH = self.original_db_path
        self.temp.cleanup()

    def connect(self) -> None:
        school_gcal.status = lambda: {"configured": True, "connected": True}
        school_gcal._state_set(school_gcal.ARMED_STATE_KEY, "2026-09-13T00:00:00Z")

    def at(self, days: int, hour: int = 20, minute: int = 0) -> datetime:
        return (self.now + timedelta(days=days)).replace(hour=hour, minute=minute)

    def validate(self, ops: list) -> list[dict]:
        with db.get_db(self.db_path) as conn:
            return school_notes.validate_ops(conn, ops)

    def refusal(self, ops: list) -> SchoolError:
        with self.assertRaises(SchoolError) as raised:
            self.validate(ops)
        self.assertEqual(raised.exception.status_code, 422)
        return raised.exception

    def apply(self, ops: list) -> dict:
        note = school_notes.create_note("a note")
        proposed = school_notes.write_back(note["id"], answer(ops))
        self.assertEqual(proposed["status"], "proposed", proposed.get("error"))
        return school_notes.apply_note(note["id"])

    def owned(self, prefix: str) -> dict[str, dict]:
        out = {}
        for event in self.google.events.values():
            key = ((event.get("extendedProperties") or {}).get("private") or {}).get("semesteros")
            if key and key.startswith(prefix):
                out[key] = event
        return out


class EventVocabularyTests(PrimaryTestCase):
    def test_the_new_ops_pass(self) -> None:
        event = school.create_event("Advisor", utc(self.at(3, 15)))
        clean = self.validate(
            [
                op(
                    "create_event",
                    title="Office hours",
                    start_at=utc(self.at(2, 15)),
                    end_at=utc(self.at(2, 16)),
                    location="Room 314",
                    course_id=self.course_id,
                    notes=None,
                ),
                op("create_event", title="Career fair", start_at="2026-10-01"),
                op("update_event", event_id=event["id"], set={"location": "Zoom"}),
                op("cancel_event", event_id=event["id"]),
                op(
                    "create_assignment",
                    course_id=self.course_id,
                    title="Midterm",
                    kind="exam",
                    due_at=utc(self.at(10, 20)),
                    ends_at=utc(self.at(10, 22)),
                    location="KLR 214",
                ),
            ]
        )
        self.assertEqual(clean[0]["all_day"], False)
        # A bare date with no all_day stated is an all day event, not a refusal.
        self.assertEqual(clean[1]["all_day"], True)
        self.assertEqual(clean[4]["ends_at"], utc(self.at(10, 22)))
        self.assertEqual(clean[4]["location"], "KLR 214")

    def test_an_end_before_the_start_is_refused(self) -> None:
        error = self.refusal(
            [op("create_event", title="x", start_at=utc(self.at(2, 15)), end_at=utc(self.at(2, 14)))]
        )
        self.assertIn("after", error.detail)

    def test_a_bare_date_that_says_it_is_timed_is_refused(self) -> None:
        self.refusal([op("create_event", title="x", start_at="2026-10-01", all_day=False)])

    def test_an_instant_that_says_it_is_all_day_is_refused(self) -> None:
        self.refusal([op("create_event", title="x", start_at=utc(self.at(1)), all_day=True)])

    def test_all_day_must_be_a_boolean(self) -> None:
        self.refusal([op("create_event", title="x", start_at="2026-10-01", all_day="yes")])

    def test_an_unknown_event_key_is_refused(self) -> None:
        error = self.refusal(
            [op("create_event", title="x", start_at="2026-10-01", color="red")]
        )
        self.assertIn("color", error.detail)

    def test_a_missing_start_is_refused(self) -> None:
        error = self.refusal([op("create_event", title="x")])
        self.assertIn("start_at", error.detail)

    def test_an_unknown_course_is_refused(self) -> None:
        self.refusal([op("create_event", title="x", start_at="2026-10-01", course_id=999)])

    def test_update_event_refuses_unknown_set_keys_and_unknown_ids(self) -> None:
        event = school.create_event("Advisor", utc(self.at(3, 15)))
        self.assertIn(
            "status",
            self.refusal(
                [op("update_event", event_id=event["id"], set={"status": "cancelled"})]
            ).detail,
        )
        self.assertIn("4242", self.refusal([op("update_event", event_id=4242, set={"title": "y"})]).detail)

    def test_update_event_refuses_an_end_before_the_start(self) -> None:
        event = school.create_event("Advisor", utc(self.at(3, 15)), end_at=utc(self.at(3, 16)))
        self.refusal(
            [op("update_event", event_id=event["id"], set={"end_at": utc(self.at(3, 14))})]
        )

    def test_a_cancelled_event_cannot_be_updated_or_cancelled_again(self) -> None:
        event = school.create_event("Advisor", utc(self.at(3, 15)))
        school.cancel_event(event["id"])
        self.refusal([op("update_event", event_id=event["id"], set={"title": "y"})])
        self.refusal([op("cancel_event", event_id=event["id"])])

    def test_ends_at_needs_a_timed_due_at_after_which_it_falls(self) -> None:
        self.assertIn(
            "clock time",
            self.refusal(
                [
                    op(
                        "create_assignment",
                        course_id=self.course_id,
                        title="Final",
                        due_at="2026-12-10",
                        ends_at="2026-12-10T22:00:00Z",
                    )
                ]
            ).detail,
        )
        self.refusal(
            [
                op(
                    "create_assignment",
                    course_id=self.course_id,
                    title="Final",
                    due_at=utc(self.at(10, 20)),
                    ends_at=utc(self.at(10, 19)),
                )
            ]
        )
        exam = school.create_assignment(
            self.course_id, "Quiz", kind="quiz", due_at=utc(self.at(5, 10))
        )
        self.refusal(
            [op("update_assignment", assignment_id=exam["id"], set={"ends_at": utc(self.at(5, 9))})]
        )
        self.refusal(
            [op("update_assignment", assignment_id=exam["id"], set={"ends_at": "2026-12-10"})]
        )


class ApplyEventTests(PrimaryTestCase):
    def test_create_move_and_cancel_an_event(self) -> None:
        applied = self.apply(
            [
                op(
                    "create_event",
                    title="Office hours",
                    start_at=utc(self.at(2, 15)),
                    end_at=utc(self.at(2, 16)),
                    location="Room 314",
                    course_id=self.course_id,
                )
            ]
        )
        self.assertEqual(applied["status"], "applied")
        self.assertIn("Created event", applied["applied_changes"][0])
        self.assertEqual(applied["gcal"]["attempted"], False)
        self.assertIn("next sync", applied["gcal"]["detail"])

        (event,) = school.list_events()
        self.assertEqual(event["origin"], "note")
        self.assertEqual(event["note_id"], applied["id"])
        self.assertEqual(event["course_code"], "CS 101")

        # Moving the start without naming the end keeps the hour.
        moved = self.apply(
            [op("update_event", event_id=event["id"], set={"start_at": utc(self.at(2, 17))})]
        )
        # The sentence reports the end that moved with the start, in campus time.
        self.assertIn("5:00-6:00p", moved["applied_changes"][0])
        self.assertNotIn("end_at=", moved["applied_changes"][0])
        stored = school.get_event(event["id"])
        self.assertEqual(stored["start_at"], utc(self.at(2, 17)))
        self.assertEqual(stored["end_at"], utc(self.at(2, 18)))

        cancelled = self.apply([op("cancel_event", event_id=event["id"])])
        self.assertIn("Cancelled event", cancelled["applied_changes"][0])
        stored = school.get_event(event["id"])
        self.assertEqual(stored["status"], "cancelled")
        self.assertIsNotNone(stored["cancelled_at"])
        # Never deleted: still there when cancelled rows are asked for.
        self.assertEqual(len(school.list_events(include_cancelled=True)), 1)
        self.assertEqual(school.list_events(), [])

    def test_assignment_ends_at_and_location_are_written_and_follow_a_moved_due_at(self) -> None:
        applied = self.apply(
            [
                op(
                    "create_assignment",
                    course_id=self.course_id,
                    title="Midterm 1",
                    kind="exam",
                    due_at=utc(self.at(10, 20)),
                    ends_at=utc(self.at(10, 22)),
                    location="KLR 214",
                )
            ]
        )
        midterm = next(row for row in school.list_assignments() if row["title"] == "Midterm 1")
        self.assertEqual(midterm["ends_at"], utc(self.at(10, 22)))
        self.assertEqual(midterm["location"], "KLR 214")
        self.assertIn("KLR 214", applied["applied_changes"][0])

        self.apply(
            [op("update_assignment", assignment_id=midterm["id"], set={"due_at": utc(self.at(11, 19))})]
        )
        moved = school.get_assignment(midterm["id"])
        self.assertEqual(moved["ends_at"], utc(self.at(11, 21)))

        self.apply(
            [op("update_assignment", assignment_id=midterm["id"], set={"location": "SRL 104"})]
        )
        self.assertEqual(school.get_assignment(midterm["id"])["location"], "SRL 104")

    def test_the_state_context_lists_scheduled_events_in_campus_time(self) -> None:
        kept = school.create_event("Advisor meeting", utc(self.at(3, 15)), location="Room 202")
        gone = school.create_event("Cancelled talk", utc(self.at(4, 15)))
        school.cancel_event(gone["id"])
        old = school.create_event("Last month", utc(self.at(-30, 15)))

        context = school_notes.state_context()

        self.assertIn("SCHEDULED EVENTS", context)
        self.assertIn(
            f"{kept['id']} | Advisor meeting | - | {self.at(3, 15).strftime('%Y-%m-%d %H:%M')}",
            context,
        )
        self.assertIn("Room 202", context)
        self.assertNotIn("Cancelled talk", context)
        self.assertNotIn(f"{old['id']} | Last month", context)

    def test_a_connected_apply_pushes_events_and_a_cancel_removes_them(self) -> None:
        self.connect()
        applied = self.apply(
            [op("create_event", title="Study group", start_at=utc(self.at(2, 18)))]
        )
        self.assertEqual(applied["gcal"]["ok"], True, applied["gcal"])
        (event,) = school.list_events()
        owned = self.owned("event:")
        self.assertEqual(list(owned), [f"event:{event['id']}"])
        body = owned[f"event:{event['id']}"]
        self.assertEqual(body["colorId"], school_gcal.COLOR_EVENT)
        # No end stated: projected as an hour.
        self.assertEqual(body["end"]["dateTime"], utc(self.at(2, 19)))

        self.apply([op("cancel_event", event_id=event["id"])])
        self.assertEqual(self.owned("event:"), {})


class ReconciliationTests(PrimaryTestCase):
    def seed_calendar(self) -> None:
        self.google.add(
            {
                "id": "personal",
                "summary": "Dentist",
                "start": {"dateTime": "2026-09-20T15:00:00Z"},
                "end": {"dateTime": "2026-09-20T16:00:00Z"},
            }
        )
        self.google.add(tagged("class:10001:lecture", "class", "class-evt"))
        self.google.add(tagged("event:99", "event", "event-evt"))

    def test_deadlines_only_touch_assignment_keys_and_never_untagged_events(self) -> None:
        self.seed_calendar()
        hw = school.create_assignment(self.course_id, "HW 2", kind="hw", due_at=utc(self.at(2, 23, 59)))
        exam = school.create_assignment(
            self.course_id,
            "Midterm",
            kind="exam",
            due_at=utc(self.at(10, 20)),
            ends_at=utc(self.at(10, 22)),
            location="KLR 214",
        )
        done = school.create_assignment(self.course_id, "HW 1", kind="hw", due_at=self.at(-3).date().isoformat())
        school.update_assignment(done["id"], status="submitted", status_given=True)
        dropped = school.create_assignment(self.course_id, "Old HW", due_at=utc(self.at(4)))
        school.update_assignment(dropped["id"], status="dropped", status_given=True)
        far = school.create_assignment(self.course_id, "Next year", due_at=utc(self.at(400)))
        undated = school.create_assignment(self.course_id, "Reading")

        # A dropped assignment's stale event, twice (a duplicate), plus an
        # untagged-kind event that claims an assignment key but not our kind.
        self.google.add(tagged(f"assignment:{dropped['id']}", "assignment", "stale-1"))
        self.google.add(tagged(f"assignment:{dropped['id']}", "assignment", "stale-2"))
        self.google.add(tagged(f"assignment:{hw['id']}", "assignment", "hw-1", summary="old name"))
        self.google.add(tagged(f"assignment:{hw['id']}", "assignment", "hw-dup", summary="old name"))
        # History: an owned event for work that qualifies but is out of window.
        self.google.add(tagged(f"assignment:{far['id']}", "assignment", "far-evt"))

        result = school_gcal.sync(["deadlines"])["deadlines"]

        self.assertTrue(result["ok"], result)
        self.assertIn("personal", self.google.events)
        self.assertIn("class-evt", self.google.events)
        self.assertIn("event-evt", self.google.events)
        self.assertIn("far-evt", self.google.events)
        self.assertNotIn("stale-1", self.google.events)
        self.assertNotIn("stale-2", self.google.events)
        self.assertNotIn("hw-dup", self.google.events)

        owned = self.owned("assignment:")
        self.assertEqual(
            set(owned),
            {
                f"assignment:{hw['id']}",
                f"assignment:{exam['id']}",
                f"assignment:{done['id']}",
                f"assignment:{far['id']}",
            },
        )
        self.assertNotIn(f"assignment:{undated['id']}", owned)
        self.assertEqual(owned[f"assignment:{hw['id']}"]["summary"], "CS 101 · HW 2")
        self.assertEqual(owned[f"assignment:{hw['id']}"]["colorId"], school_gcal.COLOR_DEADLINE)
        exam_event = owned[f"assignment:{exam['id']}"]
        self.assertEqual(exam_event["colorId"], school_gcal.COLOR_EXAM)
        self.assertEqual(exam_event["location"], "KLR 214")
        self.assertEqual(exam_event["start"]["dateTime"], utc(self.at(10, 20)))
        self.assertEqual(exam_event["end"]["dateTime"], utc(self.at(10, 22)))
        done_event = owned[f"assignment:{done['id']}"]
        self.assertTrue(done_event["summary"].startswith("✓ "))
        self.assertIn("date", done_event["start"])

        for method, url, _ in self.google.writes:
            if method in ("PATCH", "DELETE"):
                self.assertNotIn("personal", url)
                self.assertNotIn("class-evt", url)
                self.assertNotIn("event-evt", url)

    def test_a_naive_due_time_is_campus_time_on_the_calendar(self) -> None:
        local = self.at(3, 17)
        work = school.create_assignment(
            self.course_id, "Lab", due_at=local.strftime("%Y-%m-%dT%H:%M")
        )
        school_gcal.sync(["deadlines"])
        event = self.owned("assignment:")[f"assignment:{work['id']}"]
        self.assertEqual(event["end"]["dateTime"], utc(local))

    def test_classes_and_events_never_delete_other_prefixes(self) -> None:
        self.seed_calendar()
        self.google.add(tagged("assignment:1", "assignment", "assignment-evt"))
        school.create_event("Talk", utc(self.at(5, 16)))

        results = school_gcal.sync(["classes", "events"])

        self.assertTrue(results["classes"]["ok"], results)
        self.assertTrue(results["events"]["ok"], results)
        self.assertIn("personal", self.google.events)
        self.assertIn("assignment-evt", self.google.events)
        # The class key the seed does not produce is stale inside its own prefix
        # (the seeded lecture 10001 is, so it stays); event:99 has no row.
        self.assertIn("class-evt", self.google.events)
        self.assertNotIn("event-evt", self.google.events)
        classes = self.owned("class:")
        self.assertIn("class:10001:lecture", classes)
        self.assertEqual(classes["class:10004:pso"]["colorId"], school_gcal.COLOR_CLASS)
        self.assertTrue(all("recurrence" in body for body in classes.values()))

    def test_a_dry_run_writes_nothing_and_predicts_the_real_run(self) -> None:
        self.seed_calendar()
        school.create_assignment(self.course_id, "HW 2", due_at=utc(self.at(2, 23, 59)))
        school.create_event("Talk", utc(self.at(5, 16)))
        state_writes: list[tuple] = []
        school_gcal._state_set = lambda key, value: state_writes.append((key, value))

        planned = school_gcal.sync(list(school_gcal.SYNC_TARGETS), dry_run=True)

        self.assertEqual(self.google.writes, [])
        self.assertEqual(state_writes, [])
        with db.get_db(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM external_events").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM ics_sync_state").fetchone()[0], 0)
        for name in ("classes", "deadlines", "events", "pull"):
            self.assertTrue(planned[name]["ok"], planned[name])
            self.assertTrue(planned[name]["dry_run"])
        self.assertEqual(planned["events"]["removed"], 1)
        self.assertEqual(planned["deadlines"]["created"], 1)
        actions = planned["classes"]["actions"] + planned["deadlines"]["actions"] + planned["events"]["actions"]
        self.assertTrue(all(set(entry) == {"action", "key", "summary"} for entry in actions))
        self.assertIn({"action": "delete", "key": "event:99", "summary": "ours"}, planned["events"]["actions"])

        real = school_gcal.sync(["classes", "deadlines", "events"])
        for name in ("classes", "deadlines", "events"):
            for count in ("created", "updated", "removed"):
                self.assertEqual(real[name][count], planned[name][count], (name, count))

        again = school_gcal.sync(["classes", "deadlines", "events"], dry_run=True)
        for name in ("classes", "deadlines", "events"):
            self.assertEqual(again[name]["created"] + again[name]["updated"] + again[name]["removed"], 0)
            self.assertEqual(again[name]["actions"], [])

    def test_the_write_ceiling_is_shared_across_targets(self) -> None:
        original = school_gcal.MAX_WRITES_PER_SYNC
        school_gcal.MAX_WRITES_PER_SYNC = 3
        try:
            result = school_gcal.sync(["classes", "deadlines"])
        finally:
            school_gcal.MAX_WRITES_PER_SYNC = original
        self.assertEqual(len(self.google.writes), 3)
        self.assertEqual(result["classes"]["created"], 3)
        self.assertEqual(result["classes"]["deferred"], 4)

    def test_mirror_is_a_retired_no_op(self) -> None:
        result = school_gcal.sync(["mirror"])
        self.assertEqual(result["mirror"]["ok"], True)
        self.assertIn("retired", result["mirror"]["skipped"])
        self.assertEqual(self.google.calls, [])
        with self.assertRaises(SchoolError):
            school_gcal.sync(["outlook"])


class ArmingTests(PrimaryTestCase):
    """Nothing unattended writes to primary before a person has run one sync."""

    def setUp(self) -> None:
        super().setUp()
        self.saved["configured"] = school_gcal.configured
        self.saved["_read_token"] = school_gcal._read_token
        school_gcal.configured = lambda: True
        school_gcal._read_token = lambda: {"refresh_token": "r"}
        school.create_assignment(self.course_id, "HW 2", due_at=utc(self.at(2, 23, 59)))

    def test_the_background_sync_only_pulls_until_armed(self) -> None:
        result = school_gcal.sync_if_connected()
        self.assertEqual(list(result), ["pull"])
        self.assertEqual(self.google.writes, [])

    def test_a_dry_run_does_not_arm_and_a_real_manual_sync_does(self) -> None:
        school_gcal.sync(["deadlines"], dry_run=True)
        self.assertFalse(school_gcal.armed())
        school_gcal.sync(["pull"])
        self.assertFalse(school_gcal.armed())
        school_gcal.sync(["deadlines"])
        self.assertTrue(school_gcal.armed())
        writes_before = len(self.google.writes)
        result = school_gcal.sync_if_connected()
        self.assertEqual(set(result), set(school_gcal.SYNC_TARGETS))
        self.assertEqual(len(self.google.writes), writes_before + 7)  # the seven classes

    def test_a_note_applied_before_arming_writes_nothing_to_google(self) -> None:
        school_gcal.status = lambda: {"configured": True, "connected": True}
        applied = self.apply([op("create_event", title="Study group", start_at=utc(self.at(2, 18)))])
        self.assertEqual(applied["gcal"]["attempted"], False)
        self.assertIn("first sync", applied["gcal"]["detail"])
        self.assertEqual(self.google.calls, [])
        with self.assertRaises(SchoolError):
            school_gcal.push_changes(event_ids=[1])


class PullTests(PrimaryTestCase):
    def test_the_pull_skips_every_instance_of_our_own_events(self) -> None:
        master = self.google.add(tagged("class:10001:lecture", "class", "classmaster"))
        start = self.at(1, 11, 30)
        base = {
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": (start + timedelta(minutes=50)).isoformat()},
        }
        self.google.instances = [
            # An expanded instance of our recurring class, carrying the master's
            # extended properties the way Google sends them.
            {
                "id": "classmaster_20260914T153000Z",
                "recurringEventId": master["id"],
                "summary": "CS 101 · Lecture",
                "extendedProperties": master["extendedProperties"],
                **base,
            },
            # The same, with the properties missing: caught by recurringEventId.
            {
                "id": "classmaster_20260916T153000Z",
                "recurringEventId": master["id"],
                "summary": "CS 101 · Lecture",
                **base,
            },
            # A single deadline of ours.
            tagged("assignment:5", "assignment", "deadline-evt"),
            # A person's own appointment, which is the only thing to store.
            {"id": "dentist", "summary": "Dentist", **base},
        ]

        result = school_gcal.sync(["pull"])["pull"]

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["skipped"], 3)
        with db.get_db(self.db_path) as conn:
            rows = conn.execute("SELECT uid, source FROM external_events").fetchall()
        self.assertEqual([(row["uid"], row["source"]) for row in rows], [("dentist", "gcal")])


class ExternalEventsTests(PrimaryTestCase):
    def setUp(self) -> None:
        super().setUp()
        import app as server_app

        self.server_app = server_app

    def test_scheduled_events_come_back_as_source_notes(self) -> None:
        timed = school.create_event(
            "Office hours",
            utc(self.at(2, 15)),
            end_at=utc(self.at(2, 16)),
            location="Room 314",
            course_id=self.course_id,
            notes="bring hw",
        )
        all_day = school.create_event("Career fair", self.at(3).date().isoformat(), end_at=self.at(4).date().isoformat())
        cancelled = school.create_event("Talk", utc(self.at(2, 18)))
        school.cancel_event(cancelled["id"])
        with db.get_db(self.db_path) as conn:
            school_ics._store(
                conn,
                "outlook",
                [
                    {
                        "uid": "o1",
                        "instance_start": utc(self.at(2, 9)),
                        "title": "Outlook thing",
                        "location": None,
                        "description": None,
                        "start_at": utc(self.at(2, 9)),
                        "end_at": None,
                        "all_day": 0,
                    }
                ],
                *school_ics._window(),
            )

        start = self.now.date().isoformat()
        end = (self.now.date() + timedelta(days=10)).isoformat()
        events = self.server_app.school_external_events(start=start, end=end)["events"]
        by_title = {event["title"]: event for event in events}

        self.assertIn("Outlook thing", by_title)
        office = by_title["Office hours"]
        self.assertEqual(
            office,
            {
                "id": timed["id"],
                "source": "notes",
                "title": "Office hours",
                "location": "Room 314",
                "date": self.at(2).date().isoformat(),
                "start": "15:00",
                "end": "16:00",
                "all_day": 0,
                "is_active": 1,
                "course_id": self.course_id,
                "course_code": "CS 101",
                "notes": "bring hw",
            },
        )
        fair = by_title["Career fair"]
        self.assertEqual((fair["all_day"], fair["start"], fair["end"]), (1, None, None))
        self.assertIsNone(fair["course_code"])
        self.assertEqual(fair["id"], all_day["id"])
        self.assertNotIn("Talk", by_title)

        only_notes = self.server_app.school_external_events(start=start, end=end, source="notes")["events"]
        self.assertEqual({event["source"] for event in only_notes}, {"notes"})
        with_cancelled = self.server_app.school_external_events(
            start=start, end=end, source="notes", include_inactive=True
        )["events"]
        talk = next(event for event in with_cancelled if event["title"] == "Talk")
        self.assertEqual(talk["is_active"], 0)
        only_outlook = self.server_app.school_external_events(start=start, end=end, source="outlook")["events"]
        self.assertEqual([event["title"] for event in only_outlook], ["Outlook thing"])
        with self.assertRaises(SchoolError):
            self.server_app.school_external_events(start=start, end=end, source="nope")

        raw = self.server_app.school_events(include_cancelled=True)["events"]
        self.assertEqual(len(raw), 3)
        self.assertTrue(raw[0]["start_at"].endswith("Z") or len(raw[0]["start_at"]) == 10)

    def test_the_sync_route_accepts_dry_run_and_serves_both_shapes(self) -> None:
        body = self.server_app.GcalSyncRequest(targets=["events"], dry_run=True)
        answer_ = self.server_app.school_gcal_sync(body)
        self.assertEqual(answer_["results"]["events"], answer_["events"])
        self.assertTrue(answer_["events"]["dry_run"])
        self.assertEqual(self.google.writes, [])

    def test_status_reports_primary_and_the_legacy_calendars(self) -> None:
        school_gcal.status = self.saved["status"]
        school_gcal._state_set("classes_id", "abc@group.calendar.google.com")
        payload = school_gcal.status()
        self.assertEqual(payload["calendar_id"], "primary")
        self.assertEqual(
            payload["legacy_calendars"],
            [{"summary": "Classes", "id": "abc@group.calendar.google.com"}],
        )
        for key in ("configured", "connected", "account_email", "error", "last_sync_at", "calendars", "redirect_uri"):
            self.assertIn(key, payload)

    def test_the_assignment_patch_route_takes_ends_at_and_location(self) -> None:
        work = school.create_assignment(self.course_id, "Quiz", kind="quiz", due_at=utc(self.at(4, 10)))
        patched = self.server_app.patch_school_assignment(
            work["id"],
            self.server_app.AssignmentPatch(ends_at=utc(self.at(4, 11)), location="Hall 175"),
        )
        self.assertEqual(patched["ends_at"], utc(self.at(4, 11)))
        self.assertEqual(patched["location"], "Hall 175")


class MigrationTests(unittest.TestCase):
    def test_an_old_assignments_table_gains_the_columns_and_the_events_table(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.db"
            with db.get_db(path) as conn:
                conn.executescript(
                    "CREATE TABLE courses (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, "
                    "title TEXT NOT NULL);"
                    "CREATE TABLE assignments (id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL, "
                    "source TEXT, source_id TEXT, title TEXT NOT NULL, kind TEXT, due_at TEXT, "
                    "status TEXT NOT NULL DEFAULT 'pending');"
                    "INSERT INTO courses (code, title) VALUES ('X 1', 'X');"
                    "INSERT INTO assignments (course_id, title) VALUES (1, 'kept');"
                )
            db.init_db(path)
            db.init_db(path)  # idempotent
            with db.get_db(path) as conn:
                columns = {row["name"] for row in conn.execute("PRAGMA table_info(assignments)")}
                self.assertTrue({"ends_at", "location", "notes"} <= columns)
                self.assertEqual(conn.execute("SELECT title FROM assignments").fetchone()[0], "kept")
                event_columns = {row["name"] for row in conn.execute("PRAGMA table_info(school_events)")}
                self.assertTrue({"start_at", "status", "note_id", "cancelled_at"} <= event_columns)


class GoogleNormalizationTests(unittest.TestCase):
    """Google normalizations the first real sync exposed."""

    def test_an_rrule_google_reordered_is_not_a_change(self) -> None:
        ours = ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR;UNTIL=20261213T045959Z"]
        google = ["RRULE:FREQ=WEEKLY;UNTIL=20261213T045959Z;BYDAY=MO,WE,FR"]
        self.assertEqual(school_gcal._recurrence_key(ours), school_gcal._recurrence_key(google))
        self.assertNotEqual(
            school_gcal._recurrence_key(ours),
            school_gcal._recurrence_key(["RRULE:FREQ=WEEKLY;BYDAY=TU;UNTIL=20261213T045959Z"]),
        )

    def test_a_patch_to_all_day_clears_the_old_timed_shape(self) -> None:
        body = {"summary": "x", "start": {"date": "2026-09-09"}, "end": {"date": "2026-09-10"}}
        patched = school_gcal._patch_times(body)
        self.assertEqual(patched["start"], {"date": "2026-09-09", "dateTime": None, "timeZone": None})
        self.assertEqual(patched["end"], {"date": "2026-09-10", "dateTime": None, "timeZone": None})
        self.assertEqual(body["start"], {"date": "2026-09-09"})

    def test_a_patch_to_timed_clears_the_old_date(self) -> None:
        body = {
            "start": {"dateTime": "2026-10-12T11:30:00", "timeZone": "America/Indiana/Indianapolis"},
            "end": {"dateTime": "2026-10-12T20:00:00Z"},
        }
        patched = school_gcal._patch_times(body)
        self.assertIsNone(patched["start"]["date"])
        self.assertEqual(patched["start"]["timeZone"], "America/Indiana/Indianapolis")
        self.assertEqual(patched["end"], {"dateTime": "2026-10-12T20:00:00Z", "date": None, "timeZone": None})


if __name__ == "__main__":
    unittest.main()
