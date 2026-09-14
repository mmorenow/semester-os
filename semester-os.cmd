@echo off
rem Semester OS launcher for native Windows (best effort; WSL 2 is the supported route).
rem
rem   semester-os.cmd setup    install everything (safe to repeat)
rem   semester-os.cmd          start the app and open the browser
rem   semester-os.cmd doctor   check the install
rem
rem Finds a Python 3.11 or newer and hands over to scripts\launcher.py.

setlocal
set "LAUNCHER=%~dp0scripts\launcher.py"
set "CHECK=import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"

if defined SEMESTER_OS_PYTHON (
    "%SEMESTER_OS_PYTHON%" "%LAUNCHER%" %*
    goto done
)

py -3 -c "%CHECK%" >nul 2>&1
if not errorlevel 1 (
    py -3 "%LAUNCHER%" %*
    goto done
)

python -c "%CHECK%" >nul 2>&1
if not errorlevel 1 (
    python "%LAUNCHER%" %*
    goto done
)

where uv >nul 2>&1
if not errorlevel 1 (
    echo No Python 3.11+ found; using a Python managed by uv.
    uv run --no-project --quiet --python ">=3.11" "%LAUNCHER%" %*
    goto done
)

echo error: Semester OS needs Python 3.11 or newer, and none was found. 1>&2
echo   Install Python 3.12 from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^), 1>&2
echo   then open a new terminal and run this again. 1>&2
exit /b 2

:done
exit /b %errorlevel%
