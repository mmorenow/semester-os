# Installing Semester OS

| Requirement | Version | For |
| --- | --- | --- |
| Python | 3.11+ | The server |
| Node.js | 20+ (22 LTS recommended) | Building the web app once |
| Claude Code | latest | Optional: Notes and syllabus reading |

Every platform, from the repo folder:

```sh
./semester-os setup    # install (safe to re-run)
./semester-os          # start and open the browser
./semester-os doctor   # check the install
```

Setup creates `app/server/.venv`, builds the web app, and creates `config.yaml`, `data/` and `syllabi/`. Nothing goes outside the repo folder.

## macOS

```sh
brew install python@3.12 node@22 git
```

Keep the repo in your home folder (`~/semester-os`), not Desktop, Documents or Downloads, which macOS hides from [background services](run-in-background.md).

## Linux

Ubuntu 24.04+ / Debian 13+:

```sh
sudo apt update && sudo apt install -y python3 python3-venv git curl
```

Older distros (Ubuntu 22.04 has Python 3.10): install [uv](https://docs.astral.sh/uv/); the launcher uses it when no Python 3.11+ is found.

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Distro Node.js is often too old; use [nvm](https://github.com/nvm-sh/nvm):

```sh
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
nvm install 22   # in a new terminal
```

Fedora: `sudo dnf install python3 nodejs git`. Arch: `sudo pacman -S python nodejs npm git`.

## Windows

### Recommended: WSL 2

1. In an admin PowerShell: `wsl --install`, then restart. This installs Ubuntu.
2. Open **Ubuntu** and follow the [Linux](#linux) steps.
3. Keep the code in `~/semester-os`, not `/mnt/c/` (much faster). If no browser opens, visit <http://127.0.0.1:8790>.

### Native Windows (best effort)

Untested in CI. If it breaks, [report it](../.github/ISSUE_TEMPLATE/bug_report.md) and use WSL.

1. Install Python 3.12 from [python.org](https://www.python.org/downloads/) (tick **Add python.exe to PATH**), [Node.js 22 LTS](https://nodejs.org/) and [Git for Windows](https://git-scm.com/download/win).
2. From the repo folder:

   ```powershell
   .\semester-os.cmd setup
   .\semester-os.cmd
   ```

Use `.\semester-os.cmd` wherever the docs say `./semester-os`.

## Claude Code (optional)

Powers the AI features with your own Claude plan or API key.

1. Install per the [official guide](https://code.claude.com/docs/en/setup). On macOS, Linux and WSL:

   ```sh
   curl -fsSL https://claude.ai/install.sh | bash
   ```

2. Run `claude` once and sign in.
3. Restart Semester OS; `./semester-os doctor` should show Claude Code found and signed in.

If `claude` is not on your PATH, set `SEMESTER_OS_CLAUDE_BIN` to its full path.

## Getting the code

```sh
git clone https://github.com/mmorenow/semester-os.git
cd semester-os
```

A ZIP download works too but is harder to update. Neither includes the built web app, so Node.js is required.

## Everyday use

```sh
./semester-os                 # start and open the browser; Ctrl+C stops
./semester-os start -d        # start in the background
./semester-os status
./semester-os stop            # stop a background server
```

`start` options: `-d`/`--background`, `--no-browser`, `--port 8791`. Start at login: [run-in-background.md](run-in-background.md).

## Updating

```sh
git pull
./semester-os update
```

Reinstalls what changed, rebuilds, restarts a background server. Leaves `config.yaml`, `data/` and `syllabi/` alone.

## Uninstalling

`./semester-os stop`, remove any background service, delete the repo folder. Copy `data/` and `config.yaml` first to keep your semester.

## Troubleshooting

Start with `./semester-os doctor` (read-only).

| Problem | Fix |
| --- | --- |
| "Semester OS needs Python 3.11 or newer." | Install a newer Python or uv, or point at one: `SEMESTER_OS_PYTHON=/path/to/python3.12 ./semester-os setup` |
| "The venv module is a separate package" | `sudo apt install python3-venv`, or install uv |
| "Port 8790 is in use by another program." | Find it with `lsof -iTCP:8790 -sTCP:LISTEN`, or set `port: 8791` in `config.yaml` |
| npm or pip failed | See `data/logs/setup.log` or run `setup --verbose`; usually the network, re-run setup |
| "The user interface has not been built" | `./semester-os update` |
| Background server stopped | Check `data/logs/server.log` |
| Broken install | `./semester-os setup --force`, or delete `app/server/.venv` and `app/web/node_modules` and re-run setup (data kept) |
