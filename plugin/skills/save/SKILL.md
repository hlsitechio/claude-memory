---
name: save
description: |
  Manually save current session state to .mci file.
  Use when you want to checkpoint before a risky operation or heavy context usage.
---

# Save Session State

Perform a manual pre-compact save by writing a `[PC]` entry to the session's `memory.mci` file.

## What To Do

1. Find the current session path by reading `.claude-memory/current-session` in the project root
2. If that file doesn't exist, scan `.claude-memory/sessions/` for today's latest session directory
3. Read the current state from the session's marker files:
   - `facts.md` — latest `[!]` entries (what happened)
   - `context.md` — latest `[*]` entries (why it matters)
   - `intent.md` — latest `[>]` entries (where we're going)
4. Assemble a Memory/Context/Intent triplet from the latest entries
5. Append the triplet to `memory.mci` in this format:

```
--- [PC] Manual Save @ HH:MM ---
Memory: <summary of latest facts>
Context: <summary of latest context>
Intent: <summary of latest intent/next steps>
```

6. Confirm the save with:
```
[+] Session state saved to memory.mci
    Memory: <brief summary>
    Context: <brief summary>
    Intent: <brief summary>
```

## If No Session Exists

If no active session directory is found:
```
[-] No active session found. Start a new session first.
```

## Important

- Always include all three lines (Memory, Context, Intent) even if some are sparse
- Keep each line to 1-2 sentences — the .mci must stay lean
- This is a MANUAL save — the hooks handle automatic saves on compact and session end
