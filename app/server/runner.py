"""Launches the Claude Code CLI for 'school_note' and 'syllabus_import' runs.

Argument list only (never shell=True), a closed set of action types with fixed
tools, no --dangerously-skip-permissions, 600 s timeout, two concurrent runs.
Runs from the repo root so --agent finds .claude/agents/. The CLI is optional.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import threading
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import db
import onboarding
import school_notes
from db import LOCAL_TZ_NAME, REPO_ROOT, action_to_dict, encode_json, get_db, now_iso

MAX_CONCURRENT_RUNS = 2
RUN_TIMEOUT_SECONDS = 600

# Names a binary off PATH; never parsed as a command line.
CLAUDE_BIN_ENV = "SEMESTER_OS_CLAUDE_BIN"

CLI_MISSING_ERROR = (
    "Notes need the Claude Code CLI, and it is not installed on this machine (or "
    "not on the PATH of the process running Semester OS). Install it from "
    "https://code.claude.com/docs/en/overview, run `claude` once to sign "
    "in, then restart Semester OS. Everything else in the app works without it."
)

# type -> (agent name, allowed tools, human label)
ACTION_TYPES: dict[str, dict[str, str]] = {
    "school_note": {
        "agent": "school-editor",
        "tools": "Read",
        "label": "Note",
    },
    # "tools" is the file case; a link gets WebFetch instead, never both
    # (onboarding.tools_for).
    "syllabus_import": {
        "agent": "course-importer",
        "tools": "Read",
        "label": "Syllabus",
    },
}

ACTION_TYPE_NAMES = tuple(ACTION_TYPES.keys())

_slots = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)
_registry_lock = threading.Lock()
_processes: dict[int, subprocess.Popen] = {}
_cancelled: set[int] = set()


# --------------------------------------------------------------------------
# Prompt templates
# --------------------------------------------------------------------------

CHANGESET_TEMPLATE = """```json
{
  "ops": [
    {"op": "update_assignment", "assignment_id": 41,
     "set": {"due_at": "2026-09-11T23:59:00Z"},
     "summary": "Move HW 2 (CS 180) due date to Fri Sep 11, 11:59 PM"}
  ],
  "commentary": "One assignment matched: HW 2 in CS 180, the only homework due this week."
}
```"""


def school_note_prompt(note_text: str) -> str:
    """Self-contained school-editor prompt: every nameable id plus the current local instant.

    The instant is stated so relative dates ("Friday") resolve against it, not the model's guess.
    """
    now = datetime.now(ZoneInfo(LOCAL_TZ_NAME))
    return (
        "Turn the note below into a changeset for a student's semester. The note "
        "was typed by the student, in any language, and it is a fact "
        "about their courses or their calendar: a deadline that moved, work that "
        "exists, work that is done, a meeting to put on the calendar, an event "
        "that moved or was called off. You do not write anything anywhere. You answer with JSON and a "
        "server validates it and asks the student to confirm it.\n\n"
        f"THE NOTE, VERBATIM\n{note_text}\n\n"
        f"RIGHT NOW\n{now.strftime('%A %Y-%m-%d %H:%M')} local time, timezone "
        f"{LOCAL_TZ_NAME}. Every relative date in the note resolves against this "
        "instant and against nothing else. 'Friday' is the next Friday from this "
        "date. If a note says a time without a date, or a date without a year, "
        "resolve it to the nearest sensible instant in the current semester and "
        "say in the commentary which reading you took.\n\n"
        f"{school_notes.state_context()}\n\n"
        "THE OPERATIONS YOU MAY USE, AND NOTHING ELSE\n"
        '- {"op": "create_assignment", "course_id": int, "title": str, "kind": '
        'str|null, "due_at": str|null, "ends_at": str|null, "location": str|null, '
        '"points": number|null, "url": str|null, "notes": str|null, "summary": str}\n'
        '- {"op": "update_assignment", "assignment_id": int, "set": {...}, '
        '"summary": str} where set may name any of title, kind, due_at, points, '
        "status, notes, grade_points, grade_max, ends_at, location\n"
        '- {"op": "create_todo", "title": str, "course_id": int|null, '
        '"assignment_id": int|null, "due_at": str|null, "summary": str}\n'
        '- {"op": "update_todo", "todo_id": int, "set": {...}, "summary": str} '
        "where set may name any of title, due_at, done\n"
        '- {"op": "create_event", "title": str, "start_at": str, "end_at": '
        'str|null, "all_day": bool, "location": str|null, "course_id": int|null, '
        '"notes": str|null, "summary": str}\n'
        '- {"op": "update_event", "event_id": int, "set": {...}, "summary": str} '
        "where set may name any of title, start_at, end_at, all_day, location, "
        "course_id, notes\n"
        '- {"op": "cancel_event", "event_id": int, "summary": str} which marks the '
        "event cancelled\n"
        '- {"op": "comment", "summary": str} which writes nothing\n\n'
        "VALUES\n"
        f"- kind is one of: {', '.join(db.ASSIGNMENT_KINDS)}.\n"
        f"- status is one of: {', '.join(db.ASSIGNMENT_STATUSES)}.\n"
        "- due_at is either a bare YYYY-MM-DD date, which means that whole day, "
        "or an ISO-8601 instant like 2026-09-11T23:59:00Z. Nothing else parses. "
        "A note that gives a clock time gets an instant; a note that gives only a "
        "day gets a date, because turning a day into midnight in some timezone "
        "invents a time nobody stated.\n"
        "- ends_at is the end of a graded block that starts at due_at (an exam "
        "from 20:00 to 22:00): an ISO-8601 instant after due_at, only next to a "
        "due_at that has a clock time.\n"
        "- An event's start_at and end_at are ISO-8601 instants with all_day "
        "false, or bare YYYY-MM-DD dates with all_day true, where end_at is the "
        "last day, inclusive. A timed event with no end_at lasts an hour; an all "
        "day event with no end_at is that one day.\n"
        "- done is true or false.\n"
        "- Every id you name has to appear in the block above. An id that does "
        "not is refused and the whole changeset is thrown away.\n\n"
        "RULES\n"
        "- Never invent a course, an assignment, a todo or a date. If the note "
        "names work you cannot find, and it is clearly new work, create it. If it "
        "names work that should already exist and does not, say so with a comment "
        "op instead of creating something the student did not ask for.\n"
        "- Match an assignment by title similarity AND by course. 'the crypto hw2' "
        "is homework 2 in the cryptography course, not homework 2 in another one.\n"
        "- When two candidates are both plausible, do not pick one. Answer with a "
        "comment op that names both and asks which was meant. A wrong deadline on "
        "the wrong homework is worse than no change at all.\n"
        "- 'I already submitted X' sets that assignment's status to 'submitted'. "
        "It does not set a grade: a submission is not a score.\n"
        "- Exams, quizzes and graded presentations are assignments: due_at is the "
        "start, ends_at the end, location the room. Never put a time or a room in "
        "notes. Meetings, office hours, appointments, study sessions, talks and "
        "anything the student asks to put on the calendar are create_event. A "
        "moved or cancelled event is update_event or cancel_event on the matching "
        "row of SCHEDULED EVENTS, matched by title and date; when two rows could "
        "be meant, answer with a comment op.\n"
        "- Events on the student's personal Google calendar and the weekly class "
        "schedule cannot be changed by a note. Answer with a comment op.\n"
        "- One note usually means one or two operations. If you are producing "
        "more than a handful, you have stopped reading the note.\n"
        "- summary is one short English sentence per op, written for the student "
        "to read before confirming. Name the thing and the change: 'Move HW 2 "
        "(CS 180) due date to Fri Sep 11, 11:59 PM'. It is shown instead of the "
        "JSON, so it has to be true and specific.\n"
        "- The note may be in any language. Your entire answer, summaries and "
        "commentary included, is in English.\n\n"
        "OUTPUT\n"
        "One fenced json block and nothing else that matters. The shape is "
        "exactly this:\n\n"
        f"{CHANGESET_TEMPLATE}\n\n"
        "commentary is where you explain what you matched, which reading you took "
        "of an ambiguous date, and anything you could not resolve. It is prose, "
        "in English, and it is shown to the student next to the operations.\n\n"
        "Do not write to any file, do not touch the database, and do not run any "
        "command. Your reply is the deliverable."
    )


def build_prompt(action_type: str, payload: dict[str, Any] | None) -> str:
    """The prompt for one run. Note text is read from the note row, never from the payload."""
    payload = payload or {}
    if action_type == "school_note":
        note_id = school_notes.note_for_action(payload)
        if note_id is None:
            raise ValueError("A school_note action must carry a note_id in its payload.")
        text = school_notes.note_text(note_id)
        if text is None:
            raise ValueError(f"Note {note_id} no longer exists.")
        return school_note_prompt(text)
    if action_type == "syllabus_import":
        return onboarding.build_prompt(payload)
    raise ValueError(f"Unknown action type: {action_type}")


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------

def claude_binary() -> str | None:
    """Absolute path of the Claude Code CLI, or None when it is not installed."""
    override = os.environ.get(CLAUDE_BIN_ENV)
    if override:
        return shutil.which(override) or (override if os.path.isfile(override) else None)
    return shutil.which("claude")


def claude_cli_available() -> bool:
    return claude_binary() is not None


def build_command(
    binary: str, prompt: str, action_type: str, payload: dict[str, Any] | None = None
) -> list[str]:
    """Build the CLI argument list. Never a shell string."""
    spec = ACTION_TYPES[action_type]
    tools = onboarding.tools_for(payload) if action_type == "syllabus_import" else spec["tools"]
    command = [
        binary,
        "-p",
        prompt,
        "--agent",
        spec["agent"],
        "--output-format",
        "json",
        "--allowedTools",
        tools,
        # --allowedTools only pre-approves; --tools removes every other tool, so
        # user settings cannot widen a run fed untrusted syllabus text.
        "--tools",
        tools,
    ]
    return command


def _update_action(action_id: int, **fields: Any) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [action_id]
    with get_db() as conn:
        conn.execute(f"UPDATE actions SET {assignments} WHERE id = ?", values)


def _load_action(conn: sqlite3.Connection, action_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
    return action_to_dict(row)


def _finish(action_id: int, status: str, result_md: str | None = None, error: str | None = None) -> None:
    _update_action(
        action_id,
        status=status,
        result_md=result_md,
        error=error,
        finished_at=now_iso(),
    )


def _parse_cli_output(stdout: str) -> tuple[str | None, str | None]:
    """Return (result_md, error). The CLI prints one JSON object with -p json."""
    text = (stdout or "").strip()
    if not text:
        return None, "The Claude Code CLI returned no output."
    try:
        parsed = json.loads(text)
    except ValueError:
        # Older or future CLI shapes: keep whatever came back rather than lose it.
        return text, None
    if isinstance(parsed, list):
        parsed = next((item for item in reversed(parsed) if isinstance(item, dict)), {})
    if not isinstance(parsed, dict):
        return text, None
    result = parsed.get("result")
    if parsed.get("is_error"):
        return (result if isinstance(result, str) else None), (
            result if isinstance(result, str) else "The Claude Code CLI reported an error."
        )
    if isinstance(result, str) and result.strip():
        return result, None
    return text, None


def _execute(action_id: int) -> None:
    """Body of a run. Executed on a worker thread, one slot per run."""
    with _slots:
        with _registry_lock:
            if action_id in _cancelled:
                _cancelled.discard(action_id)
                return

        with get_db() as conn:
            action = _load_action(conn, action_id)
        if action is None or action["status"] not in ("pending", "running"):
            return

        action_type = action["type"]
        try:
            prompt = build_prompt(action_type, action.get("payload"))
        except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
            _finish(action_id, "failed", error=f"Could not build the prompt: {exc}")
            return

        binary = claude_binary()
        if binary is None:
            _finish(action_id, "failed", error=CLI_MISSING_ERROR)
            return
        command = build_command(binary, prompt, action_type, action.get("payload"))

        _update_action(action_id, status="running", started_at=now_iso())
        try:
            process = subprocess.Popen(  # noqa: S603 - argument list, never a shell
                command,
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                shell=False,
            )
        except OSError as exc:
            _finish(action_id, "failed", error=f"Could not start the Claude Code CLI: {exc}")
            return

        with _registry_lock:
            _processes[action_id] = process

        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=RUN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            stdout, stderr = process.communicate()
        finally:
            with _registry_lock:
                _processes.pop(action_id, None)
                was_cancelled = action_id in _cancelled
                _cancelled.discard(action_id)

        if was_cancelled:
            _finish(action_id, "cancelled", error="Cancelled while it was running.")
            return
        if timed_out:
            _finish(
                action_id,
                "failed",
                error=f"The agent run exceeded {RUN_TIMEOUT_SECONDS} seconds and was stopped.",
            )
            return
        if process.returncode != 0:
            detail = (stderr or "").strip() or (stdout or "").strip() or "no output"
            _finish(
                action_id,
                "failed",
                error=f"The Claude Code CLI exited with code {process.returncode}: {detail[:2000]}",
            )
            return

        result_md, error = _parse_cli_output(stdout)
        if error:
            _finish(action_id, "failed", result_md=result_md, error=error[:2000])
        else:
            _finish(action_id, "done", result_md=result_md)
            _write_back(action_id)


def _write_back_school_note(action_id: int, action: dict[str, Any]) -> None:
    """Store a finished run as a proposal (never applied here); every failure lands on the note row."""
    note_id = school_notes.note_for_action(action.get("payload"))
    if note_id is None:
        return
    try:
        if not action.get("result_md"):
            school_notes.record_failure(note_id, "The agent run returned no output.")
            return
        school_notes.write_back(note_id, action["result_md"])
    except Exception as exc:  # noqa: BLE001 - reported on the note, never raised
        try:
            school_notes.record_failure(note_id, f"The write-back itself failed: {exc}")
        except Exception:  # noqa: BLE001 - the action row still carries the answer
            pass


def _write_back_syllabus(action_id: int, action: dict[str, Any]) -> None:
    """Store a finished run as a proposal on the source row, or record the failure there."""
    source_id = onboarding.source_for_action(action.get("payload"))
    if source_id is None:
        return
    try:
        if not action.get("result_md"):
            onboarding.record_failure(source_id, "The agent run returned no output.")
            return
        onboarding.write_back(source_id, action["result_md"], action_id=action_id)
    except Exception as exc:  # noqa: BLE001 - reported on the source, never raised
        try:
            onboarding.record_failure(source_id, f"The write-back itself failed: {exc}")
        except Exception:  # noqa: BLE001 - the action row still carries the answer
            pass


def _write_back(action_id: int) -> None:
    """Hand a finished run to whatever owns its result. Never raises."""
    try:
        with get_db() as conn:
            action = _load_action(conn, action_id)
        if not action or action.get("status") != "done":
            return
        if action["type"] == "school_note":
            _write_back_school_note(action_id, action)
        elif action["type"] == "syllabus_import":
            _write_back_syllabus(action_id, action)
    except Exception:  # noqa: BLE001 - the answer already lives on the action row
        pass


def submit(action_id: int) -> None:
    """Start a run. Returns immediately, the request never blocks on a run."""
    thread = threading.Thread(target=_execute, args=(action_id,), name=f"action-{action_id}", daemon=True)
    thread.start()


def cancel(action_id: int, current_status: str) -> bool:
    """Stop a queued, pending or running action. Returns True when something changed."""
    with _registry_lock:
        process = _processes.get(action_id)
        _cancelled.add(action_id)

    if process is not None:
        try:
            process.terminate()
        except OSError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
        return True

    if current_status in ("queued", "pending"):
        _update_action(
            action_id,
            status="cancelled",
            error="Cancelled before it started.",
            finished_at=now_iso(),
        )
        return True

    with _registry_lock:
        _cancelled.discard(action_id)
    return False


def requeue_interrupted_actions() -> None:
    """Mark runs left in flight by a previous process as failed (rows are kept)."""
    with get_db() as conn:
        conn.execute(
            "UPDATE actions SET status = 'failed', error = ?, finished_at = ? "
            "WHERE status IN ('pending', 'running')",
            (
                "Semester OS restarted while this run was in progress. Send the note "
                "again to retry it.",
                now_iso(),
            ),
        )


def create_action(action_type: str, payload: dict[str, Any] | None) -> int:
    """Insert one pending run row and return its id. Submitting it is separate."""
    if action_type not in ACTION_TYPES:
        raise ValueError(f"Unknown action type '{action_type}'.")
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO actions (type, payload, status, created_at) VALUES (?, ?, 'pending', ?)",
            (action_type, encode_json(payload), now_iso()),
        )
        return int(cursor.lastrowid)
