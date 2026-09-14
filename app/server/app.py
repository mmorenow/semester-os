"""Semester OS API: the built SPA plus a JSON API over the local SQLite database.

Loopback only; host allowlist, token header and same-origin checks (see security.py).
Run from the repo root: `app/server/.venv/bin/python app/server/app.py`.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field

import calendar_feed
import config
import db
import onboarding
import runner
import school
import school_gcal
import school_ics
import school_notes
import security
from db import REPO_ROOT, get_db, now_iso

DIST_DIR = REPO_ROOT / "app" / "web" / "dist"

NO_UI_HINT = f"""Semester OS

The API is running on http://{security.HOST}:{security.PORT} but the user interface
has not been built yet, so there is nothing to show at this address.

Build it once, from the repository root:

    cd app/web
    npm ci
    npm run build

Then reload this page. The API is already usable in the meantime, for example:

    curl http://{security.HOST}:{security.PORT}/api/health
"""

LOG = logging.getLogger("semester_os.calendar")

# Delay before the first calendar pass, so it does not compete with the first page load.
CALENDAR_FIRST_RUN_DELAY_SECONDS = 5


async def calendar_refresh_loop() -> None:
    """Refresh both ICS feeds, then Google if connected, forever.

    Every failure is caught (a dead background task would silently stop the
    calendar); only cancellation escapes. Blocking work runs in a worker thread.
    """
    try:
        await asyncio.sleep(CALENDAR_FIRST_RUN_DELAY_SECONDS)
        while True:
            try:
                await asyncio.to_thread(school_ics.sync_all)
            except Exception:  # noqa: BLE001 - a feed must never take the app down
                LOG.exception("The ICS refresh failed.")
            try:
                await asyncio.to_thread(school_gcal.sync_if_connected)
            except Exception:  # noqa: BLE001 - nor may Google
                LOG.exception("The Google Calendar refresh failed.")
            await asyncio.sleep(school_ics.REFRESH_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    security.load_or_create_token()
    runner.requeue_interrupted_actions()
    # Fail the notes whose runs were just requeued as failed; they still say 'running'.
    school_notes.reconcile()
    calendar_task = asyncio.create_task(calendar_refresh_loop())
    try:
        yield
    finally:
        calendar_task.cancel()
        try:
            await calendar_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Semester OS",
    description="Local-first semester dashboard: courses, schedule, assignments, grades and notes.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

_ALLOWED_ADDRESSES = f"{security.HOST}:{security.PORT} or localhost:{security.PORT}"
_HOME_URL = f"http://{security.HOST}:{security.PORT}"


# ---------------------------------------------------------------------------
# Middleware: host allowlist and same-origin checks. No CORS middleware, on purpose.
# ---------------------------------------------------------------------------

@app.middleware("http")
async def guard(request: Request, call_next):
    # The feed is decided first: the only tokenless path, and all a public address may reach.
    admission = calendar_feed.admit(request.method, request.url.path, request.headers)
    if admission == calendar_feed.ADMIT_FEED:
        return await call_next(request)
    if admission == calendar_feed.ADMIT_HIDDEN:
        return JSONResponse(status_code=404, content={"detail": "Not found."})

    if not security.host_is_allowed(request.headers.get("host")):
        return JSONResponse(
            status_code=403,
            content={
                "detail": (
                    f"Semester OS only answers requests addressed to {_ALLOWED_ADDRESSES}."
                )
            },
        )

    if request.method.upper() in security.MUTATING_METHODS:
        if not security.origin_is_same(
            request.headers.get("origin"), request.headers.get("referer")
        ):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": (
                        f"Cross origin requests are not allowed. Open Semester OS at "
                        f"{_HOME_URL} and try again."
                    )
                },
            )

    return await call_next(request)


def require_token(
    x_semesteros_token: str | None = Header(default=None, alias=security.TOKEN_HEADER),
) -> None:
    if not security.token_is_valid(x_semesteros_token):
        raise HTTPException(
            status_code=401,
            detail=(
                f"Missing or invalid {security.TOKEN_HEADER} header. The web app reads the "
                "token from GET /api/bootstrap; a script can read it from "
                "data/.semester_os_token."
            ),
        )


@app.exception_handler(school.SchoolError)
async def school_error_handler(request: Request, exc: school.SchoolError) -> JSONResponse:
    """Same JSON error shape; bad enum values and dates answer 422, as the frontend expects."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class AssignmentPatch(BaseModel):
    """Manual assignment edits. `model_fields_set` tells an explicit null from an omission."""

    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    grade_points: float | None = None
    grade_max: float | None = None
    notes: str | None = None
    # Only meaningful next to a timed due_at; see school.plan_assignment_block.
    ends_at: str | None = None
    location: str | None = None


class AnnouncementPatch(BaseModel):
    """Whether an announcement has been read."""

    model_config = ConfigDict(extra="forbid")

    seen: int


class TodoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    course_id: int | None = None
    assignment_id: int | None = None
    due_at: str | None = None


class TodoPatch(BaseModel):
    """Tick, rename or reschedule. `model_fields_set` tells an explicit null from an omission."""

    model_config = ConfigDict(extra="forbid")

    done: bool | None = None
    title: str | None = None
    due_at: str | None = None


class NoteCreate(BaseModel):
    """A note's text; status, run and proposal are server-owned."""

    model_config = ConfigDict(extra="forbid")

    text: str


class GcalSyncRequest(BaseModel):
    """Targets to run (checked in school_gcal); dry_run plans without writing."""

    model_config = ConfigDict(extra="forbid")

    targets: list[str] = Field(default_factory=lambda: list(school_gcal.SYNC_TARGETS))
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _validate_enum(values: Iterable[str], allowed: Iterable[str], field: str) -> list[str]:
    allowed_set = set(allowed)
    result = []
    for value in values:
        if value not in allowed_set:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown {field} '{value}'. Valid values: {', '.join(sorted(allowed_set))}.",
            )
        result.append(value)
    return result


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict[str, Any]:
    """Liveness, plus whether the Claude Code CLI is installed (Notes needs it)."""
    with get_db() as conn:
        conn.execute("SELECT 1").fetchone()
    return {
        "ok": True,
        "app": "semester-os",
        "claude_cli": runner.claude_cli_available(),
    }


@app.get("/api/bootstrap")
def bootstrap(request: Request) -> dict[str, str]:
    if not security.origin_is_same(
        request.headers.get("origin"), request.headers.get("referer")
    ):
        raise HTTPException(
            status_code=403,
            detail=f"The API token is only handed to pages served from {_HOME_URL}.",
        )
    return {"token": security.load_or_create_token()}


@app.get("/api/config", dependencies=[Depends(require_token)])
def get_config() -> dict[str, Any]:
    """Public config. Feed URLs are credentials: only whether each is set is exposed."""
    return config.public_view()


# ---------------------------------------------------------------------------
# Agent runs: read and cancel only. Runs are created by the endpoint that owns
# their payload (e.g. POST /api/school/notes).
# ---------------------------------------------------------------------------

def _fetch_action(conn, action_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No run with id {action_id}.")
    return db.action_to_dict(row)


@app.get("/api/actions", dependencies=[Depends(require_token)])
def list_actions(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    """The most recent runs, newest first, optionally narrowed by status."""
    statuses = _validate_enum(_csv(status), db.ACTION_STATUSES, "run status")
    where_sql = "1=1"
    params: list[Any] = []
    if statuses:
        where_sql = f"status IN ({', '.join('?' for _ in statuses)})"
        params.extend(statuses)
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM actions WHERE {where_sql} ORDER BY id DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        total = int(
            conn.execute(f"SELECT COUNT(*) FROM actions WHERE {where_sql}", params).fetchone()[0]
        )
    return {"items": [db.action_to_dict(row) for row in rows], "total": total}


@app.get("/api/actions/{action_id}", dependencies=[Depends(require_token)])
def get_action(action_id: int) -> dict[str, Any]:
    with get_db() as conn:
        return _fetch_action(conn, action_id)


@app.post("/api/actions/{action_id}/cancel", dependencies=[Depends(require_token)])
def cancel_action(action_id: int) -> dict[str, Any]:
    """Stop a pending or running run. The note it was reading is failed with the reason."""
    with get_db() as conn:
        action = _fetch_action(conn, action_id)

    if action["status"] in ("done", "failed", "cancelled"):
        raise HTTPException(
            status_code=400,
            detail=f"This run already finished with status '{action['status']}'.",
        )

    runner.cancel(action_id, action["status"])

    with get_db() as conn:
        # Set the status here too, in case the worker died before writing it.
        current = _fetch_action(conn, action_id)
        if current["status"] in ("pending", "running"):
            conn.execute(
                "UPDATE actions SET status = 'cancelled', error = ?, finished_at = ? WHERE id = ?",
                ("Cancelled from Semester OS.", now_iso(), action_id),
            )
            current = _fetch_action(conn, action_id)
    school_notes.reconcile()
    return current


# ---------------------------------------------------------------------------
# School. Nothing here deletes rows.
# ---------------------------------------------------------------------------

@app.get("/api/school/courses", dependencies=[Depends(require_token)])
def school_courses() -> dict[str, Any]:
    """Every course of the term, with its meetings and its platforms attached."""
    return {"courses": school.list_courses()}


@app.get("/api/school/courses/{course_id}", dependencies=[Depends(require_token)])
def school_course(course_id: int) -> dict[str, Any]:
    """One course plus a computed grade_summary (unknown bucket splits stay in remaining_pct)."""
    return school.get_course(course_id)


@app.get("/api/school/projection", dependencies=[Depends(require_token)])
def school_projection(course_id: int, target_pct: float) -> dict[str, Any]:
    """The average remaining work needs to reach target_pct. 422 outside 0-110 or unknown course."""
    return school.projection(course_id, target_pct)


@app.get("/api/school/schedule", dependencies=[Depends(require_token)])
def school_schedule(start: str | None = None, end: str | None = None) -> dict[str, Any]:
    """Sessions expanded from weekly meetings; inclusive YYYY-MM-DD bounds, capped at 120 days."""
    return {"events": school.expand_schedule(start, end)}


@app.get("/api/school/assignments", dependencies=[Depends(require_token)])
def school_assignments(
    course_id: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """The work, nearest deadline first, with undated items at the end."""
    return {"assignments": school.list_assignments(course_id=course_id, status=status)}


@app.get("/api/school/assignments/{assignment_id}", dependencies=[Depends(require_token)])
def school_assignment(assignment_id: int) -> dict[str, Any]:
    """One assignment, whole. 404 when there is no such row."""
    return school.get_assignment(assignment_id)


@app.patch("/api/school/assignments/{assignment_id}", dependencies=[Depends(require_token)])
def patch_school_assignment(assignment_id: int, patch: AssignmentPatch) -> dict[str, Any]:
    """Partial update. A grade promotes pending work to 'graded' unless a status was also sent.

    ends_at needs a timed due_at and must be after it.
    """
    given = patch.model_fields_set
    return school.update_assignment(
        assignment_id,
        status=patch.status,
        grade_points=patch.grade_points,
        grade_max=patch.grade_max,
        notes=patch.notes,
        ends_at=patch.ends_at,
        location=patch.location,
        status_given="status" in given,
        grade_points_given="grade_points" in given,
        grade_max_given="grade_max" in given,
        notes_given="notes" in given,
        ends_at_given="ends_at" in given,
        location_given="location" in given,
    )


@app.get("/api/school/announcements", dependencies=[Depends(require_token)])
def school_announcements(
    course_id: int | None = None,
    seen: int | None = None,
) -> dict[str, Any]:
    """What the courses have said, newest first, undated last."""
    return {"announcements": school.list_announcements(course_id=course_id, seen=seen)}


@app.patch("/api/school/announcements/{announcement_id}", dependencies=[Depends(require_token)])
def patch_school_announcement(announcement_id: int, patch: AnnouncementPatch) -> dict[str, Any]:
    """Mark one announcement read, or put it back to unread."""
    return school.set_announcement_seen(announcement_id, patch.seen)


@app.get("/api/school/todos", dependencies=[Depends(require_token)])
def school_todos() -> dict[str, Any]:
    """Open work first, each group by deadline, undated last."""
    return {"todos": school.list_todos()}


@app.post("/api/school/todos", dependencies=[Depends(require_token)], status_code=201)
def create_school_todo(body: TodoCreate) -> dict[str, Any]:
    """Add one thing to do. Typed by a person, so its origin is 'manual'."""
    return school.create_todo(
        body.title,
        course_id=body.course_id,
        assignment_id=body.assignment_id,
        due_at=body.due_at,
    )


@app.patch("/api/school/todos/{todo_id}", dependencies=[Depends(require_token)])
def patch_school_todo(todo_id: int, patch: TodoPatch) -> dict[str, Any]:
    """Tick, rename or reschedule a todo. Ticking sets completed_at; un-ticking clears it."""
    given = patch.model_fields_set
    return school.update_todo(
        todo_id,
        done=patch.done,
        title=patch.title,
        due_at=patch.due_at,
        title_given="title" in given,
        due_at_given="due_at" in given,
    )


# ---------------------------------------------------------------------------
# School: notes. A note starts an agent whose changeset is validated and stored
# as a proposal; nothing in the semester changes until POST .../apply.
# ---------------------------------------------------------------------------

@app.get("/api/school/notes", dependencies=[Depends(require_token)])
def school_notes_list() -> dict[str, Any]:
    """Every note, newest first; notes whose run died are failed on the way through."""
    return {"notes": school_notes.list_notes()}


@app.post("/api/school/notes", dependencies=[Depends(require_token)], status_code=201)
def create_school_note(body: NoteCreate) -> dict[str, Any]:
    """Store a note and start its agent run; returns at once. 503, writing nothing, without the CLI.

    Order matters: note row first (text survives failures), action attached before submit.
    """
    if not runner.claude_cli_available():
        # Refused before the row exists, so no note sits failed through no fault of the student.
        raise HTTPException(status_code=503, detail=runner.CLI_MISSING_ERROR)
    note = school_notes.create_note(body.text)
    action_id = runner.create_action("school_note", {"note_id": note["id"]})
    note = school_notes.attach_action(note["id"], action_id)
    runner.submit(action_id)
    return note


@app.get("/api/school/notes/{note_id}", dependencies=[Depends(require_token)])
def school_note(note_id: int) -> dict[str, Any]:
    """One note, whole. 404 when there is no such row."""
    return school_notes.get_note(note_id)


@app.post("/api/school/notes/{note_id}/apply", dependencies=[Depends(require_token)])
def apply_school_note(note_id: int) -> dict[str, Any]:
    """Apply a proposal, then push to Google. 409 unless 'proposed'; revalidated, 422 writes nothing.

    A Google failure never fails the request; it is reported in the note's `gcal` field.
    """
    return school_notes.apply_note(note_id)


@app.post("/api/school/notes/{note_id}/discard", dependencies=[Depends(require_token)])
def discard_school_note(note_id: int) -> dict[str, Any]:
    """Decline a proposal. Only from 'proposed', and the row stays where it is."""
    return school_notes.discard_note(note_id)


# ---------------------------------------------------------------------------
# School: calendar. Outlook/Brightspace ICS and Google primary are read into
# external_events (school_ics); the semester is projected onto Google primary
# (school_gcal). These endpoints trigger what the background loop does anyway.
# ---------------------------------------------------------------------------

@app.get("/api/school/external-events", dependencies=[Depends(require_token)])
def school_external_events(
    start: str | None = None,
    end: str | None = None,
    source: str | None = None,
    include_inactive: bool = False,
) -> dict[str, Any]:
    """Occurrences in a window, campus local time, from every source (school_events as 'notes').

    Inclusive YYYY-MM-DD bounds, capped at 120 days; unknown `source` is 422.
    """
    return {
        "events": school_ics.list_external_events(
            start, end, source=source, include_inactive=include_inactive
        )
    }


@app.get("/api/school/events", dependencies=[Depends(require_token)])
def school_events(
    start: str | None = None,
    end: str | None = None,
    include_cancelled: bool = False,
) -> dict[str, Any]:
    """One-off school_events, raw (UTC instants or bare dates), optionally bounded on start_at."""
    return {"events": school.list_events(start, end, include_cancelled=include_cancelled)}


@app.post("/api/school/sync/ics", dependencies=[Depends(require_token)])
def school_sync_ics() -> dict[str, Any]:
    """Read both feeds now. A failed feed reports ok = false and why; the request never fails."""
    return school_ics.sync_all()


@app.get("/api/school/sync/status", dependencies=[Depends(require_token)])
def school_sync_status() -> dict[str, Any]:
    """`ics`: last run per external_events source (gcal included). `gcal`: the connection itself."""
    return {
        "ics": {**school_ics.sync_status(), db.GCAL_SOURCE: school_gcal.pull_status()},
        "gcal": school_gcal.status(),
    }


@app.get("/api/school/gcal/status", dependencies=[Depends(require_token)])
def school_gcal_status() -> dict[str, Any]:
    """Configured, connected, account and calendar ids. No OAuth client means configured = false."""
    return school_gcal.status()


@app.post("/api/school/gcal/connect", dependencies=[Depends(require_token)])
def school_gcal_connect() -> dict[str, Any]:
    """Return the consent URL with a single-use, in-memory state valid for ten minutes."""
    return {"auth_url": school_gcal.auth_url()}


# Token exempt: Google's redirect is a top-level navigation that cannot carry our header.
# The single-use state replaces the token (403 otherwise); the host allowlist still applies.
@app.get("/api/school/gcal/callback", include_in_schema=False)
def school_gcal_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if not school_gcal.consume_state(state):
        raise HTTPException(
            status_code=403,
            detail=(
                "This authorization link is not one this server issued, or it has already "
                "been used. Press Connect in Semester OS and try again."
            ),
        )

    if error:
        # Denied is an ordinary outcome; clear any stale error.
        school_gcal.record_error(None)
        return RedirectResponse(school_gcal.DENIED_REDIRECT, status_code=303)
    if not code:
        school_gcal.record_error("Google sent the browser back without an authorization code.")
        return RedirectResponse(school_gcal.ERROR_REDIRECT, status_code=303)

    try:
        school_gcal.exchange_code(code)
    except school_gcal.GcalError as exc:
        # Stored for the status endpoint; the redirect carries no detail.
        school_gcal.record_error(exc.detail)
        return RedirectResponse(school_gcal.ERROR_REDIRECT, status_code=303)

    return RedirectResponse(school_gcal.SUCCESS_REDIRECT, status_code=303)


@app.post("/api/school/gcal/sync", dependencies=[Depends(require_token)])
def school_gcal_sync(body: GcalSyncRequest | None = None) -> dict[str, Any]:
    """Run Google targets now (all when no body); results under "results" and top-level by name.

    The first real run of a writing target enables background and note pushes to primary.
    """
    body = body or GcalSyncRequest()
    results = school_gcal.sync(body.targets, dry_run=body.dry_run)
    return {"results": results, **results}


# ---------------------------------------------------------------------------
# Calendar feed. GET /calendar/{secret}.ics takes no token (calendar apps send no
# headers of ours); the 256-bit path secret replaces it, and a wrong one is 404.
# ---------------------------------------------------------------------------

calendar_feed.install_log_redaction()


class CalendarFeedPublicUrl(BaseModel):
    """The opt-in public origin a tunnel gives the student, or null to remove it."""

    model_config = ConfigDict(extra="forbid")

    public_base_url: str | None = None


@app.api_route("/calendar/{secret}.ics", methods=["GET", "HEAD"], include_in_schema=False)
def calendar_feed_ics(secret: str, request: Request) -> Response:
    """The feed itself. 404 for any secret but the current one."""
    if not calendar_feed.secret_matches(secret):
        raise HTTPException(status_code=404, detail="Not found.")

    body, meta = calendar_feed.render()
    via = "local" if security.host_is_allowed(request.headers.get("host")) else "public"
    if calendar_feed.came_through_proxy(request.headers):
        via = "public"
    calendar_feed.record_fetch(request.headers.get("user-agent"), via)

    headers = {
        "ETag": meta["etag"],
        # No shared caching (tunnel CDNs included), no indexing, no referrer leaks.
        "Cache-Control": "private, no-cache",
        "Content-Disposition": 'inline; filename="semester-os.ics"',
        "X-Content-Type-Options": "nosniff",
        "X-Robots-Tag": "noindex, nofollow",
        "Referrer-Policy": "no-referrer",
    }
    if meta["etag"] in (request.headers.get("if-none-match") or ""):
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="text/calendar; charset=utf-8", headers=headers)


@app.get("/api/calendar-feed", dependencies=[Depends(require_token)])
def calendar_feed_status() -> dict[str, Any]:
    """The feed links, what the feed covers, and which calendar apps read it lately."""
    return calendar_feed.describe()


@app.post("/api/calendar-feed/rotate", dependencies=[Depends(require_token)])
def calendar_feed_rotate() -> dict[str, Any]:
    """Issue a new secret. Every subscription made with the old link stops updating."""
    calendar_feed.rotate_secret()
    return calendar_feed.describe()


@app.put("/api/calendar-feed/public-url", dependencies=[Depends(require_token)])
def calendar_feed_public_url(body: CalendarFeedPublicUrl) -> dict[str, Any]:
    """Save or remove the opt-in public address. 422 for anything but an https origin."""
    calendar_feed.set_public_base_url(body.public_base_url)
    return calendar_feed.describe()


# ---------------------------------------------------------------------------
# Onboarding: syllabi and links in, proposals out. Logic lives in onboarding.py.
# ---------------------------------------------------------------------------


class OnboardingLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str


class OnboardingManualCourse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_code: str
    course_title: str | None = None


class OnboardingProposal(BaseModel):
    """A proposal as the review editor holds it. Its keys are checked in onboarding.py."""

    model_config = ConfigDict(extra="forbid")

    proposal: dict[str, Any]


class OnboardingApply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal: dict[str, Any] | None = None


@app.get("/api/onboarding/sources", dependencies=[Depends(require_token)])
def onboarding_sources() -> dict[str, Any]:
    """Every source, newest first, after rescanning syllabi/. `skipped` lists unreadable files."""
    return onboarding.list_sources()


@app.get("/api/onboarding/sources/{source_id}", dependencies=[Depends(require_token)])
def onboarding_source(source_id: int) -> dict[str, Any]:
    return onboarding.get_source(source_id)


@app.post("/api/onboarding/uploads", dependencies=[Depends(require_token)], status_code=201)
async def onboarding_upload(request: Request, filename: str = Query(..., max_length=255)) -> dict[str, Any]:
    """Save one file (raw body) into syllabi/ and queue it.

    Raw bytes, not multipart: no form parser to trust, and the size cap is enforced while streaming.
    """
    limit = onboarding.MAX_UPLOAD_BYTES
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail="The file is larger than 15 MB. A syllabus is not.")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail="The file is larger than 15 MB. A syllabus is not.")
        chunks.append(chunk)
    return await asyncio.to_thread(onboarding.save_upload, filename, b"".join(chunks))


@app.post("/api/onboarding/links", dependencies=[Depends(require_token)], status_code=201)
def onboarding_link(body: OnboardingLink) -> dict[str, Any]:
    """A course website to read. https only; the same link twice is one source."""
    return onboarding.add_link(body.url)


@app.post("/api/onboarding/manual", dependencies=[Depends(require_token)], status_code=201)
def onboarding_manual(body: OnboardingManualCourse) -> dict[str, Any]:
    """Start a course typed in by hand: an empty proposal to finish in the editor."""
    return onboarding.create_manual(body.course_code, body.course_title)


@app.post("/api/onboarding/sources/{source_id}/read", dependencies=[Depends(require_token)])
def onboarding_read(source_id: int) -> dict[str, Any]:
    """Start the agent run that reads one source. 503 without the Claude Code CLI."""
    return onboarding.start_reading(source_id)


@app.post("/api/onboarding/read-all", dependencies=[Depends(require_token)])
def onboarding_read_all() -> dict[str, Any]:
    """Read every queued source. Two run at once; the rest wait their turn."""
    return {"sources": onboarding.start_all()}


@app.patch("/api/onboarding/sources/{source_id}/proposal", dependencies=[Depends(require_token)])
def onboarding_edit(source_id: int, body: OnboardingProposal) -> dict[str, Any]:
    """Store the student's edits. Validated like the agent's answer; only while proposed."""
    return onboarding.update_proposal(source_id, body.proposal)


@app.post("/api/onboarding/sources/{source_id}/apply", dependencies=[Depends(require_token)])
def onboarding_apply(source_id: int, body: OnboardingApply | None = None) -> dict[str, Any]:
    """Confirm and add the course; 422 writes nothing. An existing code updates, keeping manual edits."""
    return onboarding.apply_source(source_id, body.proposal if body else None)


@app.post("/api/onboarding/sources/{source_id}/discard", dependencies=[Depends(require_token)])
def onboarding_discard(source_id: int) -> dict[str, Any]:
    """Decline a proposal. The row and what was read stay."""
    return onboarding.discard_source(source_id)


# ---------------------------------------------------------------------------
# Static SPA. Declared last so every API route wins the match.
# ---------------------------------------------------------------------------

@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith("api/") or full_path == "api":
        raise HTTPException(status_code=404, detail="Unknown API endpoint.")

    index = DIST_DIR / "index.html"
    if not index.is_file():
        return PlainTextResponse(NO_UI_HINT, status_code=200)

    if full_path:
        root = DIST_DIR.resolve()
        candidate = (root / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)

    return FileResponse(index)


if __name__ == "__main__":
    import uvicorn

    # Loopback only, by design.
    uvicorn.run(app, host=security.HOST, port=security.PORT)
