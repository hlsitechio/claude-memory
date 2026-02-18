---
name: status
description: |
  Display current session status including path, marker counts, .mci validity, and file sizes.
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
   - **Marker counts**: number of entries in facts.md, context.md, intent.md, memory.md
   - **.mci status**: valid (has Memory+Context+Intent), partial, or empty
   - **.mci entry count**: number of `---` delimited entries
   - **File sizes**: size of each session file
   - **Compact backups**: list any compact-*.md files
   - **Session age**: when the session was created
3. Display as a formatted dashboard:

```
🧠 claude-memory status
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📂 Session: .claude-memory/sessions/YYYY-MM-DD/session-N/
⏱️  Started: HH:MM | Age: Xh Ym

📊 Markers:
   [!] facts.md     — X entries (Y bytes)
   [*] context.md   — X entries (Y bytes)
   [>] intent.md    — X entries (Y bytes)
   [i] memory.md    — X entries (Y bytes)

🛡️ .mci Status: ✅ Valid (N entries) | ⚠️ Partial | ❌ Empty
   Last entry: <type> @ HH:MM

💾 Compact Backups: N files
   - compact-HH:MM:SS.md (X bytes)

📏 Total Session Size: X KB
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## If No Session Exists

```
🧠 claude-memory status
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
