# Configuration

Everything that differs between students lives in `config.yaml` at the repo root.

- Optional. `./semester-os setup` copies it from `config.example.yaml`; without it, defaults apply.
- Gitignored: its feed URLs are credentials. Never commit or share it.
- Validated at startup by `app/server/config.py`. An unknown key or wrong type stops the server with a message naming it. `./semester-os doctor` runs the same check.
- If an edit fails validation while running, the server keeps the last valid config and reports the error at next start.

```yaml
timezone: America/New_York
term: Spring 2027
school_name: Example University
calendar_feeds:
  outlook: https://outlook.office365.com/owa/calendar/.../calendar.ics
  brightspace: https://example.brightspace.com/d2l/le/calendar/feed/user/feed.ics?token=...
port: 8790
```

## Keys

These five are the only keys.

| Key | Value | Default | Applies |
| --- | --- | --- | --- |
| `timezone` | IANA tz name | `America/Indiana/Indianapolis` | Restart |
| `term` | Text, max 60 chars | empty | Live |
| `school_name` | Text, max 120 chars | empty | Live |
| `calendar_feeds` | `outlook` and `brightspace`, each an `https://` URL or empty | empty | Next sync |
| `port` | 1024-65535 | `8790` | Restart |

- **`timezone`**: class meetings, displayed times and notes like "Friday at 8" use it. Must be a [tz database name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) such as `America/Chicago`; `EST` or `UTC-5` are refused (no DST).
- **`term`**: e.g. `Fall 2026`. Shown in the UI and assigned to new courses. Control characters refused.
- **`school_name`**: shown under the wordmark.
- **`calendar_feeds`**: ICS links fetched every 30 minutes into Today and Week. Max 4000 chars, other feed names refused, never logged or shown. Where to find them: [calendar.md](calendar.md#import-feeds-outlook-and-brightspace).
- **`port`**: the server always binds `127.0.0.1`; only the port changes. Token and host checks follow it.

## Environment variables

Override the file, validated the same way. For scripts, tests and services.

| Variable | Sets |
| --- | --- |
| `SEMESTER_OS_TIMEZONE` | `timezone` |
| `SEMESTER_OS_PORT` | `port` (also read by the Vite dev proxy) |
| `SEMESTER_OS_OUTLOOK_ICS_URL` | `calendar_feeds.outlook` |
| `SEMESTER_OS_BRIGHTSPACE_ICS_URL` | `calendar_feeds.brightspace` |
| `SEMESTER_OS_DB` | SQLite path (default `data/semester.db`) |
| `SEMESTER_OS_CLAUDE_BIN` | Claude Code CLI path, if not on PATH |
| `SEMESTER_OS_PYTHON` | Launcher: Python used to run itself and create the venv |
| `SEMESTER_OS_NO_UV` | Launcher: `1` uses pip even if uv is installed |
| `SEMESTER_OS_NO_BROWSER` | Launcher: `1` never opens a browser |
| `NO_COLOR` | Launcher: plain output |

## Files the app manages

In `data/`, gitignored. Do not edit by hand.

| File | What |
| --- | --- |
| `data/semester.db` | Courses, assignments, grades, todos, notes |
| `data/.semester_os_token` | API token |
| `data/.calendar_feed.json` | Calendar feed secret |
| `data/.google_oauth_client.json`, `data/.google_token.json` | Google Calendar, if connected |
| `data/logs/` | `server.log`, `setup.log` |

Back up `data/` and `config.yaml` together.
