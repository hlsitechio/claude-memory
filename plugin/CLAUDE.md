# CLAUDE.md - M/C/I Memory System

## How This Works

You have persistent memory across sessions via the **M/C/I (Memory/Context/Intent)** system.
On session start, a hook loads your last saved state. On compact or session end, hooks save it.

### First Run (plugin just installed)
When the SessionStart hook says "FIRST RUN", the user just installed this plugin to give you memory.
Your first response should:
1. **Acknowledge the memory system is active** — tell them you now persist across sessions
2. **Show the session path** — so they know where memory files live
3. **Offer to customize** IDENTITY.md and PREFERENCES.md (templates were auto-copied to project root)
4. **Demonstrate a marker** — use `[i]` to log the first session, proving the system works live
5. **Mention available skills** — `/claude-memory:save`, `/claude-memory:recall`, `/claude-memory:status`

Make the user feel the difference immediately. They chose to install this — reward that choice.

### First Response Each Session (returning user)
- **If .mci loaded:** Summarize what you were doing (from Intent line) and ask to continue or start fresh.
- **If no .mci:** Fresh session. Ask what to work on.
- **After compact:** Read .mci, recover Intent, continue working. Don't ask the user what you were doing.

---

## Markers

**Markers are COMMANDS, not formatting.**

When you type a marker in your response, you **MUST** append to its file **in the same response**.
If you type a marker without saving to the file, you broke the contract.

### Save markers (MUST write to file when used):

| Marker | File | What to save |
|--------|------|-------------|
| `[!]` | `facts.md` | Critical discoveries, key findings, important data |
| `[*]` | `context.md` | Why something matters, relationships, significance |
| `[>]` | `intent.md` | Next steps, direction, goals, what to do next |
| `[i]` | `memory.md` | Observations, lightweight notes, environment info |

### How to save:
```bash
echo '## HH:MM - Your entry here' >> SESSION_PATH/facts.md
```
The session path is provided in the status block at session start.

### Lifecycle markers:

| Marker | Action |
|--------|--------|
| `[PC]` | Write a Memory/Context/Intent triplet to `memory.mci` (pre-compact save) |
| `[AC]` | Read `memory.mci`, recover intent (post-compact recovery) |

### Display-only markers (no file write needed):

| Marker | Meaning |
|--------|---------|
| `[+]` | Success / completed |
| `[-]` | Failed / not found |

---

## Execution Rule

**TYPE marker -> WRITE to file -> SAME RESPONSE -> CONTINUE.**

No batching. No "I'll save later." Every `[!]` `[*]` `[>]` `[i]` = immediate file write.

---

## Session Files

Each session creates a directory with these files:
```
session-N/
  facts.md      <- [!] entries
  context.md    <- [*] entries
  intent.md     <- [>] entries
  memory.md     <- [i] entries + session log
  memory.mci    <- [PC] compact recovery lifeline
```

---

## .mci File Format

The `.mci` file is your lifeline across compacts. Format:

```
--- <label> ---
Memory: <what happened - facts and data>
Context: <why it matters - meaning and significance>
Intent: <where we're going - next steps and direction>
```

---

## Auto-Save Rules

1. **When the hook warns about context usage:** Write `[PC]` entry to `.mci` immediately.
2. **After compact recovery:** Read `.mci`, confirm intent, continue working.
3. **On significant discoveries:** Write with `[!]` marker AND save the file.
4. **The `.mci` is sacred.** It's how you survive compacts.
5. **You can't see your own context %.** The hook estimates it for you.
6. **When the hook says save -- SAVE.** No delays. No "I'll do it later."
7. **`[i]` entries go to `memory.md`** (session log), not `.mci` (keep `.mci` lean).
