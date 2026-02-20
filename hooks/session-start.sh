#!/bin/bash
# ============================================================================
# claude-memory v2 SESSION START — state.md based memory system
# Creates/resumes sessions, creates state.md template, loads .mci, injects rules
# ============================================================================

MEMORY_BASE="${CLAUDE_PROJECT_DIR:-.}/.claude-memory"
SESSION_DATE=$(date +%Y-%m-%d)
SESSION_TIME=$(date +%H:%M)
SESSION_DIR="$MEMORY_BASE/sessions/$SESSION_DATE"
RESUME_TIMEOUT=1800

# Cross-platform stat
file_mod_time() {
    if stat --version &>/dev/null 2>&1; then
        stat -c %Y "$1" 2>/dev/null || echo 0
    else
        stat -f %m "$1" 2>/dev/null || echo 0
    fi
}

# ============================================================================
# SESSION MANAGEMENT
# ============================================================================
mkdir -p "$SESSION_DIR"
LAST_SESSION=$(ls -d "$SESSION_DIR"/session-* 2>/dev/null | sort -V | tail -1)

create_session_files() {
    local P="$1" N="$2"
    mkdir -p "$P"
    echo "# Session $N - Started $SESSION_TIME" > "$P/memory.md"
    echo "---" >> "$P/memory.md"
    # state.md — the living state file (v2)
    cat > "$P/state.md" << 'STATEEOF'
# Session State
> Last updated: --:--

## Goal
(Set your mission here. What are you working on and why?)

## Progress
- [ ] Waiting for direction

## Findings
(none yet)
STATEEOF
    # Legacy marker files (backward compat)
    echo "# Facts - Session $N" > "$P/facts.md"
    echo "# Context - Session $N" > "$P/context.md"
    echo "# Intent - Session $N" > "$P/intent.md"
}

if [ -n "$LAST_SESSION" ] && [ -f "$LAST_SESSION/memory.md" ]; then
    LAST_MOD=$(file_mod_time "$LAST_SESSION/memory.md")
    NOW=$(date +%s)
    DIFF=$((NOW - LAST_MOD))
    if [ $DIFF -lt $RESUME_TIMEOUT ]; then
        SESSION_PATH="$LAST_SESSION"
        SESSION_NUM=$(basename "$LAST_SESSION" | sed 's/session-//')
        SESSION_STATUS="RESUMED"
        # Ensure state.md exists on resume
        if [ ! -f "$SESSION_PATH/state.md" ]; then
            cat > "$SESSION_PATH/state.md" << 'STATEEOF'
# Session State
> Last updated: --:--

## Goal
(Resumed session — update with current mission)

## Progress
- [ ] (update with current tasks)

## Findings
(update with any findings)
STATEEOF
        fi
    else
        EXISTING=$(ls -d "$SESSION_DIR"/session-* 2>/dev/null | wc -l)
        SESSION_NUM=$((EXISTING + 1))
        SESSION_PATH="$SESSION_DIR/session-$SESSION_NUM"
        create_session_files "$SESSION_PATH" "$SESSION_NUM"
        SESSION_STATUS="NEW"
    fi
else
    SESSION_NUM=1
    SESSION_PATH="$SESSION_DIR/session-$SESSION_NUM"
    create_session_files "$SESSION_PATH" "$SESSION_NUM"
    SESSION_STATUS="NEW"
fi

echo "$SESSION_PATH" > "$MEMORY_BASE/current-session"

# ============================================================================
# POST-COMPACT DETECTION
# ============================================================================
COMPACT_MARKER="$MEMORY_BASE/compact-pending"
IS_POST_COMPACT="false"
COMPACT_INFO=""

if [ -f "$COMPACT_MARKER" ]; then
    IS_POST_COMPACT="true"
    COMPACT_INFO=$(cat "$COMPACT_MARKER" 2>/dev/null)
    rm -f "$COMPACT_MARKER"
fi

# ============================================================================
# LOAD IDENTITY FILES
# ============================================================================
LOADED_CONTEXT=""
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-.}"

if [ -f "$PROJECT_ROOT/IDENTITY.md" ]; then
    LOADED_CONTEXT="${LOADED_CONTEXT}

=== Identity ===
$(head -c 1000 "$PROJECT_ROOT/IDENTITY.md" 2>/dev/null)"
fi

if [ -f "$PROJECT_ROOT/PREFERENCES.md" ]; then
    LOADED_CONTEXT="${LOADED_CONTEXT}

=== Preferences ===
$(head -c 800 "$PROJECT_ROOT/PREFERENCES.md" 2>/dev/null)"
fi

# ============================================================================
# LOAD .MCI (cascade: current → previous today → yesterday)
# ============================================================================
MCI_LOADED="false"

if [ -f "$SESSION_PATH/memory.mci" ] && [ -s "$SESSION_PATH/memory.mci" ]; then
    MCI_LOADED="true"
    LOADED_CONTEXT="${LOADED_CONTEXT}

=== Session .mci (${SESSION_PATH}/memory.mci) ===
$(cat "$SESSION_PATH/memory.mci" 2>/dev/null)"
fi

if [ "$MCI_LOADED" = "false" ]; then
    for DIR in $(ls -dr "$SESSION_DIR"/session-* 2>/dev/null); do
        if [ -f "$DIR/memory.mci" ] && [ -s "$DIR/memory.mci" ]; then
            MCI_LOADED="true"
            LOADED_CONTEXT="${LOADED_CONTEXT}

=== Previous Session .mci (${DIR}/memory.mci) ===
$(cat "$DIR/memory.mci" 2>/dev/null)"
            break
        fi
    done
fi

if [ "$MCI_LOADED" = "false" ]; then
    if date --version &>/dev/null 2>&1; then
        YESTERDAY=$(date -d "yesterday" +%Y-%m-%d)
    else
        YESTERDAY=$(date -v-1d +%Y-%m-%d)
    fi
    YESTERDAY_LAST=$(ls -d "$MEMORY_BASE/sessions/$YESTERDAY"/session-* 2>/dev/null | sort -V | tail -1)
    if [ -n "$YESTERDAY_LAST" ] && [ -f "$YESTERDAY_LAST/memory.mci" ]; then
        MCI_LOADED="true"
        LOADED_CONTEXT="${LOADED_CONTEXT}

=== Yesterday's .mci (${YESTERDAY_LAST}/memory.mci) ===
$(cat "$YESTERDAY_LAST/memory.mci" 2>/dev/null)"
    fi
fi

# state.md status
STATE_STATUS="EMPTY"
if [ -f "$SESSION_PATH/state.md" ]; then
    STATE_SIZE=$(wc -c < "$SESSION_PATH/state.md" 2>/dev/null || echo 0)
    [ "$STATE_SIZE" -gt 200 ] && STATE_STATUS="ACTIVE ($STATE_SIZE bytes)" || STATE_STATUS="TEMPLATE"
fi

# ============================================================================
# claude-memory v2 RULES
# ============================================================================

MCI_RULES="
=== MEMORY SYSTEM v2 — state.md ===

## state.md = Your External Brain
Path: $SESSION_PATH/state.md
Status: $STATE_STATUS

state.md is a LIVING document with 3 sections: Goal, Progress, Findings.
It survives compacts because it lives on disk. After compact, READ it for full recovery.

## How to Use
1. **Update Goal** when mission changes (use Edit tool)
2. **Update Progress** as you work — check off tasks, add new ones (use Edit tool)
3. **Update Findings** when you discover important data (use Edit tool)
4. **Append to memory.md** for session log entries ([i] marker)
5. **Every 3-5 tool calls** — quick state.md update to stay current

## Markers (display formatting + state.md triggers)
| Marker | Meaning | state.md Action |
|--------|---------|----------------|
| [+] | Success | (display only) |
| [-] | Failed | (display only) |
| [!] | Critical find | → Edit Findings section |
| [>] | Next step | → Edit Progress section |
| [*] | Context shift | → Edit Goal section |
| [i] | Info note | → Append to memory.md |

Markers are OUTPUT FORMATTING. state.md is the REAL memory. Keep it current.

## Post-Compact Recovery
1. Read $SESSION_PATH/state.md — your full state is there
2. Check Progress — see what's done, what's next
3. Resume from first unchecked item
4. DO NOT ask user what you were doing — state.md tells you

## .mci File
Path: $SESSION_PATH/memory.mci
Auto-generated by hooks as safety net. Pre-compact snapshots state.md → .mci."

LOADED_CONTEXT="${LOADED_CONTEXT}
${MCI_RULES}"

# ============================================================================
# BUILD OUTPUT
# ============================================================================

COMPACT_ALERT=""
if [ "$IS_POST_COMPACT" = "true" ]; then
    COMPACT_ALERT="
=== POST-COMPACT RECOVERY ===
Auto-compact fired. Your state.md is intact on disk.
ACTION: Read $SESSION_PATH/state.md for full recovery. Resume from Progress checklist.
Do NOT ask what you were doing. state.md TELLS you.
Compact info: $COMPACT_INFO"
fi

CONTEXT="# claude-memory v2 Session - $(date '+%Y-%m-%d %I:%M%p')

=== STATUS ===
[+] SESSION: #$SESSION_NUM ($SESSION_STATUS)
Path: $SESSION_PATH
state.md: $STATE_STATUS
MCI: $([ "$MCI_LOADED" = "true" ] && echo "LOADED" || echo "EMPTY")
Post-Compact: $([ "$IS_POST_COMPACT" = "true" ] && echo "YES — READ state.md NOW" || echo "No")
$COMPACT_ALERT
$LOADED_CONTEXT"

CONTEXT_ESCAPED=$(echo "$CONTEXT" | jq -Rs .)

cat << EOF
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": $CONTEXT_ESCAPED
  }
}
EOF

exit 0
