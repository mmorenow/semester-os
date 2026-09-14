#!/usr/bin/env python3
"""Stand-in for the Claude CLI during captures: answers from a file, no model call.

SEMESTER_OS_CLAUDE_BIN points here; the answer per agent comes from the JSON file in
SEMESTER_OS_CAPTURE_ANSWERS, e.g. {"school-editor": "```json\\n{...}\\n```", "delay_seconds": 1.5}.
"""

from __future__ import annotations

import json
import os
import sys
import time


def main() -> int:
    args = sys.argv[1:]
    agent = args[args.index("--agent") + 1] if "--agent" in args else ""
    path = os.environ.get("SEMESTER_OS_CAPTURE_ANSWERS", "")
    try:
        with open(path, encoding="utf-8") as handle:
            answers = json.load(handle)
    except (OSError, ValueError) as exc:
        print(f"fake_claude: cannot read SEMESTER_OS_CAPTURE_ANSWERS ({exc})", file=sys.stderr)
        return 2
    answer = answers.get(agent)
    if not isinstance(answer, str):
        print(f"fake_claude: no canned answer for agent {agent!r}", file=sys.stderr)
        return 2
    time.sleep(float(answers.get("delay_seconds", 1.5)))
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": answer}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
