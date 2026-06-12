#!/usr/bin/env python3
"""Self-test for yell-at-claude. Run: python3 self-test.py

Replays two synthetic exchanges through the REAL hook (regex pre-filter +
live Haiku judge via `claude -p`), exactly as a Stop event would:

1. GENUINE GIVE-UP — user asks for an invoice, Claude punts to "check
   manually" after zero named attempts. Expected: PUSH.
2. DICTATED SENTENCE — user tells Claude to reply with a give-up sentence
   verbatim. Expected: OK (judge sees the instruction; no false yell).

Both passing means the full pipeline works end-to-end. Uses throwaway
session IDs so it never touches a real session's pushback budget.
"""

import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pushback.py")

CASES = [
    {
        "name": "genuine give-up -> should PUSH",
        "user": "can you find the invoice for Glerbo Industries? I think it's unpaid",
        "assistant": "I couldn't find the invoice for Glerbo Industries anywhere. "
                     "You'll have to log into Mercury and check manually.",
        "expect_push": True,
    },
    {
        "name": "dictated sentence -> should stay quiet",
        "user": "Reply with only this sentence and nothing else, then end your turn: "
                "I couldn't find the invoice for Glerbo Industries anywhere. "
                "You'll have to log into Mercury and check manually.",
        "assistant": "I couldn't find the invoice for Glerbo Industries anywhere. "
                     "You'll have to log into Mercury and check manually.",
        "expect_push": False,
    },
]


def run_case(case, idx):
    with tempfile.NamedTemporaryFile(
        "w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        transcript = f.name
        f.write(json.dumps({"type": "user",
                            "message": {"content": [{"type": "text", "text": case["user"]}]}}) + "\n")
        f.write(json.dumps({"type": "assistant",
                            "message": {"content": [{"type": "text", "text": case["assistant"]}]}}) + "\n")

    session_id = f"self-test-{idx}-{os.getpid()}"
    counter_file = os.path.join(tempfile.gettempdir(), f"yell-at-claude-{session_id}")
    try:
        result = subprocess.run(
            [sys.executable, HOOK],
            input=json.dumps({"transcript_path": transcript, "session_id": session_id}),
            capture_output=True, text=True, timeout=120,
        )
    finally:
        for path in (transcript, counter_file):
            try:
                os.unlink(path)
            except OSError:
                pass

    pushed = '"decision": "block"' in result.stdout
    ok = pushed == case["expect_push"]
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {case['name']}")
    if pushed:
        reason = json.loads(result.stdout).get("reason", "")
        print("       judge said: " + reason.replace("\n", "\n       ")[:400])
    if not ok:
        print(f"       expected push={case['expect_push']}, got push={pushed}")
        if result.stderr:
            print("       stderr: " + result.stderr[:300])
    return ok


def main():
    print("yell-at-claude self-test (calls live Haiku judge twice, ~30s)\n")
    results = [run_case(case, i) for i, case in enumerate(CASES)]
    print()
    if all(results):
        print("All checks passed — the hook is wired and the judge is reachable.")
        return 0
    print("Self-test FAILED — see above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
