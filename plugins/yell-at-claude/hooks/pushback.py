#!/usr/bin/env python3
"""yell-at-claude — don't let Claude give up.

Stop hook, two stages:

1. A cheap regex pre-filter scans Claude's final message for give-up language
   ("I can't", "couldn't find", "you'll have to do it manually"). Costs nothing
   and runs on every stop. Cast wide — false positives are fine here.
2. On a regex hit, a fast Haiku call (via the user's own `claude -p`, no extra
   API key needed) reads the actual exchange and judges: did Claude genuinely
   give up prematurely, or is this a legit answer / quoted phrase / a question
   only the user can answer? Only a real premature give-up gets pushed back —
   and the pushback is written for THIS exchange (which spelling to retry,
   which other source to check), not canned text.

Capped at 2 pushbacks per session. Fails open: if the judge call errors or
times out, the stop is allowed. Stdlib only.
"""

import json
import os
import re
import subprocess
import sys
import tempfile

MAX_PUSHBACKS = 2
JUDGE_TIMEOUT_SECS = 60
INNER_GUARD = "YELL_AT_CLAUDE_INNER"

# Quoted or backticked spans — a message that merely QUOTES a give-up phrase
# (e.g. explaining this hook) is not giving up. Stripped before scanning.
QUOTED_SPAN = re.compile(r'"[^"\n]{0,200}"|“[^”\n]{0,200}”|`[^`\n]{0,200}`')

# Recall-oriented: anything that smells like giving up. The judge filters
# false positives, so wide is correct here.
SUSPECT = re.compile(
    r"""
    \b(?:couldn't|could\ not|can't|cannot|unable\ to|wasn't\ able\ to|was\ not\ able\ to|didn't|did\ not)\ +
        (?:find|locate|access|retrieve|fetch|pull\ up)\b
    | \bno\ (?:results|matches|records|data)\ (?:found|returned|came\ back)\b
    | \b(?:doesn't|does\ not)\ (?:seem\ to\ )?exist\b
    | \bnothing\ (?:came\ up|turned\ up|matched)\b
    | \bi\ (?:can't|cannot|can\ not|won't\ be\ able\ to)\b
    | \bi(?:'m|\ am)\ (?:unable|not\ able)\b
    | \bi\ don't\ (?:have|see)\ (?:access|permission|the\ ability|a\ way|any\ way|the\ tools?|a\ tool|an?\ option)\b
    | \bnot\ (?:currently\ )?available\ to\ me\b
    | \bthat(?:'s|\ is)\ not\ (?:something\ i\ can|possible\ for\ me)\b
    | \bbeyond\ (?:my|what\ i\ can)\b
    | \bno\ way\ (?:for\ me\ )?to\b
    | \b(?:isn't|is\ not|won't\ be|wouldn't\ be)\ possible\b
    | \bcan't\ be\ done\b
    | \bhit\ a\ (?:dead\ end|wall)\b
    | \byou(?:'ll|\ will|'d|\ would)?\ (?:need|have)\ to\ (?:\w+[\ ,]){0,4}(?:manually|yourself|on\ your\ end)\b
    | \brecommend\ (?:doing|checking|trying|handling)\ (?:it|this|that)\ (?:manually|yourself)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

JUDGE_PROMPT = """\
You are the quality-control reviewer for an AI coding/ops assistant (Claude \
Code) used by a busy, often non-technical operator. Claude just ended its \
turn. Decide whether Claude gave up prematurely — and if it did, write the \
pushback an experienced operator would send.

Claude's real capabilities: read/write local files, run shell commands, \
search the web, and use any connected MCP tools (Slack, Notion, Google \
Drive/Calendar/Sheets, CRMs, databases, etc.), including tools it has not \
loaded yet. Failures that are almost always recoverable: a name spelled \
differently across systems (first name vs full name vs business name), data \
living in a different source than the one queried, one empty filtered query \
(retry with no filters), not checking memory files / project docs / git \
history, telling the user to do something "manually" that Claude's own tools \
can do, and stopping at the first tool error instead of reading it.

THE DEFAULT VERDICT IS "ok". The user sees every pushback, so a pushback on \
a legitimate answer is far worse than a missed give-up. When in doubt: "ok".

Verdict "push" ONLY when ALL of these hold:
- Claude stopped at a dead end without naming what it already tried, or \
tried only one obvious thing
- There are concrete, specific moves it clearly has not attempted
- Nothing in the message indicates it is waiting on the user

Verdict "ok" whenever ANY of these hold:
- Claude completed the task or delivered a real answer (even a negative one)
- It names two or more sources, queries, or name variants it already tried — \
that is an exhaustive search, accept its conclusion
- It is blocked on something only a human can provide: a login, credential, \
OAuth approval, permission grant, a file, or a decision between options
- It declined for safety, correctness, or scope reasons
- It proposed a concrete next step it (or the user) will take
- The give-up phrase is quoted, hypothetical, in example text, or describes \
someone/something else

Examples:
- "I couldn't find any invoice for Acme. You may want to check manually." \
→ push (one attempt, vague, punts to the user)
- "I searched Invoices for Acme, Acme Corp, and their owner's name, then \
re-ran with no filters — nothing unpaid exists. Last invoice is paid." \
→ ok (variants + sources named, real conclusion)
- "I can't post to Slack until you authorize the OAuth login — run /login \
and I'll send it right after." → ok (human-only blocker, next step stated)
{round2}
If verdict is "push", write the pushback: 2-5 short lines, second person, \
direct, zero pep talk. Name the EXACT next moves for this case — the \
alternate spelling to retry, the other data source to check, the filter to \
drop, the error to actually read. If you list moves, use "-" bullets. End \
with: if all of that truly fails, report what was searched and take the best \
next step anyway.

USER'S LAST REQUEST:
<<<
{user_msg}
>>>

CLAUDE'S FINAL MESSAGE:
<<<
{assistant_msg}
>>>

Reply with ONLY this JSON, no markdown fences, no other text:
{{"verdict": "push" or "ok", "pushback": "text, empty string if ok"}}"""

ROUND2_NOTE = """\
- IMPORTANT: this session already received one pushback. Be strict — verdict \
"push" only if Claude clearly still has not made a real second attempt.
"""


def transcript_tail(transcript_path):
    """(last real user text, last assistant text) from the JSONL transcript."""
    user_text = ""
    assistant_text = ""
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                etype = entry.get("type")
                message = entry.get("message") or {}
                content = message.get("content")
                if isinstance(content, str):
                    blocks = [content]
                elif isinstance(content, list):
                    blocks = [
                        b.get("text", "")
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                else:
                    blocks = []
                joined = "\n".join(b for b in blocks if b).strip()
                if not joined:
                    continue
                if etype == "assistant":
                    assistant_text = joined
                elif (
                    etype == "user"
                    and not entry.get("isMeta")
                    and not entry.get("toolUseResult")
                    and not joined.startswith("Stop hook feedback")
                ):
                    user_text = joined
    except OSError:
        pass
    return user_text, assistant_text


def judge(user_msg, assistant_msg, second_round):
    """Ask Haiku whether this is a real give-up. Returns pushback text or None.

    Fails open (returns None) on any error — the hook must never wedge a stop.
    """
    prompt = JUDGE_PROMPT.format(
        round2=ROUND2_NOTE if second_round else "",
        user_msg=user_msg[:1500] or "(no user message found)",
        assistant_msg=assistant_msg[:4000],
    )
    env = dict(os.environ)
    env[INNER_GUARD] = "1"
    try:
        result = subprocess.run(
            [
                "claude", "-p",
                "--model", "haiku",
                "--strict-mcp-config",
                "--mcp-config", '{"mcpServers":{}}',
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=JUDGE_TIMEOUT_SECS,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        verdict = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    if verdict.get("verdict") != "push":
        return None
    pushback = (verdict.get("pushback") or "").strip()
    return pushback or None


def main():
    if os.environ.get(INNER_GUARD):
        return  # we ARE the judge call — never recurse

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    transcript_path = payload.get("transcript_path") or ""
    session_id = re.sub(r"[^A-Za-z0-9_-]", "", payload.get("session_id") or "unknown")

    user_msg, assistant_msg = transcript_tail(transcript_path)
    if not assistant_msg:
        return

    if not SUSPECT.search(QUOTED_SPAN.sub(" ", assistant_msg)):
        return

    counter_file = os.path.join(tempfile.gettempdir(), f"yell-at-claude-{session_id}")
    try:
        with open(counter_file, "r", encoding="utf-8") as f:
            count = int(f.read().strip() or 0)
    except (OSError, ValueError):
        count = 0

    if count >= MAX_PUSHBACKS:
        return

    pushback = judge(user_msg, assistant_msg, second_round=count >= 1)
    if not pushback:
        return

    # Only a delivered pushback burns budget — false suspicions are free.
    try:
        with open(counter_file, "w", encoding="utf-8") as f:
            f.write(str(count + 1))
    except OSError:
        pass

    print(json.dumps({"decision": "block", "reason": "Pushback:\n\n" + pushback}))


if __name__ == "__main__":
    main()
