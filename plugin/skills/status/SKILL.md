---
name: status
description: |
  Display current session status including state.md health, .mci validity, marker counts, and file sizes.
  Use to check the health of your memory system.
---

# Session Status

Display a comprehensive status dashboard for the current claude-memory session.

## What To Do

1. Find the current session path:
   - Read `.claude-memory/current-session` in the project root
   - If not found, scan `.claude-memory/sessions/` for today's latest session
2. For the active session directory, gather:
   - **Session path** (date and session number)
   - **state.md status**: ACTIVE (>200 bytes) / TEMPLATE (<200 bytes) / MISSING
   - **state.md size**: byte count
   - **state.md last updated**: from the `> Last updated:` line
   - **.mci status**: valid (has Memory+Context+Intent), partial, or empty
   - **.mci entry count**: number of `---` delimited entries
   - **Marker counts**: number of entries in facts.md, context.md, intent.md, memory.md
   - **File sizes**: size of each session file
   - **Compact backups**: list any compact-*.md files
   - **Session age**: when the session was created
3. Display as a formatted dashboard:

```
🧠 claude-memory v2.0.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📂 Session: .claude-memory/sessions/YYYY-MM-DD/session-N/
⏱️  Started: HH:MM | Age: Xh Ym

📝 state.md: ✅ ACTIVE (X bytes) | ⚠️ TEMPLATE | ❌ MISSING
   Last updated: HH:MM

🛡️ .mci: ✅ Valid (N entries) | ⚠️ Partial | ❌ Empty
   Last entry: <type> @ HH:MM

📊 Legacy Markers:
   [!] facts.md     — X entries (Y bytes)
   [*] context.md   — X entries (Y bytes)
   [>] intent.md    — X entries (Y bytes)
   [i] memory.md    — X entries (Y bytes)

💾 Compact Backups: N files

📏 Total Session Size: X KB
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## If No Session Exists

```
🧠 claude-memory v2.0.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
❌ No active session found.
[>] Sessions are created automatically when hooks are active.
    Start Claude Code in a project with claude-memory installed.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Counting Entries

- Count `## ` prefixed lines in .md files for marker entry counts
- Count `---` lines in .mci for entry counts
- Use `wc -c` for file sizes
- state.md status: MISSING (no file), TEMPLATE (<200 bytes), ACTIVE (>200 bytes)
