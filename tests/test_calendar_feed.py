"""The subscribable calendar feed: RFC 5545 output and the one token-free route.

Output is parsed back by an independent reader (icalendar, recurring_ical_events);
raw bytes are checked for what a lenient parser forgives. HTTP tests drive the
ASGI app directly, middleware included.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import stat
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "app" / "server"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import icalendar  # noqa: E402
import recurring_ical_events  # noqa: E402

import calendar_feed  # noqa: E402
import db  # noqa: E402
import fixtures  # noqa: E402
import security  # noqa: E402

CAMPUS = ZoneInfo(db.LOCAL_TZ_NAME)
TODAY = date(2026, 9, 13)
TOKEN = "test-dashboard-token"
LOCAL_HOST = f"127.0.0.1:{security.PORT}"
PUBLIC = "https://study-mac.tail1234.ts.net"


def _load_app():
    """app.py by file path, so a directory named `app` can never shadow it."""
    spec = importlib.util.spec_from_file_location(
        "semester_os_app_for_feed_tests", REPO_ROOT / "app" / "server" / "app.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


APP_MODULE = _load_app()


def call(
    path: str,
    *,
    method: str = "GET",
    host: str = LOCAL_HOST,
    headers: dict[str, str] | None = None,
    body: object = None,
) -> tuple[int, dict[str, str], bytes]:
    """One request through the whole ASGI stack. Returns status, headers, body."""
    raw_headers = [(b"host", host.encode())]
    payload = b""
    if body is not None:
        payload = json.dumps(body).encode()
        raw_headers.append((b"content-type", b"application/json"))
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode(), value.encode()))
    path_only, _, query = path.partition("?")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path_only,
        "raw_path": path_only.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": raw_headers,
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", security.PORT),
    }
    messages: list[dict] = []
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": payload, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    asyncio.run(APP_MODULE.app(scope, receive, send))
    start = next(message for message in messages if message["type"] == "http.response.start")
    content = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    response_headers = {key.decode().lower(): value.decode() for key, value in start["headers"]}
    return start["status"], response_headers, content


class FeedTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.saved = {
            "db_path": db.DB_PATH,
            "state_path": calendar_feed.STATE_PATH,
            "token_cache": security._token_cache,
            "token_path": security.TOKEN_PATH,
        }
        db.DB_PATH = root / "semester.db"
        db.init_db(db.DB_PATH)
        calendar_feed.STATE_PATH = root / ".calendar_feed.json"
        security.TOKEN_PATH = root / ".semester_os_token"
        security._token_cache = TOKEN
        fixtures.seed_semester()
        with db.get_db() as conn:
            self.course_id = int(conn.execute("SELECT id FROM courses WHERE code = 'CS 101'").fetchone()[0])

    def tearDown(self) -> None:
        db.DB_PATH = self.saved["db_path"]
        calendar_feed.STATE_PATH = self.saved["state_path"]
        security.TOKEN_PATH = self.saved["token_path"]
        security._token_cache = self.saved["token_cache"]
        self.temp.cleanup()

    def add_assignment(self, title: str, due_at: str, **extra: object) -> int:
        fields = {"course_id": self.course_id, "title": title, "due_at": due_at, "status": "pending", **extra}
        columns = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        with db.get_db() as conn:
            cursor = conn.execute(f"INSERT INTO assignments ({columns}) VALUES ({marks})", list(fields.values()))
            return int(cursor.lastrowid)

    def add_event(self, title: str, start_at: str, end_at: str | None = None, **extra: object) -> int:
        fields = {"title": title, "start_at": start_at, "end_at": end_at, "status": "scheduled", **extra}
        columns = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        with db.get_db() as conn:
            cursor = conn.execute(f"INSERT INTO school_events ({columns}) VALUES ({marks})", list(fields.values()))
            return int(cursor.lastrowid)

    def feed(self) -> bytes:
        body, _ = calendar_feed.render(TODAY)
        return body

    def events(self, body: bytes) -> dict[str, icalendar.Event]:
        calendar = icalendar.Calendar.from_ical(body)
        return {str(event["UID"]): event for event in calendar.walk("VEVENT")}

    def feed_path(self) -> str:
        return calendar_feed.feed_urls(calendar_feed.load_state())["path"]


class RfcOutputTests(FeedTestCase):
    def test_parses_as_a_calendar_with_the_expected_header(self) -> None:
        self.add_assignment("Problem set 1", "2026-09-20T23:59:00Z", kind="hw")
        body = self.feed()
        calendar = icalendar.Calendar.from_ical(body)
        self.assertEqual(str(calendar["VERSION"]), "2.0")
        self.assertEqual(str(calendar["X-WR-CALNAME"]), "Semester OS")
        self.assertEqual(str(calendar["X-PUBLISHED-TTL"]), "PT1H")
        self.assertIn(b"REFRESH-INTERVAL;VALUE=DURATION:PT1H\r\n", body)
        self.assertEqual(len(calendar.walk("VTIMEZONE")), 1)
        self.assertEqual(str(calendar.walk("VTIMEZONE")[0]["TZID"]), db.LOCAL_TZ_NAME)
        for event in calendar.walk("VEVENT"):
            for required in ("UID", "DTSTAMP", "DTSTART", "SEQUENCE", "LAST-MODIFIED", "SUMMARY"):
                self.assertIn(required, event, f"{event.get('UID')} lacks {required}")

    def test_lines_end_in_crlf_and_fold_at_75_octets(self) -> None:
        long_note = ("Read chapters 3, 4; then the appendix. Ünïcödé keeps its bytes whole. " * 6).strip()
        self.add_assignment("Essay", "2026-09-22T23:59:00Z", notes=long_note)
        body = self.feed()
        self.assertTrue(body.endswith(b"\r\n"))
        self.assertNotIn(b"\n", body.replace(b"\r\n", b""), "a bare LF slipped into the output")
        physical = body.split(b"\r\n")[:-1]
        for line in physical:
            self.assertLessEqual(len(line), 75, line)
            line.decode("utf-8")  # a fold never splits a multi-byte character
        self.assertTrue(any(line.startswith(b" ") for line in physical), "nothing was folded")

        event = self.events(body)[f"assignment-{self._last_assignment_id()}@semester-os"]
        self.assertEqual(str(event["DESCRIPTION"]), long_note)

    def _last_assignment_id(self) -> int:
        with db.get_db() as conn:
            return int(conn.execute("SELECT MAX(id) FROM assignments").fetchone()[0])

    def test_text_is_escaped(self) -> None:
        identifier = self.add_assignment(
            "Lab 2, part A; see C:\\ drive", "2026-09-21T15:00:00Z", notes="first line\nsecond line"
        )
        body = self.feed()
        self.assertIn(b"SUMMARY:CS 101 \xc2\xb7 Lab 2\\, part A\\; see C:\\\\ drive\r\n", body)
        self.assertIn(b"DESCRIPTION:first line\\nsecond line\r\n", body)
        event = self.events(body)[f"assignment-{identifier}@semester-os"]
        # Backslash before a space: icalendar un-escapes twice, so backslash+n would parse as a newline.
        self.assertEqual(str(event["SUMMARY"]), "CS 101 · Lab 2, part A; see C:\\ drive")
        self.assertEqual(str(event["DESCRIPTION"]), "first line\nsecond line")

    def test_weekly_class_is_one_rrule_event_with_until(self) -> None:
        events = self.events(self.feed())
        lecture = events["class-10001-lecture@semester-os"]
        rule = lecture["RRULE"]
        self.assertEqual(rule["FREQ"], ["WEEKLY"])
        self.assertEqual(sorted(rule["BYDAY"]), ["FR", "MO", "WE"])
        self.assertIn("UNTIL", rule)
        self.assertEqual(lecture["DTSTART"].params.get("TZID"), db.LOCAL_TZ_NAME)
        self.assertEqual(str(lecture["LOCATION"]), "Room 101")
        self.assertIn(b"CATEGORIES:Class,CS 101", lecture.to_ical())

    def test_class_keeps_its_wall_time_across_the_november_change(self) -> None:
        calendar = icalendar.Calendar.from_ical(self.feed())
        occurrences = [
            event
            for event in recurring_ical_events.of(calendar).between(datetime(2026, 10, 26), datetime(2026, 11, 7))
            if str(event["UID"]) == "class-10001-lecture@semester-os"
        ]
        days = {event["DTSTART"].dt.date(): event["DTSTART"].dt for event in occurrences}
        before, after = days[date(2026, 10, 30)], days[date(2026, 11, 2)]
        for moment in (before, after):
            self.assertEqual(moment.astimezone(CAMPUS).strftime("%H:%M"), "11:30")
        # Only a zone that observes DST moves the UTC instant.
        expected_shift = (
            datetime(2026, 11, 2, 12, tzinfo=CAMPUS).utcoffset() - datetime(2026, 10, 30, 12, tzinfo=CAMPUS).utcoffset()
        )
        self.assertEqual(
            (after.astimezone(ZoneInfo("UTC")).hour - before.astimezone(ZoneInfo("UTC")).hour) % 24,
            int(-expected_shift.total_seconds() // 3600) % 24,
        )
        # The last session is the one on or before the meeting's end date.
        self.assertEqual(max(
            event["DTSTART"].dt.date()
            for event in recurring_ical_events.of(calendar).between(datetime(2026, 12, 1), datetime(2027, 1, 31))
            if str(event["UID"]) == "class-10001-lecture@semester-os"
        ), date(2026, 12, 11))

    def test_vtimezone_matches_zoneinfo(self) -> None:
        lines = calendar_feed.vtimezone_lines("America/New_York", date(2026, 8, 1), date(2027, 1, 1))
        text = "\r\n".join(lines)
        self.assertIn("DTSTART:20261101T020000\r\nTZOFFSETFROM:-0400\r\nTZOFFSETTO:-0500", text)
        self.assertIn("DTSTART:20260308T020000\r\nTZOFFSETFROM:-0500\r\nTZOFFSETTO:-0400", text)
        utc_only = calendar_feed.vtimezone_lines("UTC", date(2026, 8, 1), date(2027, 1, 1))
        self.assertEqual(sum(1 for line in utc_only if line.startswith("BEGIN:STANDARD")), 1)

    def test_deadline_shapes(self) -> None:
        timed = self.add_assignment("Problem set", "2026-09-20T23:59:00Z", kind="hw")
        bare = self.add_assignment("Reading", "2026-09-25", kind="reading")
        exam = self.add_assignment(
            "Midterm", "2026-10-15T20:00", kind="exam", ends_at="2026-10-15T22:00", location="KLR 214"
        )
        events = self.events(self.feed())

        block = events[f"assignment-{timed}@semester-os"]
        self.assertEqual(block["DTEND"].dt - block["DTSTART"].dt, timedelta(minutes=30))
        self.assertEqual(block["DTEND"].dt, datetime(2026, 9, 20, 23, 59, tzinfo=ZoneInfo("UTC")))
        self.assertEqual(str(block["TRANSP"]), "TRANSPARENT")

        day = events[f"assignment-{bare}@semester-os"]
        self.assertEqual(day["DTSTART"].dt, date(2026, 9, 25))
        self.assertEqual(day["DTEND"].dt, date(2026, 9, 26))

        midterm = events[f"assignment-{exam}@semester-os"]
        self.assertEqual(str(midterm["LOCATION"]), "KLR 214")
        self.assertEqual(midterm["DTSTART"].dt.astimezone(CAMPUS).strftime("%H:%M"), "20:00")
        self.assertEqual(midterm["DTEND"].dt - midterm["DTSTART"].dt, timedelta(hours=2))
        self.assertEqual(str(midterm["TRANSP"]), "OPAQUE")
        self.assertIn(b"CATEGORIES:Exam,CS 101", midterm.to_ical())

    def test_done_is_checked_and_dropped_or_cancelled_is_omitted(self) -> None:
        done = self.add_assignment("Quiz 1", "2026-09-18T12:00:00Z", status="graded")
        dropped = self.add_assignment("Old quiz", "2026-09-19T12:00:00Z", status="dropped")
        kept = self.add_event("Office hours", "2026-09-18T15:00:00Z", "2026-09-18T16:00:00Z")
        cancelled = self.add_event("Advisor", "2026-09-19T15:00:00Z", status="cancelled")
        too_old = self.add_assignment("Ancient", "2026-06-01T12:00:00Z")
        events = self.events(self.feed())

        self.assertTrue(str(events[f"assignment-{done}@semester-os"]["SUMMARY"]).startswith("✓ "))
        self.assertNotIn(f"assignment-{dropped}@semester-os", events)
        self.assertIn(f"event-{kept}@semester-os", events)
        self.assertNotIn(f"event-{cancelled}@semester-os", events)
        self.assertNotIn(f"assignment-{too_old}@semester-os", events)

    def test_uids_and_bytes_are_stable_and_sequence_moves_only_on_change(self) -> None:
        identifier = self.add_assignment("Problem set", "2026-09-20T23:59:00Z")
        first = self.feed()
        second = self.feed()
        self.assertEqual(first, second, "an unchanged semester must produce identical bytes")
        uid = f"assignment-{identifier}@semester-os"
        self.assertEqual(int(self.events(first)[uid]["SEQUENCE"]), 0)
        self.assertEqual(set(self.events(first)), set(self.events(second)))

        with db.get_db() as conn:
            conn.execute("UPDATE assignments SET title = 'Problem set (revised)' WHERE id = ?", (identifier,))
        third = self.events(self.feed())
        self.assertEqual(int(third[uid]["SEQUENCE"]), 1)
        self.assertEqual(int(third["class-10001-lecture@semester-os"]["SEQUENCE"]), 0)
        self.assertEqual(int(self.events(self.feed())[uid]["SEQUENCE"]), 1)

    def test_uids_survive_rotation(self) -> None:
        before = set(self.events(self.feed()))
        calendar_feed.rotate_secret()
        self.assertEqual(before, set(self.events(self.feed())))


class SecurityTests(FeedTestCase):
    def test_secret_is_long_random_and_private(self) -> None:
        state = calendar_feed.load_state()
        self.assertGreaterEqual(len(state["secret"]), 43)
        mode = stat.S_IMODE(os.stat(calendar_feed.STATE_PATH).st_mode)
        self.assertEqual(mode, 0o600)
        self.assertEqual(calendar_feed.load_state()["secret"], state["secret"])

    def test_feed_works_without_the_token(self) -> None:
        status, headers, body = call(self.feed_path(), headers={"user-agent": "macOS/15.0 CalendarAgent/1"})
        self.assertEqual(status, 200)
        self.assertTrue(headers["content-type"].startswith("text/calendar"))
        self.assertIn("charset=utf-8", headers["content-type"])
        self.assertIn("private", headers["cache-control"])
        self.assertTrue(body.startswith(b"BEGIN:VCALENDAR\r\n"))

        status, _, _ = call(self.feed_path(), headers={"if-none-match": headers["etag"]})
        self.assertEqual(status, 304)

        readers = calendar_feed.describe(TODAY)["readers"]
        self.assertEqual(readers[0]["client"], "apple")

    def test_wrong_secret_is_404(self) -> None:
        good = calendar_feed.load_state()["secret"]
        for secret in ("nope", good[:-1] + ("A" if good[-1] != "A" else "B"), good + "x", "x" * 43):
            status, _, body = call(f"/calendar/{secret}.ics")
            self.assertEqual(status, 404, secret)
            self.assertNotIn(b"VCALENDAR", body)

    def test_token_exemption_is_limited_to_the_feed_path(self) -> None:
        for path, method in (
            ("/api/calendar-feed", "GET"),
            ("/api/calendar-feed/rotate", "POST"),
            ("/api/calendar-feed/public-url", "PUT"),
            ("/api/school/courses", "GET"),
        ):
            status, _, _ = call(path, method=method)
            self.assertEqual(status, 401, path)

        status, _, body = call("/api/calendar-feed", headers={security.TOKEN_HEADER: TOKEN})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["path"], self.feed_path())

        # A mutating method on the feed path is not the feed.
        status, _, _ = call(self.feed_path(), method="POST")
        self.assertNotEqual(status, 200)

        # An unknown Host still gets the DNS rebinding refusal, feed path included.
        status, _, _ = call(self.feed_path(), host="evil.example:80")
        self.assertEqual(status, 403)

    def test_rotation_requires_the_token_and_same_origin_and_invalidates(self) -> None:
        old_path = self.feed_path()
        status, _, _ = call(
            "/api/calendar-feed/rotate",
            method="POST",
            headers={security.TOKEN_HEADER: TOKEN, "origin": "https://evil.example"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(call(old_path)[0], 200)

        status, _, body = call("/api/calendar-feed/rotate", method="POST", headers={security.TOKEN_HEADER: TOKEN})
        self.assertEqual(status, 200)
        new_path = json.loads(body)["path"]
        self.assertNotEqual(new_path, old_path)
        self.assertEqual(call(old_path)[0], 404)
        self.assertEqual(call(new_path)[0], 200)

    def test_public_address_is_validated(self) -> None:
        for bad in (
            "http://study-mac.tail1234.ts.net",
            "https://127.0.0.1",
            "https://localhost:8790",
            "https://study-mac.tail1234.ts.net/calendar",
            "https://user:pw@study-mac.tail1234.ts.net",
            "https://study-mac.tail1234.ts.net?x=1",
            "https://10.0.0.4",
            "https://nodot",
        ):
            status, _, _ = call(
                "/api/calendar-feed/public-url",
                method="PUT",
                headers={security.TOKEN_HEADER: TOKEN},
                body={"public_base_url": bad},
            )
            self.assertEqual(status, 422, bad)
        self.assertIsNone(calendar_feed.load_state()["public_base_url"])

    def test_public_host_reaches_the_feed_and_nothing_else(self) -> None:
        public_host = PUBLIC.split("://", 1)[1]
        # Not configured: a tunnel host is an unknown Host like any other.
        self.assertEqual(call(self.feed_path(), host=public_host)[0], 403)

        status, _, body = call(
            "/api/calendar-feed/public-url",
            method="PUT",
            headers={security.TOKEN_HEADER: TOKEN},
            body={"public_base_url": PUBLIC + "/"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["public_url"], PUBLIC + self.feed_path())

        forwarded = {"x-forwarded-for": "203.0.113.9", "user-agent": "Google-Calendar-Importer"}
        self.assertEqual(call(self.feed_path(), host=public_host, headers=forwarded)[0], 200)
        self.assertEqual(call(self.feed_path(), host=public_host + ":443", headers=forwarded)[0], 200)
        self.assertEqual(call("/calendar/wrong-secret.ics", host=public_host, headers=forwarded)[0], 404)
        for path in ("/", "/api/health", "/api/bootstrap", "/api/calendar-feed", "/connect", "/calendar/"):
            status, _, body = call(path, host=public_host, headers={**forwarded, security.TOKEN_HEADER: TOKEN})
            self.assertEqual(status, 404, path)
            self.assertNotIn(TOKEN.encode(), body)
        status, _, _ = call(
            "/api/calendar-feed/rotate", method="POST", host=public_host, headers={security.TOKEN_HEADER: TOKEN}
        )
        self.assertEqual(status, 404)

    def test_proxy_that_rewrites_host_reaches_only_the_feed(self) -> None:
        proxied = {"x-forwarded-for": "203.0.113.9"}
        status, _, body = call("/api/bootstrap", headers=proxied)
        self.assertEqual(status, 404)
        self.assertNotIn(TOKEN.encode(), body)
        self.assertEqual(call("/api/health", headers={"cf-connecting-ip": "203.0.113.9"})[0], 404)
        self.assertEqual(call(self.feed_path(), headers=proxied)[0], 200)
        # Without the forwarding headers the dashboard is untouched.
        self.assertEqual(call("/api/health")[0], 200)

    def test_feed_path_never_reaches_a_log(self) -> None:
        calendar_feed.install_log_redaction()
        logger = logging.getLogger("uvicorn.access")
        path = self.feed_path()
        record = logger.makeRecord(
            "uvicorn.access", logging.INFO, __file__, 1,
            '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:5000", "GET", path, "1.1", 200), None,
        )
        for handler_filter in logger.filters:
            handler_filter.filter(record)
        message = record.getMessage()
        self.assertNotIn(calendar_feed.load_state()["secret"], message)
        self.assertIn(calendar_feed.REDACTED_PATH, message)


if __name__ == "__main__":
    unittest.main()
