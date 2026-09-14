# Calendars

All on the **Connect** page.

| Piece | Direction | Setup |
| --- | --- | --- |
| Calendar feed | Semester OS to your calendar app | Paste one link (default) |
| Import feeds | Outlook and Brightspace into Semester OS | Two URLs in `config.yaml` (optional) |
| Google Calendar (OAuth) | Writes into your Google primary calendar | Cloud project, OAuth client (advanced) |

## The calendar feed

An RFC 5545 feed at `http://127.0.0.1:8790/calendar/<secret>.ics`.

- **Classes:** one recurring event per weekly meeting with room, in your `timezone` with a full `VTIMEZONE` (DST-safe).
- **Deadlines:** a 30-minute block ending at the deadline, or all-day if only a date is known. Exams with an end time are real blocks. Submitted and graded work stays, prefixed `✓ `.
- **Events** added through Notes.
- Covers the last 30 days through the end of term (at least 200 days). Stable UIDs and a `SEQUENCE` that only bumps on change, so apps update in place. `CATEGORIES` and `COLOR` are set.
- Excluded: your Outlook, Brightspace and Google events (you already have them), and cancelled or dropped items (omitted, not `STATUS:CANCELLED`, since apps render that inconsistently).

### Protection

The only address that works without the dashboard token.

- 256-bit secret in `data/.calendar_feed.json` (owner-only), constant-time compare. Wrong secret: `404`.
- **Rotate link** on Connect kills old subscriptions immediately. Rotate if the link was ever shared.
- Logged as `/calendar/<redacted>.ics`. Sent with `Cache-Control: private, no-cache` and `noindex`.
- Read-only: it exposes your schedule and deadline notes, nothing else.

## Which apps can use the local link

Only apps that fetch the feed from your own computer. Provider servers cannot reach `127.0.0.1`.

| App | Fetched by | Works? |
| --- | --- | --- |
| Apple Calendar on this Mac, location **On My Mac** | This Mac | Yes, live |
| Apple Calendar, location **iCloud** | Apple's servers | No |
| Classic Outlook for Windows (Internet Calendars) | This PC | Yes, live |
| Google Calendar ("From URL") | Google's servers | No |
| Outlook on the web, new Outlook for Windows and Mac | Microsoft's servers | No |
| Any phone | The phone or its cloud | No |

**Apple Calendar:** *Open in Apple Calendar* on Connect, or *File > New Calendar Subscription*. Location **On My Mac**, auto-refresh hourly.

**Classic Outlook:** *File > Account Settings > Account Settings > Internet Calendars > New*, paste, *Add*.

## Google Calendar and phones

| You want | Do this |
| --- | --- |
| Zero exposure | [Import a downloaded .ics](#1-import-a-downloaded-ics) for classes; check deadlines in Semester OS |
| Live, nothing exposed | [Google Calendar with OAuth](#3-google-calendar-with-oauth) |
| Live, any app | [Tunnel](#2-public-address-through-a-tunnel) limited to `/calendar` |

### 1. Import a downloaded .ics

**Download .ics**, then import into a dedicated calendar (Google: *Settings > Import & export*; Outlook web: *Add calendar > Upload from file*). The copy never updates and re-importing does not remove deleted items; to refresh, delete the calendar and import again.

### 2. Public address through a tunnel

Save the tunnel's `https://` name on Connect under **Public address** to get a public feed link.

**Tailscale Funnel** (recommended: stable name, HTTPS to your machine, free, single path):

```sh
tailscale funnel --bg --https=443 --set-path=/calendar http://127.0.0.1:8790/calendar
```

Save `https://<your-machine>.<your-tailnet>.ts.net`. From a phone on mobile data, the feed link should download and the bare address should not. Stop: `tailscale funnel --https=443 off`.

**cloudflared:** `cloudflared tunnel --url http://127.0.0.1:8790` works without an account, but the name changes every start. Named tunnels need a domain, and Cloudflare terminates TLS. Do **not** pass `--http-host-header`.

The server enforces:

- The public address serves **only** `GET /calendar/<secret>.ics`; everything else is `404`.
- Requests with forwarding headers (`X-Forwarded-For`, `Forwarded`, `CF-Connecting-IP`, etc.) are treated as internet traffic, even with `Host: 127.0.0.1`.
- Unknown tunnel hosts are refused. The public address must be a bare `https://` host.

Risks: the feed is on the internet behind only its secret; Google and Microsoft keep a copy; the tunnel is another exposed program (limit it, update it, turn it off); nothing updates while your computer sleeps; Google refreshes every 8 to 24 hours regardless of the feed's hint.

### 3. Google Calendar with OAuth

The Google Calendar card writes classes, deadlines and events to your primary calendar through Google's API, within minutes. Needs a Google Cloud project, an OAuth client at `data/.google_oauth_client.json`, and, in Testing mode, signing in again every seven days.

### Not offered

- **Synced folders or secret Gists:** third-party copies with no rotation, and Google cannot subscribe to most of them.
- **Listening on `0.0.0.0`:** would expose the dashboard to the whole network.

## Import feeds: Outlook and Brightspace

Fetched every 30 minutes, shown on Today and Week:

```yaml
calendar_feeds:
  outlook: https://outlook.office365.com/owa/calendar/…/calendar.ics
  brightspace: https://yourschool.brightspace.com/d2l/le/calendar/feed/user/feed.ics?token=…
```

Both are credentials, never logged. Applied on the next sync, no restart.

**Brightspace:** *Calendar* (often under *Course Tools*) > *Subscribe* (maybe behind the gear or *…*) > *All Courses*, copy the `.ics` address.

**Outlook:** Outlook on the web, *Settings > Calendar > Shared calendars > Publish a calendar*, *Can view all details*, *Publish*, copy the **ICS** link. Missing section means your school disabled it.
