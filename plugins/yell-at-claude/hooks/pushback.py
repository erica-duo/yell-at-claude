#!/usr/bin/env python3
"""yell-at-claude — don't let Claude give up.

Stop hook. Reads the session transcript, checks Claude's final message for
give-up language ("I can't", "couldn't find", "I don't have access"), and if
found, blocks the stop and feeds back a pushback prompt so Claude keeps
digging — the same way an experienced operator would respond. Capped at 2
pushbacks per session so it can never loop forever.

Stdlib only. Exits 0 with no output to allow the stop.
"""

import json
import os
import re
import sys
import tempfile

MAX_PUSHBACKS = 2

# Quoted or backticked spans — a message that merely QUOTES a give-up phrase
# (e.g. explaining the hook itself) is not giving up. Stripped before scanning.
QUOTED_SPAN = re.compile(r'"[^"\n]{0,200}"|“[^”\n]{0,200}”|`[^`\n]{0,200}`')

CANT_FIND = re.compile(
    r"""
    \b(?:couldn't|could\ not|can't|cannot|unable\ to|wasn't\ able\ to|was\ not\ able\ to|didn't|did\ not)\ +
        (?:find|locate|access|retrieve|fetch|pull\ up)\b
    | \bno\ (?:results|matches|records|data)\ (?:found|returned|came\ back)\b
    | \b(?:doesn't|does\ not)\ (?:seem\ to\ )?exist\b
    | \bnothing\ (?:came\ up|turned\ up|matched)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

CANT_DO = re.compile(
    r"""
    \bi\ (?:can't|cannot|can\ not|won't\ be\ able\ to)\b
    | \bi(?:'m|\ am)\ (?:unable|not\ able)\b
    | \bi\ don't\ have\ (?:access|the\ ability|a\ way|permission|the\ tools?)\b
    | \bthat(?:'s|\ is)\ not\ (?:something\ i\ can|possible\ for\ me)\b
    | \bbeyond\ (?:my|what\ i\ can)\b
    | \byou(?:'ll|\ will)\ (?:need|have)\ to\ do\ (?:this|that|it)\ (?:manually|yourself)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

PUSHBACK_FIND = (
    "Pushback — \"not found\" isn't a final answer yet. Try all of these first:\n"
    "\n"
    "- Alternate spellings and name variants (first name, full name, company name, "
    "abbreviations — different tools name things differently)\n"
    "- The same query with NO filters, to confirm the data source is responding at all\n"
    "- At least one other data source — the answer is rarely in only one place\n"
    "- Memory files, project docs, and git history for prior context\n"
    "\n"
    "If all of that is truly exhausted: report what you searched (sources and queries), "
    "your best guess at where it lives, and the next step — then take that step yourself."
)

PUSHBACK_DO = (
    "Pushback — you have more tools than you think (files, shell, web, every MCP server). "
    "Before saying it can't be done:\n"
    "\n"
    "- Re-check your available tools, including MCP tools you haven't loaded yet\n"
    "- Try a different route — a small script, smaller steps, or a different tool\n"
    "- Check memory and project docs for how this was done before\n"
    "- If a tool errored, read the actual error and fix that one thing\n"
    "\n"
    "If it's genuinely impossible: explain exactly why, propose the closest thing you "
    "CAN do, and then do it."
)

PUSHBACK_FINAL = (
    "Pushback, final round — re-read your last answer like a skeptical client would. "
    "Did you try everything, or stop at the first dead end?\n"
    "\n"
    "Make one more serious attempt with a tool or source you have NOT tried yet. "
    "Then either deliver the result, or list what you tried, why each attempt failed, "
    "and one concrete next step a non-technical reader can act on."
)


def last_assistant_text(transcript_path):
    """Concatenated text blocks of the final assistant message in the JSONL transcript."""
    text = ""
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
                if entry.get("type") != "assistant":
                    continue
                content = (entry.get("message") or {}).get("content") or []
                if isinstance(content, str):
                    blocks = [content]
                else:
                    blocks = [
                        b.get("text", "")
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                joined = "\n".join(b for b in blocks if b)
                if joined.strip():
                    text = joined
    except OSError:
        return ""
    return text


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    transcript_path = payload.get("transcript_path") or ""
    session_id = re.sub(r"[^A-Za-z0-9_-]", "", payload.get("session_id") or "unknown")

    message = last_assistant_text(transcript_path)
    if not message:
        return

    message = QUOTED_SPAN.sub(" ", message)

    found_cant_find = bool(CANT_FIND.search(message))
    found_cant_do = bool(CANT_DO.search(message))
    if not (found_cant_find or found_cant_do):
        return

    counter_file = os.path.join(tempfile.gettempdir(), f"yell-at-claude-{session_id}")
    try:
        with open(counter_file, "r", encoding="utf-8") as f:
            count = int(f.read().strip() or 0)
    except (OSError, ValueError):
        count = 0

    if count >= MAX_PUSHBACKS:
        return

    try:
        with open(counter_file, "w", encoding="utf-8") as f:
            f.write(str(count + 1))
    except OSError:
        pass

    if count >= 1:
        reason = PUSHBACK_FINAL
    elif found_cant_find:
        reason = PUSHBACK_FIND
    else:
        reason = PUSHBACK_DO

    print(json.dumps({"decision": "block", "reason": reason}))


if __name__ == "__main__":
    main()
