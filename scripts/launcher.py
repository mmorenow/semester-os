#!/usr/bin/env python3
"""Semester OS launcher: setup, start, stop, status, update, doctor.

Invoked by `./semester-os` / `semester-os.cmd`. Standard library only, because
it runs before the virtual environment exists.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Iterable, NoReturn, Sequence

# ---------------------------------------------------------------------------
# Paths and requirements
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "app" / "server"
WEB_DIR = ROOT / "app" / "web"
DIST_DIR = WEB_DIR / "dist"
NODE_MODULES = WEB_DIR / "node_modules"
VENV_DIR = SERVER_DIR / ".venv"
REQUIREMENTS = SERVER_DIR / "requirements.txt"
REQUIREMENTS_DEV = SERVER_DIR / "requirements-dev.txt"
CONFIG_PATH = ROOT / "config.yaml"
EXAMPLE_CONFIG = ROOT / "config.example.yaml"
DATA_DIR = ROOT / "data"
SYLLABI_DIR = ROOT / "syllabi"
LOG_DIR = DATA_DIR / "logs"
SERVER_LOG = LOG_DIR / "server.log"
SETUP_LOG = LOG_DIR / "setup.log"
PID_FILE = DATA_DIR / "semester-os.pid"
TOKEN_FILE = DATA_DIR / ".semester_os_token"

# Hashes of what was installed from which inputs, so a repeat setup skips finished work.
VENV_STAMP = VENV_DIR / ".semester-os-requirements"
STAMP_DIR = NODE_MODULES / ".semester-os"
NPM_STAMP = STAMP_DIR / "lockfile"
BUILD_STAMP = STAMP_DIR / "build"

# The web inputs whose change means the build is out of date.
WEB_BUILD_INPUTS = (
    "src",
    "public",
    "index.html",
    "package.json",
    "package-lock.json",
    "vite.config.ts",
    "tsconfig.json",
    "tsconfig.app.json",
    "tsconfig.node.json",
    "components.json",
)

MIN_PYTHON = (3, 11)
MIN_NODE = 20
DEFAULT_PORT = 8790
HOST = "127.0.0.1"
HEALTH_TIMEOUT_SECONDS = 60
STOP_TIMEOUT_SECONDS = 10

WINDOWS = os.name == "nt"
EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_NOT_RUNNING = 3  # the LSB convention for "status: program is not running"


class LauncherError(Exception):
    """A step failed. The message says what happened and what to do next."""


# ---------------------------------------------------------------------------
# Output. Plain ASCII markers, colored only on a terminal that wants color.
# ---------------------------------------------------------------------------

def _wants_color() -> bool:
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if not sys.stdout.isatty():
        return False
    if WINDOWS:
        # Turns on ANSI escape processing in the Windows console.
        os.system("")
    return True


COLOR = _wants_color()


def _paint(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOR else text


def bold(text: str) -> str:
    return _paint("1", text)


def dim(text: str) -> str:
    return _paint("2", text)


def say(text: str = "") -> None:
    print(text, flush=True)


def heading(text: str) -> None:
    say()
    say(bold(text))


def ok(text: str) -> None:
    say(f"  {_paint('32', '[ok]  ')} {text}")


def info(text: str) -> None:
    say(f"  {_paint('36', '[..]  ')} {text}")


def warn(text: str) -> None:
    say(f"  {_paint('33', '[warn]')} {text}")


def bad(text: str) -> None:
    say(f"  {_paint('31', '[FAIL]')} {text}")


def hint(text: str) -> None:
    for line in text.splitlines():
        say(f"         {dim(line)}")


def die(message: str, code: int = EXIT_FAIL) -> NoReturn:
    say()
    for number, line in enumerate(message.splitlines()):
        say(_paint("31", f"error: {line}") if number == 0 else f"       {line}")
    sys.exit(code)


def launcher_command() -> str:
    return "semester-os.cmd" if WINDOWS else "./semester-os"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def is_wsl() -> bool:
    if sys.platform != "linux":
        return False
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def os_family() -> str:
    if WINDOWS:
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "wsl" if is_wsl() else "linux"


def venv_python() -> Path:
    return VENV_DIR / ("Scripts/python.exe" if WINDOWS else "bin/python")


def which(name: str) -> str | None:
    return shutil.which(name)


def capture(cmd: Sequence[str], timeout: float = 20, cwd: Path | None = None) -> tuple[int, str]:
    """Run a short command and return (exit code, stdout+stderr). Never raises."""
    try:
        done = subprocess.run(
            list(cmd),
            cwd=str(cwd) if cwd else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)
    return done.returncode, done.stdout.strip()


def run_step(cmd: Sequence[str], label: str, cwd: Path | None = None, verbose: bool = False) -> float:
    """Run an install/build step, logging to setup.log (tail printed on failure). Returns seconds taken."""
    started = time.monotonic()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with SETUP_LOG.open("a", encoding="utf-8") as log:
        log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {label}\n$ {' '.join(cmd)}\n")
        log.flush()
        try:
            if verbose:
                code = subprocess.call(list(cmd), cwd=str(cwd) if cwd else None)
            else:
                code = subprocess.call(
                    list(cmd),
                    cwd=str(cwd) if cwd else None,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
        except OSError as exc:
            raise LauncherError(f"{label} could not start: {exc}") from None
    if code != 0:
        tail = ""
        if not verbose:
            lines = SETUP_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = "\n".join(lines[-25:])
        raise LauncherError(
            f"{label} failed (exit code {code}).\n"
            f"The full output is in {relative(SETUP_LOG)}. Last lines:\n{tail}"
        )
    return time.monotonic() - started


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def sha256_files(paths: Iterable[Path], extra: str = "") -> str:
    digest = hashlib.sha256(extra.encode("utf-8"))
    for path in sorted(paths):
        if path.is_file():
            digest.update(str(path.relative_to(ROOT)).replace("\\", "/").encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def web_build_hash() -> str:
    files: list[Path] = []
    for name in WEB_BUILD_INPUTS:
        target = WEB_DIR / name
        if target.is_dir():
            files.extend(p for p in target.rglob("*") if p.is_file() and p.name != ".DS_Store")
        elif target.is_file():
            files.append(target)
    return sha256_files(files)


def read_stamp(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def write_stamp(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n", encoding="utf-8")


def python_version_of(executable: Path | str) -> tuple[int, int, int] | None:
    code, out = capture(
        [str(executable), "-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"], timeout=15
    )
    if code != 0:
        return None
    try:
        major, minor, micro = (int(part) for part in out.splitlines()[-1].split("."))
    except ValueError:
        return None
    return major, minor, micro


def node_major() -> tuple[int | None, str | None]:
    node = which("node")
    if not node:
        return None, None
    code, out = capture([node, "--version"], timeout=15)
    if code != 0 or not out.startswith("v"):
        return None, out or None
    try:
        return int(out[1:].split(".")[0]), out
    except ValueError:
        return None, out


def requirements_hash(dev: bool) -> str:
    files = [REQUIREMENTS, REQUIREMENTS_DEV] if dev else [REQUIREMENTS]
    return sha256_files(files, extra="dev" if dev else "runtime")


def deps_are_current(dev: bool = False) -> bool:
    stamp = read_stamp(VENV_STAMP)
    if not stamp or not venv_python().is_file():
        return False
    if dev:
        return stamp == requirements_hash(True)
    return stamp in {requirements_hash(False), requirements_hash(True)}


def use_uv() -> str | None:
    if os.environ.get("SEMESTER_OS_NO_UV"):
        return None
    return which("uv")


# ---------------------------------------------------------------------------
# Install hints
# ---------------------------------------------------------------------------

def python_hint() -> str:
    family = os_family()
    if family == "macos":
        return (
            "Install it with Homebrew (brew install python@3.12) or from https://www.python.org/downloads/.\n"
            "Or install uv (https://docs.astral.sh/uv/) and the launcher will fetch Python for you."
        )
    if family in {"linux", "wsl"}:
        return (
            "On Ubuntu 24.04 or newer: sudo apt install python3 python3-venv\n"
            "Anywhere else, the easiest route is uv, which brings its own Python:\n"
            "  curl -LsSf https://astral.sh/uv/install.sh | sh"
        )
    return "Install Python 3.12 from https://www.python.org/downloads/ (tick 'Add python.exe to PATH')."


def node_hint() -> str:
    family = os_family()
    if family == "macos":
        return "Install it with Homebrew (brew install node@22) or from https://nodejs.org/ (the LTS version)."
    if family in {"linux", "wsl"}:
        return (
            "Install the LTS version with nvm (https://github.com/nvm-sh/nvm): nvm install 22\n"
            "Distribution packages are often too old; check with node --version."
        )
    return "Install the LTS version from https://nodejs.org/."


# ---------------------------------------------------------------------------
# Configuration, read through the server's own validator
# ---------------------------------------------------------------------------

CONFIG_PROBE = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
try:
    import config
except Exception as exc:
    print(json.dumps({"ok": False, "error": str(exc), "kind": type(exc).__name__}))
    raise SystemExit(0)
live = config.CONFIG
print(json.dumps({
    "ok": True,
    "port": live.port,
    "timezone": live.timezone,
    "term": live.term,
    "school_name": live.school_name,
    "feeds": {name: bool(url) for name, url in live.calendar_feeds.items()},
    "config_file": config.CONFIG_PATH.is_file(),
}))
"""


def probe_config() -> dict[str, Any]:
    """Validate config.yaml with the server's own config.py, in the venv, so the two never disagree."""
    python = venv_python()
    if not python.is_file():
        return {"ok": False, "error": "The virtual environment does not exist yet.", "kind": "NoVenv"}
    code, out = capture([str(python), "-c", CONFIG_PROBE, str(SERVER_DIR)], timeout=30, cwd=ROOT)
    try:
        return json.loads(out.splitlines()[-1])
    except (IndexError, ValueError):
        return {"ok": False, "error": out or f"exit code {code}", "kind": "ProbeFailed"}


def resolve_port() -> int:
    probe = probe_config()
    if not probe.get("ok"):
        raise LauncherError(
            f"config.yaml is not valid: {probe.get('error')}\n"
            "Fix the file (config.example.yaml documents every key) and try again."
        )
    return int(probe["port"])


# ---------------------------------------------------------------------------
# The running server
# ---------------------------------------------------------------------------

_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def health(port: int, timeout: float = 1.5) -> dict[str, Any] | None:
    """GET /api/health on loopback. None when nothing (or not us) answers."""
    try:
        with _NO_PROXY_OPENER.open(f"http://{HOST}:{port}/api/health", timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException):
        return None
    if isinstance(body, dict) and body.get("app") == "semester-os":
        return body
    return None


def port_is_free(port: int) -> bool:
    """True when nothing answers on the port and it binds the way uvicorn binds it.

    Both checks: with SO_REUSEADDR a bind succeeds on macOS beside a 0.0.0.0
    listener, and a connect alone misses a port bound but not yet listening.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        if probe.connect_ex((HOST, port)) == 0:
            return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if not WINDOWS:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((HOST, port))
        except OSError:
            return False
    return True


def read_pid_file() -> dict[str, Any] | None:
    try:
        data = json.loads(PID_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("pid"), int) else None


def write_pid_file(pid: int, port: int, mode: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(
        json.dumps({"pid": pid, "port": port, "mode": mode, "started_at": int(time.time())}) + "\n",
        encoding="utf-8",
    )


def remove_pid_file(pid: int | None = None) -> None:
    current = read_pid_file()
    if pid is not None and current and current.get("pid") != pid:
        return
    try:
        PID_FILE.unlink()
    except OSError:
        pass


def pid_alive(pid: int) -> bool:
    if WINDOWS:
        code, out = capture(["tasklist", "/FI", f"PID eq {pid}", "/NH"], timeout=10)
        return code == 0 and str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def pid_is_our_server(pid: int) -> bool:
    """Guard against a recycled pid: the process should be running app.py."""
    if WINDOWS or not which("ps"):
        return pid_alive(pid)
    code, out = capture(["ps", "-p", str(pid), "-o", "command="], timeout=10)
    return code == 0 and "app.py" in out


def open_browser(url: str) -> None:
    if os.environ.get("SEMESTER_OS_NO_BROWSER") or os.environ.get("SSH_CONNECTION"):
        return
    family = os_family()
    try:
        if family == "wsl":
            for cmd in (["wslview", url], ["cmd.exe", "/c", "start", "", url]):
                if which(cmd[0]) and capture(cmd, timeout=15)[0] == 0:
                    return
            return
        if family == "linux" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            # No display: webbrowser would open a text browser in this terminal.
            return
        webbrowser.open(url, new=2)
    except Exception:  # noqa: BLE001 - failing to open a browser is never fatal
        pass


def server_command() -> list[str]:
    return [str(venv_python()), str(SERVER_DIR / "app.py")]


def server_env(port: int) -> dict[str, str]:
    env = dict(os.environ)
    env["SEMESTER_OS_PORT"] = str(port)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def wait_for_health(port: int, process: subprocess.Popen[Any]) -> dict[str, Any]:
    deadline = time.monotonic() + HEALTH_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise LauncherError(
                f"The server exited during startup (exit code {process.returncode}). "
                "Its output above says why."
            )
        body = health(port, timeout=1)
        if body:
            return body
        time.sleep(0.25)
    raise LauncherError(f"The server did not answer on port {port} within {HEALTH_TIMEOUT_SECONDS} seconds.")


def terminate(process_or_pid: subprocess.Popen[Any] | int) -> None:
    """Ask politely, wait, then insist."""
    pid = process_or_pid if isinstance(process_or_pid, int) else process_or_pid.pid

    def exited(timeout: float) -> bool:
        if isinstance(process_or_pid, subprocess.Popen):
            try:
                process_or_pid.wait(timeout=timeout)
                return True
            except subprocess.TimeoutExpired:
                return False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not pid_alive(pid):
                return True
            time.sleep(0.2)
        return not pid_alive(pid)

    if exited(0):
        return
    if WINDOWS:
        capture(["taskkill", "/PID", str(pid), "/T"], timeout=15)
        if not exited(STOP_TIMEOUT_SECONDS):
            capture(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=15)
            exited(5)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    if not exited(STOP_TIMEOUT_SECONDS):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        exited(5)


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

def check_python() -> None:
    if sys.version_info < MIN_PYTHON:
        raise LauncherError(
            f"Python {'.'.join(map(str, MIN_PYTHON))} or newer is required; this is "
            f"{platform.python_version()}.\n{python_hint()}"
        )
    ok(f"Python {platform.python_version()} ({sys.executable})")


def base_python() -> str:
    """The interpreter a new venv is made from: never the venv's own python."""
    return getattr(sys, "_base_executable", None) or sys.executable


def ensure_venv(verbose: bool) -> None:
    python = venv_python()
    existing = python_version_of(python) if python.is_file() else None
    if existing and existing[:2] >= MIN_PYTHON:
        ok(f"Virtual environment {relative(VENV_DIR)} (Python {'.'.join(map(str, existing))})")
        return
    if VENV_DIR.exists():
        warn(f"{relative(VENV_DIR)} is broken or too old; recreating it.")
        shutil.rmtree(VENV_DIR, ignore_errors=True)
    uv = use_uv()
    info(f"Creating the virtual environment in {relative(VENV_DIR)}" + (" with uv" if uv else ""))
    try:
        if uv:
            took = run_step([uv, "venv", "--quiet", "--python", base_python(), str(VENV_DIR)],
                            "Creating the virtual environment", verbose=verbose)
        else:
            took = run_step([base_python(), "-m", "venv", str(VENV_DIR)],
                            "Creating the virtual environment", verbose=verbose)
    except LauncherError as exc:
        extra = ""
        if os_family() in {"linux", "wsl"}:
            extra = (
                "\nOn Debian and Ubuntu the venv module is a separate package: "
                "sudo apt install python3-venv (or python3.12-venv)."
            )
        raise LauncherError(f"{exc}{extra}") from None
    ok(f"Virtual environment {relative(VENV_DIR)} ({took:.1f}s)")


def ensure_requirements(dev: bool, force: bool, verbose: bool) -> None:
    if not force and deps_are_current(dev):
        ok("Server requirements already installed")
        return
    target = REQUIREMENTS_DEV if dev else REQUIREMENTS
    uv = use_uv()
    python = str(venv_python())
    label = "Installing the server requirements" + (" (with test tools)" if dev else "")
    info(label + (" with uv" if uv else " with pip (a minute or two)"))
    if uv:
        cmd = [uv, "pip", "install", "--python", python, "-r", str(target)]
    else:
        cmd = [python, "-m", "pip", "install", "--disable-pip-version-check", "-r", str(target)]
    took = run_step(cmd, label, cwd=SERVER_DIR, verbose=verbose)
    code, out = capture(
        [python, "-c", "import fastapi, uvicorn, yaml, pydantic, icalendar, recurring_ical_events"],
        timeout=60,
    )
    if code != 0:
        raise LauncherError(f"The requirements installed but do not import:\n{out}")
    write_stamp(VENV_STAMP, requirements_hash(dev))
    ok(f"Server requirements installed ({took:.1f}s)")


def ensure_config() -> None:
    if CONFIG_PATH.is_file():
        ok("config.yaml exists (left untouched)")
        return
    if not EXAMPLE_CONFIG.is_file():
        raise LauncherError("config.example.yaml is missing from the repository.")
    shutil.copyfile(EXAMPLE_CONFIG, CONFIG_PATH)
    ok("Created config.yaml from config.example.yaml (edit it any time)")


def ensure_dirs() -> None:
    created = []
    for folder in (DATA_DIR, SYLLABI_DIR):
        if not folder.is_dir():
            folder.mkdir(parents=True, exist_ok=True)
            created.append(relative(folder) + "/")
    if not WINDOWS:
        # data/ holds the API token and any calendar credentials.
        try:
            os.chmod(DATA_DIR, 0o700)
        except OSError:
            pass
    ok(("Created " + " and ".join(created)) if created else "data/ and syllabi/ exist")


def ensure_web(force_build: bool, verbose: bool) -> None:
    major, version = node_major()
    has_build = (DIST_DIR / "index.html").is_file()
    if major is None or major < MIN_NODE:
        found = f"found {version}" if version else "not found"
        if has_build:
            warn(f"Node.js {MIN_NODE}+ {found}; using the web app already built in {relative(DIST_DIR)}.")
            hint("Install Node to rebuild it after an update.\n" + node_hint())
            return
        raise LauncherError(
            f"Node.js {MIN_NODE} or newer is required to build the web app ({found}).\n{node_hint()}"
        )
    npm = which("npm")
    if not npm:
        raise LauncherError(f"Node {version} is installed but npm is not on PATH.\n{node_hint()}")
    ok(f"Node.js {version}")

    lock_hash = sha256_files([WEB_DIR / "package-lock.json", WEB_DIR / "package.json"])
    if read_stamp(NPM_STAMP) == lock_hash and NODE_MODULES.is_dir():
        ok("Web dependencies already installed")
    else:
        info("Installing web dependencies with npm ci (a minute or two)")
        took = run_step([npm, "ci", "--no-audit", "--no-fund", "--loglevel=error"],
                        "Installing web dependencies", cwd=WEB_DIR, verbose=verbose)
        write_stamp(NPM_STAMP, lock_hash)
        write_stamp(BUILD_STAMP, "")  # a fresh node_modules invalidates the build stamp
        ok(f"Web dependencies installed ({took:.1f}s)")

    build_hash = web_build_hash()
    if not force_build and has_build and read_stamp(BUILD_STAMP) == build_hash:
        ok("Web app already built and up to date")
        return
    info("Building the web app")
    took = run_step([npm, "run", "build"], "Building the web app", cwd=WEB_DIR, verbose=verbose)
    if not (DIST_DIR / "index.html").is_file():
        raise LauncherError(f"The build finished but {relative(DIST_DIR)}/index.html is missing.")
    write_stamp(BUILD_STAMP, build_hash)
    ok(f"Web app built into {relative(DIST_DIR)} ({took:.1f}s)")


def do_setup(dev: bool = False, force: bool = False, rebuild: bool = False, verbose: bool = False) -> None:
    started = time.monotonic()
    heading("Semester OS setup")
    steps = (
        ("Python", check_python),
        ("Virtual environment", lambda: ensure_venv(verbose)),
        ("Server requirements", lambda: ensure_requirements(dev, force, verbose)),
        ("Web app", lambda: ensure_web(force or rebuild, verbose)),
        ("Configuration", ensure_config),
        ("Folders", ensure_dirs),
    )
    for _name, step in steps:
        step()
    probe = probe_config()
    if probe.get("ok"):
        ok(f"Configuration is valid (port {probe['port']}, timezone {probe['timezone']})")
    else:
        raise LauncherError(f"config.yaml is not valid: {probe.get('error')}")
    say()
    say(bold(f"Setup finished in {time.monotonic() - started:.1f}s."))


def is_set_up() -> bool:
    return venv_python().is_file() and deps_are_current() and (DIST_DIR / "index.html").is_file()


# ---------------------------------------------------------------------------
# start / stop / status
# ---------------------------------------------------------------------------

def describe_running(port: int) -> str:
    return f"http://{HOST}:{port}"


def do_start(background: bool, browser: bool, port_override: int | None) -> int:
    if port_override is not None:
        os.environ["SEMESTER_OS_PORT"] = str(port_override)
    if not is_set_up():
        say(bold("Semester OS is not set up yet (or its requirements changed). Running setup first."))
        do_setup()
    elif shutil.which("node") and read_stamp(BUILD_STAMP) not in {None, "", web_build_hash()}:
        warn(f"The web source changed since the last build. Run {launcher_command()} update to rebuild.")

    port = resolve_port()
    url = describe_running(port)

    running = read_pid_file()
    if health(port):
        say(bold(f"Semester OS is already running at {url}"))
        if running and running.get("port") == port:
            say(f"Stop it with {launcher_command()} stop.")
        if browser:
            open_browser(url)
        return EXIT_OK
    if running and not pid_alive(int(running["pid"])):
        remove_pid_file()
    if not port_is_free(port):
        hint_cmd = f"lsof -iTCP:{port} -sTCP:LISTEN" if not WINDOWS else f"netstat -ano | findstr :{port}"
        raise LauncherError(
            f"Port {port} is in use by another program.\n"
            f"See what holds it with: {hint_cmd}\n"
            "Or pick another port: set port in config.yaml, or run with SEMESTER_OS_PORT=8791."
        )

    heading(f"Starting Semester OS on {url}")
    started = time.monotonic()
    env = server_env(port)

    if background:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log = SERVER_LOG.open("a", encoding="utf-8")
        log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} start (port {port})\n")
        log.flush()
        kwargs: dict[str, Any] = {}
        if WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(
            server_command(), cwd=str(ROOT), env=env,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **kwargs,
        )
        log.close()
        write_pid_file(process.pid, port, "background")
        try:
            body = wait_for_health(port, process)
        except LauncherError as exc:
            terminate(process)
            remove_pid_file(process.pid)
            raise LauncherError(f"{exc}\nThe server log is {relative(SERVER_LOG)}.") from None
        ok(f"Running in the background (pid {process.pid}), ready in {time.monotonic() - started:.1f}s")
        report_claude(body)
        say(f"\n  Open {bold(url)}")
        say(f"  Logs: {relative(SERVER_LOG)}   Stop: {launcher_command()} stop")
        if browser:
            open_browser(url)
        return EXIT_OK

    process = subprocess.Popen(server_command(), cwd=str(ROOT), env=env)
    write_pid_file(process.pid, port, "foreground")

    def _on_term(_signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt

    if not WINDOWS:
        signal.signal(signal.SIGTERM, _on_term)
        signal.signal(signal.SIGHUP, _on_term)
    try:
        body = wait_for_health(port, process)
        say()
        ok(f"Ready in {time.monotonic() - started:.1f}s")
        report_claude(body)
        say(f"\n  Open {bold(url)}")
        say("  Press Ctrl+C to stop.\n")
        if browser:
            open_browser(url)
        return process.wait()
    except KeyboardInterrupt:
        say("\nStopping Semester OS...")
        terminate(process)
        say("Stopped.")
        return EXIT_OK
    except LauncherError:
        terminate(process)
        raise
    finally:
        remove_pid_file(process.pid)


def report_claude(body: dict[str, Any]) -> None:
    if body.get("claude_cli"):
        ok("Claude Code CLI found: Notes and AI features are available")
    else:
        warn("Claude Code CLI not found: everything works except the AI features (see docs/install.md)")


def do_stop() -> int:
    record = read_pid_file()
    if not record:
        probe = probe_config()
        port = int(probe["port"]) if probe.get("ok") else DEFAULT_PORT
        if health(port):
            say(
                f"Semester OS is running on port {port}, but it was not started by this launcher "
                "(a background service, or another checkout), so there is no process to stop here."
            )
            say("If it runs as a service, stop it the way docs/run-in-background.md describes.")
            return EXIT_FAIL
        say("Semester OS is not running.")
        return EXIT_OK
    pid = int(record["pid"])
    if not pid_alive(pid) or not pid_is_our_server(pid):
        remove_pid_file()
        say("Semester OS is not running (removed a stale pid file).")
        return EXIT_OK
    say(f"Stopping Semester OS (pid {pid})...")
    terminate(pid)
    if pid_alive(pid):
        die(f"Process {pid} did not exit. Stop it by hand.")
    remove_pid_file()
    say("Stopped.")
    return EXIT_OK


def do_status() -> int:
    record = read_pid_file()
    probe = probe_config()
    port = int(record["port"]) if record else (int(probe["port"]) if probe.get("ok") else DEFAULT_PORT)
    body = health(port)
    if body:
        say(bold(f"Semester OS is running at {describe_running(port)}"))
        if record and pid_alive(int(record["pid"])):
            uptime = int(time.time()) - int(record.get("started_at", time.time()))
            say(f"  pid {record['pid']}, {record.get('mode', 'unknown')} mode, up {format_duration(uptime)}")
        else:
            say("  Not started by this launcher (a background service or another checkout).")
        say(f"  AI features: {'available' if body.get('claude_cli') else 'Claude Code CLI not found'}")
        return EXIT_OK
    if record and not pid_is_our_server(int(record["pid"])):
        remove_pid_file()
    elif record:
        say(f"Semester OS process {record['pid']} exists but does not answer on port {port}.")
        say(f"  It may still be starting. The log is {relative(SERVER_LOG)}.")
        return EXIT_FAIL
    say(f"Semester OS is not running. Start it with {launcher_command()} start.")
    return EXIT_NOT_RUNNING


def format_duration(seconds: int) -> str:
    minutes, secs = divmod(max(seconds, 0), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

def do_update(verbose: bool) -> int:
    say("Updating Semester OS. Pull the new code first (for example: git pull); this step")
    say("reinstalls whatever changed and rebuilds the web app.")
    record = read_pid_file()
    restart = bool(
        record
        and record.get("mode") == "background"
        and pid_alive(int(record["pid"]))
        and pid_is_our_server(int(record["pid"]))
    )
    if restart:
        do_stop()
    dev = read_stamp(VENV_STAMP) == requirements_hash(True)
    do_setup(dev=dev, rebuild=True, verbose=verbose)
    if restart:
        return do_start(background=True, browser=False, port_override=None)
    if record and record.get("mode") == "foreground" and pid_alive(int(record["pid"])):
        warn("Semester OS is running in another terminal. Restart it there to use the new version.")
    return EXIT_OK


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

class Report:
    def __init__(self) -> None:
        self.failures = 0
        self.warnings = 0

    def ok(self, text: str) -> None:
        ok(text)

    def warn(self, text: str, fix: str | None = None) -> None:
        self.warnings += 1
        warn(text)
        if fix:
            hint(fix)

    def fail(self, text: str, fix: str | None = None) -> None:
        self.failures += 1
        bad(text)
        if fix:
            hint(fix)


def claude_binary() -> str | None:
    override = os.environ.get("SEMESTER_OS_CLAUDE_BIN")
    if override:
        return which(override) or (override if os.path.isfile(override) else None)
    return which("claude")


def doctor_claude(report: Report) -> None:
    heading("Claude Code (optional, for the AI features)")
    binary = claude_binary()
    if not binary:
        report.warn(
            "Claude Code CLI not found. Everything works except the AI features.",
            "Install it: https://code.claude.com/docs/en/setup, then run `claude` once to sign in.",
        )
        return
    code, out = capture([binary, "--version"], timeout=20)
    version = out.splitlines()[0] if code == 0 and out else "version unknown"
    report.ok(f"Claude Code CLI {version} ({binary})")
    # `claude auth status` reads the local sign-in state. It is not a model call.
    code, out = capture([binary, "auth", "status", "--json"], timeout=20)
    status: dict[str, Any] | None = None
    if code in (0, 1) and out:
        start = out.find("{")
        try:
            status = json.loads(out[start:]) if start >= 0 else None
        except ValueError:
            status = None
    if status is None:
        report.warn(
            "Could not read the sign-in state from this CLI version.",
            "Run `claude` once in a terminal; it asks you to sign in if needed.",
        )
    elif status.get("loggedIn"):
        method = status.get("authMethod") or "unknown method"
        report.ok(f"Signed in ({method})")
    else:
        report.warn("Claude Code is installed but not signed in.", "Run `claude` once in a terminal to sign in.")


def doctor_port(report: Report, port: int) -> None:
    body = health(port)
    if body:
        record = read_pid_file()
        who = f"pid {record['pid']}" if record and pid_alive(int(record["pid"])) else "not started by this launcher"
        report.ok(f"Port {port}: Semester OS is running there ({who})")
    elif port_is_free(port):
        report.ok(f"Port {port} is free")
    else:
        report.fail(
            f"Port {port} is in use by another program.",
            "Stop that program, or set port in config.yaml (or SEMESTER_OS_PORT) to a free port.",
        )


def doctor_data(report: Report) -> None:
    target = DATA_DIR if DATA_DIR.is_dir() else ROOT
    try:
        with tempfile.NamedTemporaryFile(dir=target, prefix=".write-test-", delete=True):
            pass
    except OSError as exc:
        report.fail(f"{relative(target)}/ is not writable: {exc}", "Check the folder's owner and permissions.")
        return
    if DATA_DIR.is_dir():
        report.ok("data/ exists and is writable")
    else:
        report.warn("data/ does not exist yet (the server creates it on first start)")
    if TOKEN_FILE.is_file() and not WINDOWS:
        mode = TOKEN_FILE.stat().st_mode & 0o777
        if mode & 0o077:
            report.warn(
                f"data/.semester_os_token is readable by other users (mode {oct(mode)})",
                "The server tightens this on its next start, or run: chmod 600 data/.semester_os_token",
            )
    if SYLLABI_DIR.is_dir():
        report.ok("syllabi/ exists")
    else:
        report.warn("syllabi/ does not exist yet", f"{launcher_command()} setup creates it.")


def do_doctor() -> int:
    report = Report()
    say(bold("Semester OS doctor"))
    say(dim(f"  {ROOT}"))

    heading("System")
    family = os_family()
    report.ok(f"{platform.system()} {platform.release()} ({family}, {platform.machine()})")
    if WINDOWS:
        report.warn("Native Windows is best effort. WSL 2 is the supported way to run on Windows.")

    heading("Python")
    if sys.version_info >= MIN_PYTHON:
        report.ok(f"Launcher Python {platform.python_version()} ({sys.executable})")
    else:
        report.fail(f"Python {platform.python_version()} is too old; 3.11+ is required.", python_hint())
    uv = which("uv")
    report.ok(f"uv {(capture([uv, '--version'])[1].split() + ['?', '?'])[1] if uv else 'not installed'}"
              + ("" if uv else " (optional; setup uses pip instead)"))
    python = venv_python()
    version = python_version_of(python) if python.is_file() else None
    if version is None:
        report.fail(f"No working virtual environment at {relative(VENV_DIR)}", f"Run {launcher_command()} setup.")
    else:
        report.ok(f"Virtual environment Python {'.'.join(map(str, version))}")
        code, out = capture(
            [str(python), "-c", "import fastapi, uvicorn, yaml, pydantic, icalendar, recurring_ical_events"],
            timeout=60,
        )
        if code != 0:
            report.fail("Server requirements are missing or broken", f"Run {launcher_command()} setup.")
        elif not deps_are_current():
            report.warn("requirements.txt changed since the last install", f"Run {launcher_command()} update.")
        else:
            report.ok("Server requirements installed and current")

    heading("Web app")
    major, node_version = node_major()
    has_build = (DIST_DIR / "index.html").is_file()
    if major is not None and major >= MIN_NODE:
        npm = which("npm")
        npm_version = capture([npm, "--version"])[1] if npm else "missing"
        report.ok(f"Node.js {node_version}, npm {npm_version}")
    elif has_build:
        report.warn(f"Node.js {MIN_NODE}+ not found ({node_version or 'none'}); fine while the existing build is used",
                    node_hint())
    else:
        report.fail(f"Node.js {MIN_NODE}+ not found ({node_version or 'none'})", node_hint())
    if not has_build:
        report.fail(f"The web app is not built ({relative(DIST_DIR)}/index.html missing)",
                    f"Run {launcher_command()} setup.")
    elif major is not None and read_stamp(BUILD_STAMP) not in {None, "", web_build_hash()}:
        report.warn("The web app is built but its source changed since", f"Run {launcher_command()} update.")
    else:
        report.ok("Web app is built")

    doctor_claude(report)

    heading("Configuration")
    probe = probe_config()
    port = DEFAULT_PORT
    if probe.get("ok"):
        port = int(probe["port"])
        source = "config.yaml" if probe.get("config_file") else "defaults (no config.yaml)"
        report.ok(f"Valid, read from {source}")
        feeds = [name for name, present in probe.get("feeds", {}).items() if present]
        say(dim(f"         timezone {probe['timezone']}, port {port}, term {probe.get('term') or '-'}, "
                f"calendar feeds: {', '.join(feeds) if feeds else 'none'}"))
    elif probe.get("kind") == "NoVenv":
        report.fail("Cannot validate config.yaml before setup", f"Run {launcher_command()} setup.")
    else:
        report.fail(f"config.yaml is not valid: {probe.get('error')}",
                    "config.example.yaml documents every key; see docs/configuration.md.")
    if os.environ.get("SEMESTER_OS_PORT"):
        say(dim(f"         SEMESTER_OS_PORT={os.environ['SEMESTER_OS_PORT']} overrides the port"))

    heading("Network and data")
    doctor_port(report, port)
    doctor_data(report)

    say()
    if report.failures:
        say(_paint("31", bold(f"{report.failures} problem(s), {report.warnings} warning(s).")))
        return EXIT_FAIL
    say(_paint("32", bold(f"No problems found ({report.warnings} warning(s)).")))
    return EXIT_OK


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    prog = launcher_command()
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Set up, run and check Semester OS. With no command: start (setting up first if needed).",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    setup = sub.add_parser("setup", help="install everything needed to run (safe to repeat)")
    setup.add_argument("--dev", action="store_true", help="also install the test tools (pytest)")
    setup.add_argument("--force", action="store_true", help="reinstall and rebuild even if up to date")
    setup.add_argument("--verbose", "-v", action="store_true", help="show pip and npm output")

    start = sub.add_parser("start", help="run the server and open the browser")
    start.add_argument("--background", "-d", action="store_true", help="keep running after this terminal closes")
    start.add_argument("--no-browser", action="store_true", help="do not open a browser")
    start.add_argument("--port", type=int, help="use this port instead of config.yaml's")

    sub.add_parser("stop", help="stop a server started by this launcher")
    sub.add_parser("status", help="show whether the server is running")

    update = sub.add_parser("update", help="after pulling new code: reinstall and rebuild")
    update.add_argument("--verbose", "-v", action="store_true", help="show pip and npm output")

    sub.add_parser("doctor", help="check the install without changing anything")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "start"
    try:
        if command == "setup":
            do_setup(dev=args.dev, force=args.force, verbose=args.verbose)
            say(f"Next: {launcher_command()} start")
            return EXIT_OK
        if command == "start":
            return do_start(
                background=getattr(args, "background", False),
                browser=not getattr(args, "no_browser", False),
                port_override=getattr(args, "port", None),
            )
        if command == "stop":
            return do_stop()
        if command == "status":
            return do_status()
        if command == "update":
            return do_update(verbose=args.verbose)
        if command == "doctor":
            return do_doctor()
    except LauncherError as exc:
        die(str(exc))
    except KeyboardInterrupt:
        say("\nInterrupted.")
        return 130
    except BrokenPipeError:
        # Piped into e.g. `| head`; silence the interpreter's complaint at exit.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return EXIT_OK
    parser.print_help()
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
