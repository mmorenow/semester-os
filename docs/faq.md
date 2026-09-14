# FAQ

## Privacy

### Does my data leave my computer?

Not by itself: no account, telemetry or cloud. Only through features you turn on:

- **AI features.** Note or syllabus text goes to Anthropic through Claude Code, under your account. Course URLs are fetched by Claude Code's `WebFetch`.
- **Calendar import.** The server downloads the feed URLs in `config.yaml`.
- **Google Calendar sync** (off by default) writes events to your Google calendar.
- **A tunnel** you run for the calendar feed ([calendar.md](calendar.md)).

Details: [SECURITY.md](../SECURITY.md).

### Can anyone on my Wi-Fi see my dashboard?

No. It only accepts connections from your own computer, and not from other websites.

### Is my data used to train AI models?

Your Claude account settings decide that, not Semester OS.

## Cost

### Is it free?

Yes, MIT licensed.

### Do the AI features cost extra?

They use your own Claude plan or API key and count toward its limits. Semester OS charges nothing.

### Does `./semester-os doctor` use my Claude usage?

No. It checks install and sign-in locally, without a model call.

## Schools and platforms

### Does it work at my university?

It should. Nothing is school-specific. Not affiliated with Purdue University or any institution.

### My school uses Canvas, Blackboard or Moodle.

Put its ICS subscription link in the `brightspace` slot of `calendar_feeds`; the name is only a label. Proper support is welcome ([CONTRIBUTING.md](../CONTRIBUTING.md)).

### My school uses Google Workspace, not Outlook.

Use Google Calendar on the Connect page, or put your school calendar's secret iCal address in the `outlook` slot.

## Running it

### Does it need to be running for my calendar to update?

Yes. See [run-in-background.md](run-in-background.md) to start it at login.

### Can I use it on my phone?

Not directly. Subscribe your phone's calendar to the feed instead ([calendar.md](calendar.md)).

### Can two students share one install?

No. One install, one student.

### How do I back up?

Copy `data/` and `config.yaml`; restore them into a fresh install ([configuration.md](configuration.md)).

### Something is broken. What do I send?

`./semester-os doctor` output in a [bug report](../.github/ISSUE_TEMPLATE/bug_report.md). It never prints feed links or tokens. Security issues: [SECURITY.md](../SECURITY.md).
