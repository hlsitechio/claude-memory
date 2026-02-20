# CLAUDE.md - claude-memory v2

## How This Works

You have persistent memory across sessions via the **claude-memory v2** system powered by **state.md**.
On session start, a hook loads your last saved state. On compact or session end, hooks snapshot state.md.

## state.md — Your External Brain

`state.md` is a living document with 3 sections: **Goal**, **Progress**, **Findings**.
It lives on disk, survives compacts untouched. Keep it current.

### How to Use
1. **Update Goal** when mission changes (use Edit tool)
2. **Update Progress** as you work — check off tasks, add new ones
3. **Update Findings** when you discover important data
4. **Every 3-5 tool calls** — quick state.md update

### Post-Compact Recovery
1. Read `state.md` — your full state is there
2. Check Progress — see what's done, what's next
3. Resume from first unchecked item
4. DO NOT ask user what you were doing — state.md tells you

## Markers

| Marker | Meaning | state.md Action |
|--------|---------|----------------|
| `[+]` | Success | (display only) |
| `[-]` | Failed | (display only) |
| `[!]` | Critical | → Edit Findings |
| `[>]` | Next step | → Edit Progress |
| `[*]` | Context | → Edit Goal |
| `[i]` | Info | → Append to memory.md |

## Session Files
```
session-N/
  state.md        ← primary memory (v2)
  memory.mci      ← auto-generated safety net
  facts.md        ← legacy [!] backup
  context.md      ← legacy [*] backup
  intent.md       ← legacy [>] backup
  memory.md       ← session log
```

## Auto-Save
- Pre-compact hook snapshots state.md → .mci automatically
- Auto-checkpoint every ~10 prompts
- Stop hook snapshots at session end
- Legacy markers auto-captured for backward compat
