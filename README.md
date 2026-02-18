<h1 align="center">🧠 claude-memory</h1>

<p align="center">
  <img src="banner.png" alt="claude-memory — Persistent M/C/I Memory for Claude Code" width="100%">
</p>

<p align="center">
  <strong>Persistent memory for Claude Code sessions using the M/C/I system.</strong><br>
  <em>Survives compacts, crashes, restarts, and even weekends.</em>
</p>

<p align="center">
  <a href="#-quick-start"><img src="https://img.shields.io/badge/setup-one_command-brightgreen?style=for-the-badge" alt="One Command Setup"></a>
  <a href="#-quick-start"><img src="https://img.shields.io/badge/plugin-native_install-blueviolet?style=for-the-badge" alt="Plugin Install"></a>
  <a href="#-how-it-works"><img src="https://img.shields.io/badge/hooks-4_automated-blue?style=for-the-badge" alt="4 Hooks"></a>
  <a href="#%EF%B8%8F-safety-net--recovery"><img src="https://img.shields.io/badge/fallback-3_tier-orange?style=for-the-badge" alt="3-Tier Fallback"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-purple?style=for-the-badge" alt="MIT License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Claude_Code-v2.1+-black?style=flat-square&logo=anthropic&logoColor=white" alt="Claude Code">
  <img src="https://img.shields.io/badge/platform-Linux_%7C_macOS_%7C_Windows-lightgrey?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/badge/hooks-Node.js_(cross--platform)-339933?style=flat-square&logo=node.js&logoColor=white" alt="Node.js">
  <img src="https://img.shields.io/badge/battle_tested-100+_sessions-red?style=flat-square" alt="Battle Tested">
</p>

---

> 🚨 **The problem:** Claude Code starts every session blank. When the context window fills up, auto-compact fires and your conversation history is compressed. Terminal crash? **Complete amnesia.**
>
> ✅ **The fix:** `claude-memory` — a hook-based system that automatically saves and restores your working state across sessions, compacts, crashes, and restarts.

---

## 🔄 How It Works

### 😵 The Problem

```
Session 1: You build something complex over 2 hours
            ↓ context fills up
            ↓ auto-compact fires 💥
Session 1 (continued): Claude forgot everything 🤷
            ↓ terminal crashes
Session 2: Total amnesia. "What were we working on?" 😶
```

### 💡 The Solution: M/C/I (Memory / Context / Intent)

Every piece of knowledge is stored as an **atomic triplet**:

| Component | What it captures |
|-----------|-----------------|
| 📝 **Memory** | What happened — facts, data, discoveries |
| 🔗 **Context** | Why it matters — meaning, relationships, significance |
| 🎯 **Intent** | Where we're going — next steps, direction, goals |

### ⚡ Four hooks automate the lifecycle:

```
┌─────────────────────────────────────────────────────────┐
│ 🟢 SessionStart                                         │
│    → Creates/resumes session directory                   │
│    → Loads last .mci (cascades up to 7 days back)        │
│    → Detects crashes & recovers automatically            │
│    → First-run: copies templates, onboards Claude        │
├─────────────────────────────────────────────────────────┤
│ 🔵 UserPromptSubmit (every prompt)                       │
│    → Captures markers from Claude's last response        │
│    → Auto-checkpoints every ~10 prompts (crash safety)   │
│    → Estimates context usage & warns before compact ⚠️   │
├─────────────────────────────────────────────────────────┤
│ 🟠 PreCompact (before auto-compact)                      │
│    → 3-tier fallback: .mci → markers → JSONL emergency  │
│    → Creates conversation backup 💾                      │
├─────────────────────────────────────────────────────────┤
│ 🔴 Stop (session end)                                    │
│    → Ensures valid .mci exists for next session          │
│    → Generates session summary 📊                        │
└─────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### 🔌 Option A: Plugin Install (Recommended)

The fastest way — native Claude Code plugin with automatic hook registration:

```bash
# Add the marketplace (one-time)
/plugin marketplace add hlsitechio/claude-memory

# Install the plugin
/plugin install claude-memory@hlsitechio
```

That's it! Restart Claude Code and memory is active. On first run, the plugin:

1. 📂 Creates `.claude-memory/sessions/` directory
2. 📄 Copies `IDENTITY.md` and `PREFERENCES.md` templates to your project
3. 🧠 Injects M/C/I rules so Claude understands the system immediately
4. 💬 Guides Claude through a first-run welcome message

You also get **3 slash commands**:

| Command | What it does |
|---------|-------------|
| 🔖 `/claude-memory:save` | Manual checkpoint — save state to `.mci` right now |
| 🔁 `/claude-memory:recall` | Load and display last saved M/C/I state |
| 📊 `/claude-memory:status` | Dashboard — marker counts, .mci health, session info |

**Updating:**
```bash
/plugin marketplace update hlsitechio
/plugin update claude-memory@hlsitechio
```

### 📦 Option B: Manual Install (git clone)

For full control or if you want to customize the hooks:

```bash
git clone https://github.com/hlsitechio/claude-memory.git
cd claude-memory
./install.sh /path/to/your/project
```

The installer will:
1. 📂 Copy 4 hook scripts to your project's `.claude/hooks/`
2. 📄 Install `CLAUDE.md` with M/C/I rules
3. ⚙️ Generate `.claude/settings.local.json` with hook configuration
4. 🗂️ Create the `.claude-memory/sessions/` directory
5. 🎭 Optionally install identity templates (`IDENTITY.md`, `PREFERENCES.md`)

### 📋 Prerequisites

| Requirement | Plugin | Manual |
|------------|--------|--------|
| 🤖 Claude Code | v2.1+ | v2.1+ |
| 📦 Node.js | ✅ (bundled with Claude Code) | Not needed |
| 🔧 jq + bash | Not needed | Required |

---

## 🛡️ Safety Net & Recovery

### 💥 Crash Recovery

If the terminal crashes, gets killed, or is closed abruptly — the **Stop hook never fires**. claude-memory handles this:

1. **On next startup**, SessionStart detects the crash (no end marker in previous session)
2. **Loads the .mci** from the crashed session (if it exists)
3. **Loads marker files** (facts.md, context.md, intent.md) for richer context
4. **Injects a CRASH RECOVERY block** telling Claude exactly what happened
5. Claude resumes where you left off — **no questions asked**

### ⏱️ Auto-Checkpoint (Crash Insurance)

Every **~10 prompts**, the UserPromptSubmit hook auto-saves a checkpoint to `.mci`. This means even if Claude never manually wrote `[PC]` and the terminal crashes, there's recent state saved.

### 📅 7-Day .mci Cascade

When loading memory, SessionStart searches:

```
current session .mci
  → previous session (timed out)
    → earlier sessions today
      → yesterday
        → 2 days ago → ... → up to 7 days back
```

Come back after a long weekend? Your context is still there.

### 🥇🥈🥉 3-Tier Fallback (PreCompact)

| Tier | Source | When |
|------|--------|------|
| 🥇 **Best** | Claude saved `.mci` via `[PC]` | Claude was diligent |
| 🥈 **Good** | Assembled from marker files (`[!]` `[*]` `[>]`) | Claude used markers but forgot `[PC]` |
| 🥉 **Emergency** | Extracted from JSONL transcript | Nothing else available |

**Result:** Even in the worst case, the next session loads *something* rather than starting blank.

---

## 🏷️ Markers

Markers are how Claude saves information during a session. When Claude types a marker in its response, it **must** also write it to the corresponding file.

### 💾 Save Markers (write to file on use)

| Marker | File | Purpose |
|--------|------|---------|
| 🔴 `[!]` | `facts.md` | Critical discoveries, key findings |
| 🟡 `[*]` | `context.md` | Why something matters, significance |
| 🟢 `[>]` | `intent.md` | Next steps, direction, goals |
| 🔵 `[i]` | `memory.md` | Observations, environment info |

### 🔄 Lifecycle Markers

| Marker | Action |
|--------|--------|
| 💾 `[PC]` | Pre-compact save — writes M/C/I triplet to `memory.mci` |
| 🔁 `[AC]` | Post-compact recovery — reads `.mci` to restore state |

### 🎨 Display-Only Markers (no file write)

| Marker | Meaning |
|--------|---------|
| ✅ `[+]` | Success / found |
| ❌ `[-]` | Failed / not found |

### 📌 Example

When Claude writes this in a response:
```
[!] Found that the API rate limit can be bypassed by rotating User-Agent headers
```

It must also run:
```bash
echo '## 14:30 - Found that the API rate limit can be bypassed by rotating User-Agent headers' >> SESSION_PATH/facts.md
```

> 💡 The `prompt-capture` hook also captures markers as a backup, but Claude should save them directly for reliability.

---

## 📦 The .mci File

The `.mci` file is the **compact recovery lifeline** — the single most important file in the system:

```
--- Session 3 ---
Memory: Built the user filtering API. Added 3 columns to users table. Found auth bypass.
Context: Preparing for v2.1 release. Auth bypass is a security issue blocking release.
Intent: Fix auth middleware, write tests, then merge the filtering PR.
```

> 🛡️ When auto-compact fires, the `.mci` file **survives** because it's on disk, not in the context window. The next `SessionStart` hook loads it back, and Claude picks up exactly where it left off.

---

## 📁 Session Structure

Sessions are organized by date:

```
.claude-memory/
└── 📂 sessions/
    └── 📂 2026-02-18/
        ├── 📂 session-1/
        │   ├── 📄 facts.md           ← 🔴 [!] entries
        │   ├── 📄 context.md         ← 🟡 [*] entries
        │   ├── 📄 intent.md          ← 🟢 [>] entries
        │   ├── 📄 memory.md          ← 🔵 [i] entries + session log
        │   ├── 🛡️ memory.mci         ← compact recovery lifeline
        │   ├── 💾 compact-12:17:29.md ← conversation backup
        │   └── 📊 session-summary.md ← tool stats, files modified
        └── 📂 session-2/
            └── ...
```

| Feature | Detail |
|---------|--------|
| ♻️ Auto-resume | Sessions active within last 4 hours are resumed |
| 🆕 New session | Created automatically after 4-hour gap |
| 🔍 MCI cascade | Searches: current → previous today → up to 7 days back |
| 💥 Crash detection | Detects if previous session ended without Stop hook |
| ⚡ Auto-checkpoint | Saves .mci every ~10 prompts as crash insurance |
| 🎉 First-run setup | Copies templates, onboards Claude on first install |

---

## ⚙️ Configuration

### 🔌 Plugin Hooks (automatic)

Plugin hooks are configured automatically via `hooks.json`. No manual setup needed.

<details>
<summary>📋 Click to see plugin hooks.json</summary>

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|clear|compact",
        "hooks": [{ "type": "command", "command": "node \"${CLAUDE_PLUGIN_ROOT}/scripts/session-start.js\"", "timeout": 30 }]
      }
    ],
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [{ "type": "command", "command": "node \"${CLAUDE_PLUGIN_ROOT}/scripts/prompt-capture.js\"", "timeout": 5 }]
      }
    ],
    "PreCompact": [
      {
        "matcher": "",
        "hooks": [{ "type": "command", "command": "node \"${CLAUDE_PLUGIN_ROOT}/scripts/pre-compact.js\"", "timeout": 30 }]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [{ "type": "command", "command": "node \"${CLAUDE_PLUGIN_ROOT}/scripts/session-stop.js\"", "timeout": 30 }]
      }
    ]
  }
}
```

</details>

### 🪝 Manual Hook Settings

For git-clone installs, the installer generates `.claude/settings.local.json`:

<details>
<summary>📋 Click to expand manual hook configuration</summary>

```json
{
  "hooks": {
    "SessionStart": [
      { "matcher": "", "hooks": [{ "type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR/.claude/hooks/session-start.sh\"" }] }
    ],
    "UserPromptSubmit": [
      { "matcher": "", "hooks": [{ "type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR/.claude/hooks/prompt-capture.sh\"", "timeout": 5 }] }
    ],
    "PreCompact": [
      { "matcher": "", "hooks": [{ "type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR/.claude/hooks/pre-compact.sh\"" }] }
    ],
    "Stop": [
      { "matcher": "", "hooks": [{ "type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR/.claude/hooks/session-stop.sh\"", "timeout": 30 }] }
    ]
  }
}
```

</details>

### 🎛️ Tunable Constants

**Plugin** (in `plugin/scripts/*.js`):

| Constant | Default | Purpose |
|----------|---------|---------|
| `RESUME_TIMEOUT` | `14400` (4 hours) | Seconds before creating a new session |
| `MCI_LOOKBACK_DAYS` | `7` | Days to search back for .mci recovery |
| `AUTO_CHECKPOINT_INTERVAL` | `10` | Prompts between auto-checkpoints |
| `CONTEXT_LIMIT` | `1000000` | Estimated JSONL bytes at compact |
| `WARN_BYTES` | `700000` | ~70% — gentle checkpoint reminder |
| `CRITICAL_BYTES` | `850000` | ~85% — strong save warning |
| `EMERGENCY_BYTES` | `950000` | ~95% — save NOW |

### 🎭 Identity Templates (Optional)

| Template | Purpose |
|----------|---------|
| 📝 `IDENTITY.md` | Personality and principles (system prompt addition) |
| ⚡ `PREFERENCES.md` | Output style and communication preferences |

> On plugin first-run, templates are automatically copied to your project root. Edit them to customize Claude's personality and communication style.

---

## ❓ FAQ

<details>
<summary>🤖 Does this work with Claude Code subagents (Task tool)?</summary>

The hooks run on the main session. Subagents don't trigger hooks directly, but the main session's markers capture the overall flow.
</details>

<details>
<summary>📊 How much context does this use?</summary>

SessionStart injects ~500-800 tokens (identity + .mci + rules). This is a small fraction of the ~200K token context window.
</details>

<details>
<summary>⏱️ What if hooks are slow?</summary>

`prompt-capture.js` has a 5-second timeout and runs in <2 seconds. It only reads the last 50 lines of the JSONL for speed.
</details>

<details>
<summary>💥 What if my terminal crashes?</summary>

On next startup, SessionStart detects the crash (missing Stop marker), loads the last .mci + marker files, and injects a CRASH RECOVERY block. Auto-checkpoints every ~10 prompts ensure there's always recent state saved.
</details>

<details>
<summary>📅 What if I come back after the weekend?</summary>

The .mci cascade searches up to 7 days back. Your context from Friday is still there on Monday.
</details>

<details>
<summary>🪟 Does this work on Windows?</summary>

Yes! Plugin hooks use Node.js (bundled with Claude Code) for full cross-platform support. No bash required.
</details>

<details>
<summary>📄 Can I use this with an existing CLAUDE.md?</summary>

Yes! The plugin's CLAUDE.md is loaded alongside your existing one. For manual install, the installer can append M/C/I rules to your existing `CLAUDE.md`.
</details>

<details>
<summary>🔒 What about `.claude-memory/` in git?</summary>

It's in `.gitignore` by default. Session data is personal and shouldn't be committed.
</details>

---

## 🏗️ How It Was Built

> *Battle-tested over 100+ sessions spanning 2 months.*

| Lesson | Detail |
|--------|--------|
| 🎯 **Markers = commands** | Early versions treated markers as decorative — entries were never saved. Enforcement changed everything. |
| 🛡️ **Multi-layer fallbacks** | Claude forgets. Compacts fire unexpectedly. Terminals crash. Every layer catches what the previous one missed. |
| 🪶 **Lightweight startup** | Loading too much context wastes the context window. The "drawer model" — load on demand — maximizes useful space. |
| 💎 **The .mci is sacred** | It's the single most important file in the system. Everything else is backup. |
| 🔄 **Node.js over bash** | Bash hooks failed on Windows and had variable expansion issues. Node.js is cross-platform and bundled with Claude Code. |
| ⚡ **Auto-checkpoint** | Relying on Claude to save `[PC]` was unreliable. Auto-checkpointing every ~10 prompts is the crash safety net. |

---

## 📜 License

MIT — see [LICENSE](LICENSE)

---

## 🤝 Contributing

Issues and pull requests welcome!

<p align="center">
  <a href="https://github.com/hlsitechio/claude-memory/issues">🐛 Report Bug</a>
  &nbsp;&nbsp;•&nbsp;&nbsp;
  <a href="https://github.com/hlsitechio/claude-memory/issues">💡 Request Feature</a>
  &nbsp;&nbsp;•&nbsp;&nbsp;
  <a href="https://github.com/hlsitechio/claude-memory">⭐ Star the Repo</a>
</p>

<p align="center">
  <sub>Built with 🧠 by <a href="https://github.com/hlsitechio">hlsitechio</a> — giving Claude a memory it deserves.</sub>
</p>
