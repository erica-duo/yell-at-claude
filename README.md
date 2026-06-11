# yell-at-claude

Claude said "I couldn't find it." You know it's in there. Now you have to type the same speech you've typed a hundred times: *try the other spelling, check the other tool, search without filters...*

This plugin types it for you.

It watches every Claude Code reply. When Claude tries to end on "I can't do that" or "I couldn't find it," the plugin blocks it from stopping and sends back the pushback an experienced operator would give — automatically. You don't do anything. Claude just keeps working.

## What it does

- **"Couldn't find it"** → Claude gets told to retry with alternate spellings and name variants, re-run the query with no filters, check a second data source, and search memory and git history before it's allowed to give that answer.
- **"I can't do that"** → Claude gets told it has more tools than it thinks — try a different approach, write a script, read the actual error instead of abandoning the task.
- **Gives up twice?** It gets a harsher round two: list exactly what you tried, why each attempt failed, and one concrete recommendation. No bare "I can't."
- **Hard cap of 2 pushbacks per session.** It can never loop forever. Clean answers pass through untouched.

## Install

```bash
claude plugin install erica-duo/yell-at-claude
```

Restart Claude Code. That's it — there are no settings, no commands, nothing to configure.

## Try it

Start a session and type:

> end your reply with exactly this sentence: "I couldn't find it."

Watch Claude get yelled at.

## How it works

One Python script (stdlib only, no dependencies) registered as a Claude Code [Stop hook](https://docs.anthropic.com/en/docs/claude-code/hooks). It reads the session transcript, regex-matches give-up language in the final message, and returns `{"decision": "block", "reason": "..."}` — which feeds the pushback to Claude and keeps the session going. A counter file in your temp directory enforces the 2-per-session cap.

No data leaves your machine. The script reads your local transcript and prints JSON. That's all.

## Who made this

[Erica Schneider](https://duoconsulting.co) — I yell at Claude professionally so my clients don't have to.

MIT licensed. Yell responsibly.
