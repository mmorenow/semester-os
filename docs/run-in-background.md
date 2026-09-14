# Running in the background

- **For today:** `./semester-os start -d`. Runs until `./semester-os stop` or a reboot. Log: `data/logs/server.log`.
- **Always:** install a login service from the templates below.

A service bypasses the launcher: run `setup` first, use the service commands instead of `stop`, restart it after `update`, and do not combine it with `start -d` (same port). Run everything from the repo folder (`$PWD`).

## macOS: launchd

Keep the repo out of Desktop, Documents, Downloads and iCloud Drive, or it fails with "Operation not permitted". If `which claude` is not on the template's `PATH`, add it or set `SEMESTER_OS_CLAUDE_BIN`.

### Install

Paste as one command:

```sh
mkdir -p ~/Library/LaunchAgents data/logs
cat > ~/Library/LaunchAgents/local.semester-os.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>local.semester-os</string>

  <key>ProgramArguments</key>
  <array>
    <string>$PWD/app/server/.venv/bin/python</string>
    <string>$PWD/app/server/app.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PWD</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
  </dict>

  <!-- Start at login, and restart after a crash (not after a clean stop). -->
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>ThrottleInterval</key>
  <integer>30</integer>

  <key>StandardOutPath</key>
  <string>$PWD/data/logs/server.log</string>
  <key>StandardErrorPath</key>
  <string>$PWD/data/logs/server.log</string>
</dict>
</plist>
EOF
plutil -lint ~/Library/LaunchAgents/local.semester-os.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.semester-os.plist
```

Check with `./semester-os status` or <http://127.0.0.1:8790>.

### Manage

```sh
launchctl kickstart -k gui/$(id -u)/local.semester-os   # restart (after an update)
launchctl print gui/$(id -u)/local.semester-os | head    # state and last exit code
tail -f data/logs/server.log                              # the log
```

### Remove

```sh
launchctl bootout gui/$(id -u)/local.semester-os
rm ~/Library/LaunchAgents/local.semester-os.plist
```

## Linux: systemd user service

Runs as you, no root, starts at login. Also works on WSL with systemd.

### Install

```sh
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/semester-os.service <<EOF
[Unit]
Description=Semester OS
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$PWD
ExecStart=$PWD/app/server/.venv/bin/python $PWD/app/server/app.py
# Where the Claude Code CLI lives. Add a folder if "which claude" differs.
Environment=PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=10
NoNewPrivileges=true

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now semester-os
```

Paths with spaces break `ExecStart`; use a folder without spaces. To keep it running while logged out (e.g. over SSH): `loginctl enable-linger "$USER"`.

### Manage

```sh
systemctl --user status semester-os
systemctl --user restart semester-os      # after an update
journalctl --user -u semester-os -f       # the log
```

### Remove

```sh
systemctl --user disable --now semester-os
rm ~/.config/systemd/user/semester-os.service
systemctl --user daemon-reload
```

## Windows

### WSL 2

If `systemctl --user status` says systemd is not running, add this to `/etc/wsl.conf`, run `wsl --shutdown`, and reopen Ubuntu:

```ini
[boot]
systemd=true
```

Then follow the Linux steps, including `enable-linger`. To start WSL at Windows login, schedule `wsl.exe -d Ubuntu --exec /bin/true` at logon. WSL may stop an idle distro; reopen Ubuntu if the app disappears. Without systemd, run `./semester-os start -d` in each session.

### Native Windows (best effort)

From PowerShell in the repo folder:

```powershell
schtasks /Create /SC ONLOGON /TN "Semester OS" /TR "`"$PWD\semester-os.cmd`" start --background --no-browser"
```

Stop with `.\semester-os.cmd stop`. Remove with `schtasks /Delete /TN "Semester OS" /F`.
