# Contributing to Semester OS

Server in `app/server` (FastAPI), web app in `app/web` (Vite, React). Fixes, docs and support for more schools are welcome.

## Development setup

Python 3.11+ and Node.js 20+ (`.nvmrc` pins Node 22, `.python-version` pins Python 3.12).

```sh
./semester-os setup --dev   # venv + pytest, npm ci, web build
./semester-os doctor
```

`make setup`, `make test` and `make start` mirror the launcher.

| Loop | Command | Notes |
| --- | --- | --- |
| Backend | `make dev-server` | uvicorn with `--reload` on 127.0.0.1:8790 |
| Frontend | `make dev-web` | <http://localhost:5173>, proxies `/api` to 8790 (or `SEMESTER_OS_PORT`); see `app/web/vite.config.ts` |
| Production build | `./semester-os update && ./semester-os start` | What a student runs |

If you also use it for real, develop with `SEMESTER_OS_PORT=8791 SEMESTER_OS_DB=/tmp/semester-dev.db`.

## Run the demo

`scripts/seed_demo.py` fills an empty install with an invented week-7 semester: five courses, graded work, an exam, imported events, Notes and a pending syllabus.

```sh
./semester-os setup --dev
app/server/.venv/bin/python scripts/seed_demo.py   # --today 2026-10-05 pins the date
./semester-os start
```

- No model calls, no network, Google push off.
- Writes `data/semester.db` (or `SEMESTER_OS_DB`) and one file in `syllabi/`; refuses if either has data (`--force` overrides). Use a separate clone.
- Remove it: delete `data/semester.db*` and `syllabi/cs2100-syllabus.md`.

### Regenerating screenshots and GIFs

`scripts/capture/` builds `docs/assets/` from a seeded temp copy of the repo, offline, with `fake_claude.py` standing in for the CLI. Your data is untouched. Needs a built web app, ffmpeg and Playwright (outside the app):

```sh
cd app/web && npm run build && cd ../..
mkdir -p /tmp/pw && npm install --prefix /tmp/pw playwright@1.62.0
npx --prefix /tmp/pw playwright install chromium-headless-shell
app/server/.venv/bin/python scripts/capture/capture.py --playwright /tmp/pw
```

Flags: `--only shots|notes|onboarding`, `--today YYYY-MM-DD`, `--keep` (keep temp folder).

## Tests

```sh
app/server/.venv/bin/python -m pytest tests -q   # or: make test
cd app/web && npm run build                       # when the web app changed (strict tsc + vite)
```

CI runs both plus a launcher smoke test on Ubuntu and macOS, Python 3.11 and 3.13.

- **No network.** `tests/conftest.py` blocks non-loopback `urlopen` and hides Google credentials. Fake the call; never weaken the guard.
- **No real data.** Use `tests/fixtures.py`. Never commit a real syllabus, feed URL or `data/`.
- **No model calls.** Use canned agent replies, as in `tests/test_school_notes.py`.
- **Throwaway databases.** Point `db.DB_PATH` at a temp file.
- `unittest.TestCase` classes, one file per module, with a docstring saying what it protects.

## Code style

No formatter in CI yet; match the surrounding code.

**Python**

- `from __future__ import annotations`, type hints everywhere, 4 spaces, ~110 columns.
- Closed vocabularies: unknown keys and values are refused with a message naming them (see `app/server/config.py`).
- Additive data: nothing is deleted, retiring is a status. Timestamps are ISO 8601 UTC ending in `Z`.
- Subprocesses take an argument list, never `shell=True`; user text never enters a command line.
- HTTP via `urllib`, no client dependency. Blocking work in a worker thread.
- Secrets (feed URLs, tokens) never reach logs or errors.
- Bind to `127.0.0.1` only. No flag to change it.

**TypeScript and React**

- Strict TS, 2 spaces, single quotes, no semicolons, `@/` alias.
- Features in `src/features/<feature>/`, primitives in `src/components/ui` (shadcn/ui), helpers in `src/lib`.
- Server state through TanStack Query hooks in `src/lib/*-queries.ts`.
- Tailwind v4, Phosphor icons. Read [DESIGN.md](DESIGN.md) before touching color, type or spacing.

**Everywhere:** English only. No university-specific details in code; they belong in `config.yaml` or the database.

## Releases

Build output is gitignored. A release is a tag plus an archive including `app/web/dist` built from it, so setup works without Node. Move **Unreleased** changelog entries under the new version.

## Pull requests

1. Open an issue first for anything bigger than a small fix.
2. One change per PR. Update docs, and add an **Unreleased** line to `CHANGELOG.md` if users would notice.
3. Tests and web build pass locally.

Security problems go through [SECURITY.md](SECURITY.md), not issues. Contributions are licensed under the [MIT License](LICENSE).
