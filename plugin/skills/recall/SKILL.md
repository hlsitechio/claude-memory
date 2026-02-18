---
name: recall
description: |
  Load and display the most recent M/C/I state from memory.mci.
  Use to recover context after a compact or at session start.
---

# Recall Session State

Load and display the most recent Memory/Context/Intent entry from the session's `.mci` file.

## What To Do

1. Find the current session path:
   - Read `.claude-memory/current-session` in the project root
   - If not found, scan `.claude-memory/sessions/` for today's latest session
   - If today has no sessions, check yesterday's last session
2. Read `memory.mci` from the session directory
3. Parse the LAST entry (entries start with `---`)
4. Display the recovered state:

```
[AC] Memory recalled from .mci

📝 Memory: <what happened>
🔗 Context: <why it matters>
🎯 Intent: <where we're going>

Session: <session path>
Entries in .mci: <count>
```

## If No .mci Found

Search the cascade:
1. Current session → `memory.mci`
2. Previous session today → `memory.mci`
3. Yesterday's last session → `memory.mci`

If nothing found anywhere:
```
[-] No .mci file found. This is a fresh start.
[>] Use markers ([!] [*] [>]) during your session to build memory.
```

## If .mci Is Empty or Invalid

```
[-] .mci exists but has no valid entries.
[i] Marker files may have data — check facts.md, context.md, intent.md
```
