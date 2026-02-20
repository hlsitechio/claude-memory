---
name: save
description: |
  Manually save current session state to .mci file.
  Use when you want to checkpoint before a risky operation or heavy context usage.
---

# Save Session State

Perform a manual save by snapshotting `state.md` into the session's `memory.mci` file.

## What To Do

1. Find the current session path by reading `.claude-memory/current-session` in the project root
2. If that file doesn't exist, scan `.claude-memory/sessions/` for today's latest session directory
3. Read `state.md` from the session directory and extract:
   - **Goal** section (## Goal)
   - **Progress** section (## Progress)
   - **Findings** section (## Findings)
4. If state.md is missing or empty, fall back to reading marker files:
   - `facts.md` — latest `[!]` entries
   - `context.md` — latest `[*]` entries
   - `intent.md` — latest `[>]` entries
5. Append the triplet to `memory.mci` in this format:

```
--- [PC] Manual Save @ HH:MM ---
Memory: GOAL: <goal content>
Context: PROGRESS: <progress content>
Intent: FINDINGS: <findings content>
```

6. Confirm the save with:
```
[+] Session state saved to memory.mci
    Goal: <brief summary>
    Progress: <X done, Y pending>
    Findings: <brief summary>
```

## If No Session Exists

If no active session directory is found:
```
[-] No active session found. Start a new session first.
```

## Important

- state.md is the PRIMARY source — always try it first
- Always include all three lines (Memory, Context, Intent) even if some are sparse
- Keep each line concise — the .mci must stay lean
- This is a MANUAL save — the hooks handle automatic saves on compact and session end
