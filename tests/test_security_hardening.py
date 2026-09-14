"""Security review fixes, one test per fix: untrusted input must not reach an unhandled path.

No real data/, network or model: everything lives in a temporary directory.
"""

from __future__ import annotations

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

import db  # noqa: E402
import onboarding  # noqa: E402
import runner  # noqa: E402
import school_ics  # noqa: E402
import security  # noqa: E402
from school import SchoolError  # noqa: E402


class TokenComparisonTests(unittest.TestCase):
    """A header is whatever the client sent; comparing it must never raise."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.original = (security.TOKEN_PATH, security._token_cache)  # noqa: SLF001
        security.TOKEN_PATH = Path(self.temp.name) / ".semester_os_token"
        security._token_cache = None  # noqa: SLF001

    def tearDown(self) -> None:
        security.TOKEN_PATH, security._token_cache = self.original  # noqa: SLF001
        self.temp.cleanup()

    def test_a_non_ascii_token_is_invalid_rather_than_an_error(self) -> None:
        token = security.load_or_create_token()
        self.assertTrue(security.token_is_valid(token))
        self.assertTrue(security.token_is_valid(f"  {token}\n"))
        # Starlette decodes headers as latin-1; str compare_digest raises on these.
        self.assertFalse(security.token_is_valid("café"))
        self.assertFalse(security.token_is_valid(token[:-1] + "ÿ"))
        self.assertFalse(security.token_is_valid("\udcff"))
        self.assertFalse(security.token_is_valid(""))
        self.assertFalse(security.token_is_valid(None))


class DamagedDocxTests(unittest.TestCase):
    """A .docx in syllabi/ that cannot be read is the student's 415, never a 500."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.original = (db.DB_PATH, onboarding.SYLLABI_DIR, onboarding.EXTRACT_DIR)
        db.DB_PATH = root / "semester.db"
        db.init_db(db.DB_PATH)
        onboarding.SYLLABI_DIR = root / "syllabi"
        onboarding.EXTRACT_DIR = root / "extracted"
        onboarding.SYLLABI_DIR.mkdir()

    def tearDown(self) -> None:
        db.DB_PATH, onboarding.SYLLABI_DIR, onboarding.EXTRACT_DIR = self.original
        self.temp.cleanup()

    def refusal(self, data: bytes) -> SchoolError:
        path = onboarding.SYLLABI_DIR / "broken.docx"
        path.write_bytes(data)
        with self.assertRaises(SchoolError) as raised:
            onboarding._extract_docx(path, 1)  # noqa: SLF001
        return raised.exception

    @staticmethod
    def docx(document: bytes) -> bytes:
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", document)
        return buffer.getvalue()

    def test_a_file_that_is_not_a_zip_is_refused(self) -> None:
        self.assertEqual(self.refusal(b"this is not a zip archive at all").status_code, 415)

    def test_malformed_document_xml_is_refused(self) -> None:
        self.assertEqual(self.refusal(self.docx(b"<w:document><unclosed>")).status_code, 415)

    def test_a_member_that_fails_its_checksum_is_refused(self) -> None:
        data = bytearray(self.docx(b"<?xml version='1.0'?><document>" + b"x" * 4000 + b"</document>"))
        # Corrupt one byte of the compressed stream, after the local header.
        data[60] ^= 0xFF
        self.assertEqual(self.refusal(bytes(data)).status_code, 415)

    def test_a_readable_docx_still_extracts(self) -> None:
        namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        xml = (
            f'<w:document xmlns:w="{namespace}"><w:body>'
            "<w:p><w:r><w:t>CS 2100 Syllabus</w:t></w:r></w:p>"
            "</w:body></w:document>"
        ).encode("utf-8")
        path = onboarding.SYLLABI_DIR / "fine.docx"
        path.write_bytes(self.docx(xml))
        target = onboarding._extract_docx(path, 7)  # noqa: SLF001
        self.assertEqual(target.read_text(encoding="utf-8"), "CS 2100 Syllabus")


class _FakeResponse:
    def __init__(self, final_url: str, body: bytes) -> None:
        self.final_url = final_url
        self.body = body
        self.read_called = False

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def geturl(self) -> str:
        return self.final_url

    def read(self, _limit: int = -1) -> bytes:
        self.read_called = True
        return self.body


class FeedRedirectTests(unittest.TestCase):
    """urllib follows a redirect to plain http by itself; the body is not used."""

    def setUp(self) -> None:
        self.original = urllib.request.urlopen

    def tearDown(self) -> None:
        urllib.request.urlopen = self.original

    def serve(self, final_url: str) -> _FakeResponse:
        response = _FakeResponse(final_url, b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n")
        urllib.request.urlopen = lambda request, timeout=None: response  # noqa: ARG005
        return response

    def test_a_feed_redirected_to_http_is_refused_without_reading_it(self) -> None:
        response = self.serve("http://127.0.0.1:8790/api/bootstrap")
        with self.assertRaises(school_ics.FeedError) as raised:
            school_ics._fetch("https://calendar.example.edu/feed.ics?token=secret")  # noqa: SLF001
        self.assertIn("not https", str(raised.exception))
        self.assertNotIn("127.0.0.1", str(raised.exception))
        self.assertNotIn("secret", str(raised.exception))
        self.assertFalse(response.read_called)

    def test_a_feed_that_stays_on_https_is_read(self) -> None:
        self.serve("https://cdn.example.edu/feed.ics")
        body = school_ics._fetch("https://calendar.example.edu/feed.ics")  # noqa: SLF001
        self.assertIn("BEGIN:VCALENDAR", body)


class AgentToolRestrictionTests(unittest.TestCase):
    """Every run gets --tools, not only --allowedTools, whatever its type."""

    def test_a_note_run_is_limited_to_read_outright(self) -> None:
        command = runner.build_command("claude", "a note", "school_note")
        self.assertEqual(command[command.index("--allowedTools") + 1], "Read")
        self.assertEqual(command[command.index("--tools") + 1], "Read")
        self.assertEqual(command[command.index("--agent") + 1], "school-editor")
        self.assertNotIn("--dangerously-skip-permissions", command)
        # The prompt is one argument, never split or joined into a shell string.
        self.assertEqual(command[command.index("-p") + 1], "a note")


if __name__ == "__main__":
    unittest.main()
