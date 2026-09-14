"""config.yaml defaults, validation and environment overrides (never the real file or env)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "app" / "server"))

import config  # noqa: E402
from config import ConfigError  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_an_empty_file_runs_on_the_defaults(self) -> None:
        loaded = config.parse({}, environ={})
        self.assertEqual(loaded.timezone, "America/Indiana/Indianapolis")
        self.assertEqual(loaded.port, 8790)
        self.assertIsNone(loaded.term)
        self.assertIsNone(loaded.school_name)
        self.assertEqual(loaded.calendar_feeds, {"outlook": None, "brightspace": None})

    def test_every_key_is_read(self) -> None:
        loaded = config.parse(
            {
                "timezone": "America/New_York",
                "term": "Spring 2027",
                "school_name": "Example University",
                "calendar_feeds": {"outlook": "https://mail.example.edu/cal.ics", "brightspace": ""},
                "port": 9001,
            },
            environ={},
        )
        self.assertEqual(loaded.timezone, "America/New_York")
        self.assertEqual(loaded.term, "Spring 2027")
        self.assertEqual(loaded.school_name, "Example University")
        self.assertEqual(loaded.calendar_feeds["outlook"], "https://mail.example.edu/cal.ics")
        self.assertIsNone(loaded.calendar_feeds["brightspace"])
        self.assertEqual(loaded.port, 9001)

    def test_an_unknown_top_level_key_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.yaml"
            path.write_text("timezone: America/Chicago\ntimzone: typo\n", encoding="utf-8")
            with self.assertRaises(ConfigError) as raised:
                config.load(path)
        self.assertIn("timzone", str(raised.exception))

    def test_an_unknown_feed_is_refused(self) -> None:
        with self.assertRaises(ConfigError):
            config.parse({"calendar_feeds": {"canvas": "https://x.example/c.ics"}}, environ={})

    def test_a_timezone_this_machine_does_not_know_is_refused(self) -> None:
        with self.assertRaises(ConfigError):
            config.parse({"timezone": "Mars/Olympus_Mons"}, environ={})

    def test_a_feed_must_be_https_and_the_url_is_never_echoed(self) -> None:
        with self.assertRaises(ConfigError) as raised:
            config.parse({"calendar_feeds": {"outlook": "http://secret-token.example/c.ics"}}, environ={})
        self.assertNotIn("secret-token", str(raised.exception))

    def test_a_port_outside_the_unprivileged_range_is_refused(self) -> None:
        for port in (80, 70000, "abc", True):
            with self.subTest(port=port), self.assertRaises(ConfigError):
                config.parse({"port": port}, environ={})

    def test_environment_overrides_win_and_are_validated(self) -> None:
        loaded = config.parse(
            {"timezone": "America/Chicago", "port": 8790},
            environ={
                "SEMESTER_OS_TIMEZONE": "Europe/Madrid",
                "SEMESTER_OS_PORT": "8801",
                "SEMESTER_OS_BRIGHTSPACE_ICS_URL": "https://lms.example.edu/feed.ics",
            },
        )
        self.assertEqual(loaded.timezone, "Europe/Madrid")
        self.assertEqual(loaded.port, 8801)
        self.assertEqual(loaded.calendar_feeds["brightspace"], "https://lms.example.edu/feed.ics")
        with self.assertRaises(ConfigError):
            config.parse({}, environ={"SEMESTER_OS_PORT": "22"})

    def test_the_public_view_never_carries_a_feed_url(self) -> None:
        view = config.public_view()
        self.assertEqual(set(view["calendar_feeds"]), set(config.FEED_NAMES))
        self.assertTrue(all(isinstance(value, bool) for value in view["calendar_feeds"].values()))

    def test_the_example_file_is_valid(self) -> None:
        loaded = config.load(config.EXAMPLE_PATH)
        self.assertEqual(loaded.port, config.DEFAULT_PORT)


if __name__ == "__main__":
    unittest.main()
