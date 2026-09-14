#!/usr/bin/env python3
"""Regenerate the README screenshots and GIFs in docs/assets/. Development only.

Seeds a demo semester in a temp copy of the repo, serves it offline with a fake Claude CLI,
drives headless Chromium via capture.cjs, and converts recordings to GIFs with ffmpeg.

Requires a built web app, ffmpeg, and Playwright for Node outside the app:
    mkdir -p /tmp/pw && npm install --prefix /tmp/pw playwright@1.62.0
    npx --prefix /tmp/pw playwright install chromium-headless-shell

Usage: app/server/.venv/bin/python scripts/capture/capture.py --playwright /tmp/pw [--only notes --keep]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PYTHON = sys.executable
TIMEZONE = "America/Indiana/Indianapolis"
SCENES = ("shots", "notes", "onboarding")

CONFIG_YAML = """timezone: {timezone}
term: {term}
school_name: Example State University
calendar_feeds:
  outlook: https://outlook.example.edu/owa/calendar/demo/calendar.ics
  brightspace: https://learn.example.edu/d2l/le/calendar/feed/user/feed.ics?token=demo
port: {port}
"""

IGNORED = shutil.ignore_patterns(
    "node_modules", ".venv", "__pycache__", ".pytest_cache", ".git", ".DS_Store", "*.db", "*.db-*",
)

# Canned course-importer answer for examples/syllabi/stat2400-course-page.html.
STAT2400_PROPOSAL = {
    "course_code": "STAT 2400",
    "course_title": "Statistics for Data Science",
    "credit_hours": 3,
    "term": "Fall 2026",
    "instructors": ["Lin Moreau"],
    "meetings": [
        {"kind": "lecture", "days": ["T", "R"], "start_time": "09:00", "duration_min": 75,
         "location": "Marlowe Hall 1255", "start_date": None, "end_date": None, "crn": None},
        {"kind": "pso", "days": ["W"], "start_time": None, "duration_min": None,
         "location": None, "start_date": None, "end_date": None, "crn": None},
    ],
    "platforms": [
        {"platform": "other", "name": "WebAssign", "url": None, "notes": "Homework is completed and submitted here."},
        {"platform": "other", "name": "Piazza", "url": "https://piazza.example.com/stat2400", "notes": "Questions."},
        {"platform": "brightspace", "name": None, "url": None, "notes": "Grades are posted here."},
    ],
    "grading_weights_pct": {"Homework": 20, "Recitation quizzes": 10, "Data project": 15, "Exam 1": 15,
                            "Exam 2": 15, "Final exam": 25},
    "total_points": 1000,
    "grading_scale": None,
    "drop_rules": "The two lowest homework sets are dropped before the homework total is scaled to 200 points.",
    "late_policy": "Late homework is not accepted; WebAssign closes at the deadline.",
    "ai_policy": None,
    "attendance_policy": None,
    "regrade_policy": None,
    "assignments": [
        *[
            {"title": f"Homework {number}", "kind": "hw", "category": "Homework", "due_date": due,
             "due_time": "23:59", "end_time": None, "location": None, "points": None, "weight_pct": None,
             "notes": None}
            for number, due in enumerate(
                ["2026-09-03", "2026-09-10", "2026-09-17", "2026-10-01", "2026-10-08", "2026-10-22",
                 "2026-10-29", "2026-11-12", "2026-11-19", "2026-12-03"],
                start=1,
            )
        ],
        {"title": "Exam 1", "kind": "exam", "category": "Exam 1", "due_date": "2026-09-24", "due_time": "18:30",
         "end_time": "19:45", "location": "Ridgeway Auditorium", "points": 150, "weight_pct": None, "notes": None},
        {"title": "Project proposal", "kind": "project", "category": "Data project", "due_date": "2026-10-22",
         "due_time": None, "end_time": None, "location": None, "points": None, "weight_pct": None,
         "notes": "Due in recitation."},
        {"title": "Exam 2", "kind": "exam", "category": "Exam 2", "due_date": "2026-11-05", "due_time": "18:30",
         "end_time": "19:45", "location": "Ridgeway Auditorium", "points": 150, "weight_pct": None, "notes": None},
        {"title": "Data project report", "kind": "project", "category": "Data project", "due_date": "2026-12-03",
         "due_time": None, "end_time": None, "location": None, "points": None, "weight_pct": None, "notes": None},
        {"title": "Final exam", "kind": "exam", "category": "Final exam", "due_date": None, "due_time": None,
         "end_time": None, "location": None, "points": 250, "weight_pct": None,
         "notes": "During finals week; time and place announced later."},
    ],
    "uncertain": [
        {"field": "meetings[1].start_time", "reason": "Recitation times depend on your section. Check your class schedule."},
        {"field": "meetings[1].location", "reason": "Recitation rooms depend on your section."},
        {"field": "assignments[14].due_date", "reason": "The final exam is scheduled later."},
    ],
}

STAT2400_COMMENTARY = (
    "Read the course page. Lectures meet Tuesday and Thursday at 9:00, and every student also has a Wednesday "
    "recitation whose time and room depend on the section. The course is graded out of 1000 points. Both "
    "evening exams are dated with their room; the final exam is not scheduled yet. The page states its times "
    "in Eastern Time, which is the campus timezone, so nothing was converted."
)


def fenced(document: dict) -> str:
    return "```json\n" + json.dumps(document, indent=2) + "\n```\n"


def capture_day(today: date) -> date:
    """Today on a weekday, else next Monday (a weekend Today has no classes)."""
    return today if today.weekday() < 5 else today + timedelta(days=7 - today.weekday())


def free_port(preferred: int) -> int:
    for port in (preferred, preferred + 1, preferred + 2):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise SystemExit(f"Ports {preferred}-{preferred + 2} are all in use.")


class Workspace:
    """A throwaway copy of the app, and the server running from it."""

    def __init__(self, root: Path, port: int, term: str) -> None:
        self.root = root
        self.repo = root / "repo"
        self.port = port
        self.answers = root / "answers.json"
        self.server: subprocess.Popen | None = None
        self.now: datetime | None = None
        shutil.copytree(REPO_ROOT, self.repo, ignore=IGNORED)
        for name in ("data", "syllabi", "config.yaml", "docs"):
            target = self.repo / name
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        (self.repo / "config.yaml").write_text(
            CONFIG_YAML.format(timezone=TIMEZONE, term=term, port=port), encoding="utf-8"
        )

    def env(self) -> dict[str, str]:
        env = {key: value for key, value in os.environ.items() if not key.startswith("SEMESTER_OS_")}
        env.update({
            "SEMESTER_OS_PORT": str(self.port),
            "SEMESTER_OS_CLAUDE_BIN": str(self.repo / "scripts" / "capture" / "fake_claude.py"),
            "SEMESTER_OS_CAPTURE_ANSWERS": str(self.answers),
            "SEMESTER_OS_NO_BROWSER": "1",
        })
        if self.now is not None:
            env["SEMESTER_OS_CAPTURE_NOW"] = self.now.isoformat()
        return env

    def reset(self) -> None:
        self.stop()
        for name in ("data", "syllabi"):
            shutil.rmtree(self.repo / name, ignore_errors=True)

    def run(self, *args: str) -> str:
        result = subprocess.run(
            [PYTHON, *args], cwd=self.repo, env=self.env(), capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise SystemExit(f"{' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
        return result.stdout

    def start(self) -> None:
        log = open(self.root / "server.log", "a", encoding="utf-8")  # noqa: SIM115 - closed with the process
        self.server = subprocess.Popen(
            [PYTHON, "scripts/capture/demo_server.py"], cwd=self.repo, env=self.env(), stdout=log, stderr=log
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/health", timeout=1) as answer:
                    if answer.status == 200:
                        return
            except OSError:
                time.sleep(0.25)
        raise SystemExit(f"The capture server did not start; see {self.root / 'server.log'}")

    def stop(self) -> None:
        if self.server is not None:
            self.server.terminate()
            try:
                self.server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.server.kill()
            self.server = None

    def query(self, sql: str, *params: object) -> list[tuple]:
        import sqlite3

        with sqlite3.connect(self.repo / "data" / "semester.db") as conn:
            return conn.execute(sql, params).fetchall()


def node(args: argparse.Namespace, workspace: Workspace, scene: str, out: Path, settings: dict) -> None:
    env = {**os.environ, "NODE_PATH": str(Path(args.playwright).resolve() / "node_modules")}
    subprocess.run(
        ["node", str(HERE / "capture.cjs"), scene, f"http://127.0.0.1:{workspace.port}", str(out), json.dumps(settings)],
        env=env,
        check=True,
    )


def to_gif(video: Path, target: Path, *, start: float, fps: int, width: int, speed: float) -> None:
    """WebM to GIF via a two-pass per-clip palette, which keeps UI text crisp."""
    filters = f"trim=start={start:.2f},setpts=(PTS-STARTPTS)/{speed},fps={fps},scale={width}:-1:flags=lanczos"
    palette = video.with_suffix(".palette.png")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", f"{filters},palettegen=stats_mode=diff:max_colors=200",
         str(palette)],
        check=True,
    )
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(palette), "-lavfi",
         f"{filters}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle", "-loop", "0",
         str(target)],
        check=True,
    )
    palette.unlink()


def shrink_png(path: Path) -> None:
    """Palette-compress a PNG with pngquant, else ffmpeg; keeps the smaller file."""
    if shutil.which("pngquant"):
        subprocess.run(["pngquant", "--force", "--skip-if-larger", "--quality", "80-98", "--ext", ".png", str(path)],
                       check=False)
        return
    candidate = path.with_suffix(".pal.png")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vf",
         "split[a][b];[a]palettegen=max_colors=256:stats_mode=full[p];[b][p]paletteuse=dither=none",
         "-pix_fmt", "pal8", "-compression_level", "100", str(candidate)],
        check=True,
    )
    if candidate.stat().st_size < path.stat().st_size:
        candidate.replace(path)
    else:
        candidate.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--playwright", required=True, help="A folder holding node_modules/playwright.")
    parser.add_argument("--out", default=str(REPO_ROOT / "docs" / "assets"))
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--today", help="The day the demo is dated around (default: the next weekday).")
    parser.add_argument("--only", choices=SCENES, action="append", help="Capture only this scene (repeatable).")
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--width", type=int, default=1100, help="GIF width in pixels.")
    parser.add_argument("--keep", action="store_true", help="Keep the temporary folder and the WebM files.")
    args = parser.parse_args()

    if not (REPO_ROOT / "app" / "web" / "dist" / "index.html").is_file():
        raise SystemExit("Build the web app first: cd app/web && npm run build")
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg is required for the GIFs.")
    if not (Path(args.playwright) / "node_modules" / "playwright").is_dir():
        raise SystemExit(f"No node_modules/playwright under {args.playwright}. See the docstring.")

    scenes = args.only or list(SCENES)
    zone = ZoneInfo(TIMEZONE)
    day = date.fromisoformat(args.today) if args.today else capture_day(datetime.now(zone).date())
    now = datetime.combine(day, datetime.min.time(), tzinfo=zone).replace(hour=10, minute=40)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    port = free_port(args.port)
    root = Path(tempfile.mkdtemp(prefix="semester-os-capture-"))
    print(f"Capturing around {now:%a %b %d %H:%M} on port {port} in {root}")

    middle = day - timedelta(days=day.weekday()) - timedelta(weeks=2)
    term = f"{'Spring' if middle.month <= 5 else 'Summer' if middle.month <= 7 else 'Fall'} {middle.year}"
    workspace = Workspace(root, port, term)
    workspace.now = now
    settings = {"timezone": TIMEZONE, "now": now.isoformat()}
    try:
        if "shots" in scenes or "notes" in scenes:
            print(workspace.run("scripts/seed_demo.py", "--today", day.isoformat(), "--now", "10:40").strip())
            course_id = workspace.query("SELECT id FROM courses WHERE code = 'CS 3200'")[0][0]
            midterm_id, math_id = workspace.query(
                "SELECT a.id, a.course_id FROM assignments a JOIN courses c ON c.id = a.course_id "
                "WHERE c.code = 'MATH 2700' AND a.title = 'Midterm 2'"
            )[0]
            # Thursday of next week: the recording pages one week ahead to find it.
            moved = day - timedelta(days=day.weekday()) + timedelta(days=10)
            start = datetime.combine(moved, datetime.min.time(), tzinfo=zone).replace(hour=19)
            spoken = f"{moved:%b} {moved.day}"
            note_text = f"Midterm 2 moved to {spoken}, 7-9pm in LAB 101"
            answer = fenced({
                "ops": [{
                    "op": "update_assignment",
                    "assignment_id": midterm_id,
                    "set": {
                        "due_at": start.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "ends_at": (start + timedelta(hours=2)).astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "location": "LAB 101",
                    },
                    "summary": f"Move Midterm 2 (MATH 2700) to {moved:%a} {spoken}, 7:00-9:00 PM in LAB 101",
                }],
                "commentary": f"Only MATH 2700 has a Midterm 2 (course {math_id}). {spoken} is read in this "
                              "semester; the exam becomes a block from 7 to 9 PM in LAB 101.",
            })
            workspace.answers.write_text(json.dumps({"school-editor": answer, "delay_seconds": 1.6}), encoding="utf-8")
            workspace.start()
            if "shots" in scenes:
                node(args, workspace, "shots", out, {**settings, "courseId": course_id})
            if "notes" in scenes:
                node(args, workspace, "notes", out, {**settings, "noteText": note_text})

        if "onboarding" in scenes:
            workspace.reset()
            answer = fenced({**STAT2400_PROPOSAL, "commentary": STAT2400_COMMENTARY})
            workspace.answers.write_text(json.dumps({"course-importer": answer, "delay_seconds": 1.2}), encoding="utf-8")
            workspace.start()
            syllabus = workspace.repo / "examples" / "syllabi" / "stat2400-course-page.html"
            node(args, workspace, "onboarding", out, {**settings, "syllabusPath": str(syllabus)})
    finally:
        workspace.stop()

    for name, speed in (("notes", 1.0), ("onboarding", 1.25)):
        video = out / f"{name}.webm"
        if name in scenes and video.exists():
            trim = json.loads((out / f"{name}.json").read_text(encoding="utf-8"))
            to_gif(video, out / f"{name}.gif", start=trim["start"], fps=args.fps, width=args.width, speed=speed)
            (out / f"{name}.json").unlink()
            if not args.keep:
                video.unlink()
    for png in sorted(out.glob("*.png")):
        if "shots" in scenes:
            shrink_png(png)
    for asset in sorted(out.iterdir()):
        print(f"  {asset.name:24} {asset.stat().st_size / 1024:8.0f} KB")

    if args.keep:
        print(f"Kept {root}")
    else:
        shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
