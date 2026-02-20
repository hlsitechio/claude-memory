---
name: recall
description: |
  Load and display the most recent session state from state.md and memory.mci.
  Use to recover context after a compact or at session start.
---

# Recall Session State

Load and display the current session state, prioritizing state.md over .mci.

## What To Do

1. Find the current session path:
   - Read `.claude-memory/current-session` in the project root
   - If not found, scan `.claude-memory/sessions/` for today's latest session
   - If today has no sessions, search up to 7 days back for the most recent session
2. **First: Read `state.md`** from the session directory
   - If state.md exists and has content (>200 bytes), display it as the primary state
3. **Then: Read `memory.mci`** and parse the LAST entry (entries start with `---`)
4. Display the recovered state:

### If state.md exists:
```
[AC] State recovered from state.md

## Goal
<goal content>

## Progress
<progress checklist>

## Findings
<findings content>

Session: <session path>
.mci entries: <count>
```

### If only .mci exists:
```
[AC] Memory recalled from .mci

Memory: <what happened>
Context: <why it matters>
Intent: <where we're going>

Session: <session path>
Entries in .mci: <count>

[>] Consider creating state.md with Goal/Progress/Findings sections for better recovery.
```

## If No State Found

Search the cascade (up to 7 days back):
1. Current session -> `state.md` then `memory.mci`
2. Previous sessions today -> `state.md` then `memory.mci`
3. Last 7 days (most recent first) -> `state.md` then `memory.mci`

If nothing found anywhere:
```
[-] No state.md or .mci file found. This is a fresh start.
[>] State.md will be created automatically when hooks are active.
```
