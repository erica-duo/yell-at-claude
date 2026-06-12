# yell-at-claude

Claude said "I couldn't find it." You know it's in there. Now you have to type the same speech you've typed a hundred times: *try the other spelling, check the other tool, search without filters...*

This plugin types it for you.

It watches every Claude Code reply. When Claude tries to end on "I can't do that" or "I couldn't find it," the plugin blocks it from stopping and sends back the pushback an experienced operator would give — automatically. You don't do anything. Claude just keeps working.

## What it does

v2 is smart about *when* to yell. Two stages:

1. **A free regex pre-filter** scans Claude's final message for give-up language. Costs nothing, runs on every reply, casts a wide net.
2. **A fast Haiku judge** (a few seconds, via your own `claude` CLI — no API key, no setup) reads the actual exchange and decides: did Claude genuinely give up early, or is this a real answer?

It only yells at **lazy give-ups** — one vague attempt, then "you may want to check manually." And the pushback isn't canned: the judge writes it for *your* exchange — the exact name variant to retry, the other data source to check, the filter to drop.

It stays quiet when Claude:

- delivered a real answer, even a negative one
- names the sources and spelling variants it already tried (a real exhaustive search)
- is blocked on something only you can provide — a login, an OAuth approval, a decision
- declined for a good reason, or merely *quoted* a give-up phrase

**Hard cap of 2 pushbacks per session.** It can never loop forever, and only delivered pushbacks count against the cap.

## Install

```bash
claude plugin install erica-duo/yell-at-claude
```

Restart Claude Code. That's it — there are no settings, no commands, nothing to configure. Requires a logged-in `claude` CLI (you have one — you're running Claude Code).

## Try it

Start a session and ask Claude to find something using a name it'll miss on the first query — then watch what happens when it tries to shrug.

## How it works

One Python script (stdlib only, no dependencies) registered as a Claude Code [Stop hook](https://code.claude.com/docs/en/hooks). It reads the session transcript, regex-matches give-up language in the final message, and on a hit shells out to `claude -p --model haiku` (MCP servers disabled, recursion-guarded by an env var) to judge the exchange and write the pushback. A "push" verdict returns `{"decision": "block", "reason": "..."}` — which feeds the pushback to Claude and keeps the session going. A counter file in your temp directory enforces the 2-per-session cap.

Fails open: if the judge call errors or times out, Claude is allowed to stop. The hook will never wedge your session.

Your transcript text goes only to your own Claude account via your own CLI — the same place it already lives. Nothing else leaves your machine.

## Who made this

[Erica Schneider](https://duoconsulting.co) — I yell at Claude professionally so my clients don't have to.

MIT licensed. Yell responsibly.
