# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### v0.1.0 (first public release, not yet tagged)

#### Added

- **Dashboard** on `127.0.0.1` (FastAPI + React): Today, Week, Assignments, Courses and Notes, dark and light themes.
- **Syllabus onboarding** on Set up: PDF, Word, Markdown, text, saved HTML, `syllabi/` or a course URL. Unstated values are flagged, problems block Confirm, courses can be typed by hand, and re-confirming a syllabus keeps hand edits.
- **Exams as timed blocks in a room**, on Week, Today, the feed and Google. Syllabi use `end_time`/`location`; Notes use `ends_at`/`location`.
- **Grade center** per course: current average, secured, lost and open per category, and the average needed for a target.
- **Notes**: proposed changes to assignments, exams, to-dos and events, reviewed before writing. Ambiguous notes get a question.
- **Connect**: subscribable calendar feed with a rotatable secret and optional public address; Outlook and Brightspace import; optional Google Calendar sync via your own OAuth client.
- `config.yaml` validation naming the bad key, plus environment overrides.
- `semester-os` launcher (`semester-os.cmd` on Windows): `setup`, `start`, `stop`, `status`, `update`, `doctor`.
- `scripts/seed_demo.py` (invented semester) and `scripts/capture/` (regenerates README media offline).
- Two invented syllabi in `examples/syllabi/`.
- Docs: README, install, configuration, calendars, background service, FAQ, security, contributing.
- CI on Ubuntu and macOS: tests, web build, launcher smoke test.
