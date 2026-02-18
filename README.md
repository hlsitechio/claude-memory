# claude-memory

**Persistent memory for Claude Code sessions using the M/C/I system.**

Claude Code starts every session blank. When the context window fills up, auto-compact fires and your conversation history is compressed. Next session? Complete amnesia.

**claude-memory** fixes this with a lightweight hook-based system that automatically saves and restores your working state across sessions and compacts.

---

## How It Works

### The Problem

```
Session 1: You build something complex over 2 hours
            ↓ context fills up
            ↓ auto-compact fires
Session 1 (continued): Claude forgot everything
            ↓ session ends
Session 2: Total amnesia. "What were we working on?"
```

### The Solution: M/C/I (Memory / Context / Intent)

Every piece of knowledge is stored as an atomic triplet:

- **Memory** — What happened (facts, data, discoveries)
- **Context** — Why it matters (meaning, relationships, significance)
- **Intent** — Where we're going (next steps, direction, goals)

Four hooks automate the lifecycle:

```
┌─────────────────────────────────────────────────────┐
│ SessionStart                                        │
│ → Creates/resumes session directory                 │
│ → Loads last .mci file (your saved state)           │
│ → Injects M/C/I rules so Claude knows the system    │
├─────────────────────────────────────────────────────┤
│ UserPromptSubmit (every prompt)                     │
│ → Captures markers from Claude's last response      │
│ → Estimates context usage                           │
│ → Warns when compact is approaching                 │
├─────────────────────────────────────────────────────┤
│ PreCompact (before auto-compact)                    │
│ → Safety net: saves state if Claude forgot          │
│ → 3-tier fallback: .mci → markers → JSONL emergency│
│ → Creates conversation backup                       │
├─────────────────────────────────────────────────────┤
│ Stop (session end)                                  │
│ → Ensures valid .mci exists for next session        │
│ → Generates session summary                         │
└─────────────────────────────────────────────────────┘
```

---

## Quick Start

```bash
git clone https://github.com/hlsitechio/claude-memory.git
cd claude-memory
./install.sh /path/to/your/project
```

The installer will:
1. Copy 4 hook scripts to your project's `.claude/hooks/`
2. Install `CLAUDE.md` with M/C/I rules
3. Generate `.claude/settings.local.json` with hook configuration
4. Create the `.claude-memory/sessions/` directory
5. Optionally install identity templates (`IDENTITY.md`, `PREFERENCES.md`)

Then start Claude Code in your project:
```bash
cd /path/to/your/project
claude
```

### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (v2.1.0+)
- [jq](https://jqlang.github.io/jq/download/) (JSON processor, used by hooks)

---

## Markers

Markers are how you (and Claude) save information during a session. When Claude types a marker in its response, it **must** also write it to the corresponding file.

| Marker | File | Purpose |
|--------|------|---------|
| `[!]` | `facts.md` | Critical discoveries, key findings |
| `[*]` | `context.md` | Why something matters, significance |
| `[>]` | `intent.md` | Next steps, direction, goals |
| `[i]` | `memory.md` | Observations, environment info |
| `[PC]` | `memory.mci` | Pre-compact save (Memory/Context/Intent triplet) |
| `[AC]` | — | Post-compact recovery (reads .mci) |
| `[+]` | — | Display only: success |
| `[-]` | — | Display only: failed |

### Example

When Claude writes this in a response:
```
[!] Found that the API rate limit can be bypassed by rotating User-Agent headers
```

It must also run:
```bash
echo '## 14:30 - Found that the API rate limit can be bypassed by rotating User-Agent headers' >> SESSION_PATH/facts.md
```

The `prompt-capture.sh` hook also captures markers as a backup, but Claude should save them directly for reliability.

---

## The .mci File

The `.mci` file is the compact recovery lifeline. It contains M/C/I triplets:

```
--- Session 3 ---
Memory: Built the user filtering API. Added 3 columns to users table. Found auth bypass.
Context: Preparing for v2.1 release. Auth bypass is a security issue blocking release.
Intent: Fix auth middleware, write tests, then merge the filtering PR.
```

When auto-compact fires, the `.mci` file survives because it's on disk, not in the context window. The next `SessionStart` hook loads it back, and Claude picks up exactly where it left off.

---

## Session Structure

Sessions are organized by date:

```
.claude-memory/
└── sessions/
    └── 2026-02-18/
        ├── session-1/
        │   ├── facts.md           ← [!] entries
        │   ├── context.md         ← [*] entries
        │   ├── intent.md          ← [>] entries
        │   ├── memory.md          ← [i] entries + session log
        │   ├── memory.mci         ← compact recovery lifeline
        │   ├── compact-12:17:29.md← conversation backup
        │   └── session-summary.md ← tool stats, files modified
        └── session-2/
            └── ...
```

- Sessions auto-resume if the last one was active within 30 minutes
- Otherwise, a new session directory is created
- The `.mci` loading cascade checks: current session → previous today → yesterday

---

## Configuration

### Hook Settings

The installer generates `.claude/settings.local.json`. If you need to add hooks manually:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash \"$CLAUDE_PROJECT_DIR/.claude/hooks/session-start.sh\""
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash \"$CLAUDE_PROJECT_DIR/.claude/hooks/prompt-capture.sh\"",
            "timeout": 5
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash \"$CLAUDE_PROJECT_DIR/.claude/hooks/pre-compact.sh\""
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash \"$CLAUDE_PROJECT_DIR/.claude/hooks/session-stop.sh\"",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

### Tunable Constants

In `hooks/prompt-capture.sh`, you can adjust context estimation thresholds:

```bash
CONTEXT_LIMIT=1000000   # Total JSONL bytes at compact (~167K tokens)
WARN_BYTES=700000       # ~70% - gentle checkpoint reminder
CRITICAL_BYTES=850000   # ~85% - strong [PC] save warning
EMERGENCY_BYTES=950000  # ~95% - save NOW
```

In `hooks/session-start.sh`:

```bash
RESUME_TIMEOUT=1800     # Seconds before creating a new session (default: 30 min)
```

### Identity Templates (Optional)

- `IDENTITY.md` — Personality and principles (equivalent to a system prompt addition)
- `PREFERENCES.md` — Output style and communication preferences

If these files exist in your project root, `session-start.sh` loads them at startup (~200 tokens each).

---

## How the Safety Net Works

Claude should save `.mci` entries using the `[PC]` marker. But sometimes it forgets, or compact fires unexpectedly. The system has a 3-tier fallback:

**Tier 1 — Claude saved .mci (best case)**
Claude typed `[PC]` and wrote a proper M/C/I triplet. Nothing else needed.

**Tier 2 — Assemble from marker files**
If `.mci` is empty, `pre-compact.sh` reads the latest `[!]`, `[*]`, `[>]` entries from the marker files and assembles an `.mci` entry automatically.

**Tier 3 — Emergency extraction from JSONL**
If marker files are also empty, the hook scrapes the JSONL conversation log for any marker lines, recent messages, tool usage, and files touched. It builds an emergency `.mci` with whatever context it can find.

**Result:** Even in the worst case, the next session loads *something* rather than starting completely blank.

---

## FAQ

**Does this work with Claude Code subagents (Task tool)?**
The hooks run on the main session. Subagents don't trigger hooks directly, but the main session's markers capture the overall flow.

**How much context does this use?**
SessionStart injects ~500-800 tokens (identity + .mci + rules). This is a small fraction of the ~200K token context window.

**What if hooks are slow?**
`prompt-capture.sh` has a 5-second timeout and is optimized to run in <2 seconds. It only reads the last 50 lines of the JSONL for speed.

**Can I use this with an existing CLAUDE.md?**
Yes. The installer can append M/C/I rules to your existing `CLAUDE.md` instead of replacing it.

**What about `.claude-memory/` in git?**
It's in `.gitignore` by default. Session data is personal and shouldn't be committed. The hooks and CLAUDE.md are the shareable parts.

**Does this work on macOS?**
Yes. The hooks detect GNU vs BSD `stat` for cross-platform compatibility.

---

## How It Was Built

This system was developed and battle-tested over 100+ sessions spanning 2 months. Key lessons learned:

- **Markers must be commands, not formatting.** Early versions treated markers as decorative — entries were never saved. Enforcement changed everything.
- **Multi-layer fallbacks are essential.** Claude forgets. Compacts fire unexpectedly. Every layer catches what the previous one missed.
- **Keep startup lightweight.** Loading too much context at session start wastes the context window. The "drawer model" — load on demand — maximizes useful space.
- **The .mci file is the lifeline.** It's the single most important file in the system. Everything else is backup.

---

## License

MIT

---

## Contributing

Issues and pull requests welcome at [github.com/hlsitechio/claude-memory](https://github.com/hlsitechio/claude-memory).
