# Security

## Reporting a vulnerability

Use **GitHub private vulnerability reporting**: repository **Security** tab, **Report a vulnerability**. Do not open a public issue or PR.

Include steps and impact. Expect a reply within a week; you are credited unless you decline. Only the latest release and `main` get fixes.

## Threat model

**In scope:** web pages you visit, other programs and people on your network, anyone holding a leaked link or file.

**Out of scope:** someone who already controls your account or computer, and the security of services you connect (your university, Google, Anthropic).

### Loopback only

The server binds to `127.0.0.1`. There is no setting to change that.

### Web pages cannot use it

Every request must pass:

- **Host check.** Host must be `127.0.0.1:<port>` or `localhost:<port>`. Blocks DNS rebinding.
- **Token.** API calls need `X-SemesterOS-Token` (random, in `data/.semester_os_token`, owner-only). Exempt: the health check, `/api/bootstrap` (refuses cross-site Origin/Referer) and the Google OAuth callback (one-time `state` only).
- **Same origin.** Cross-site POST, PATCH, PUT and DELETE are refused. No CORS headers are sent.

The calendar feed (`/calendar/<secret>.ics`) needs no token since calendar apps cannot send one. It is read-only, guarded by a random secret, and rotatable on Connect. Treat it like a password. See [docs/calendar.md](docs/calendar.md).

### Agents run with restricted tools

The server runs `claude` under your own sign-in and:

- passes one tool via both `--allowedTools` and `--tools` so your settings cannot add more (`Read` for notes and files, `WebFetch` for course URLs, never both), never `--dangerously-skip-permissions`;
- builds the command as an argument list, never a shell string;
- validates answers against a closed vocabulary and writes nothing until you confirm;
- runs at most two at a time, ten minutes each.

A malicious document can attempt prompt injection; tool limits and the confirm step contain it.

### What is stored

All inside the repo folder and gitignored:

| Where | What |
| --- | --- |
| `data/semester.db` | Courses, assignments, grades, todos, notes, run history |
| `data/.semester_os_token` | API token (owner-only) |
| `data/.calendar_feed.json` | Calendar feed secret (owner-only) |
| `data/.google_oauth_client.json`, `data/.google_token.json` | Google credentials, if connected |
| `config.yaml` | Settings, including feed URLs (credentials) |
| `syllabi/` | Your syllabus files |

Data leaves only through features you turn on: AI features (text to Anthropic), calendar import (downloads your feed URLs), Google sync, and a tunnel you run.

Feed URLs, the token and the feed secret never appear in logs or errors.

### What you can do

- Keep the repo in your user account, not a shared or synced folder.
- Never paste `config.yaml`, `data/` contents or your feed link anywhere.
- Rotate the feed link if it was shared.
- Run `./semester-os doctor` after updates; it flags loose token file permissions.
