#!/bin/bash
# ============================================================================
# SESSION START - M/C/I Memory System
# Creates/resumes sessions, loads last .mci state, injects M/C/I rules
# ============================================================================

# === CONFIGURATION ===
MEMORY_BASE="${CLAUDE_PROJECT_DIR:-.}/.claude-memory"
SESSION_DATE=$(date +%Y-%m-%d)
SESSION_TIME=$(date +%H:%M)
SESSION_DIR="$MEMORY_BASE/sessions/$SESSION_DATE"
RESUME_TIMEOUT=1800  # 30 minutes

# Cross-platform stat (GNU vs BSD)
file_mod_time() {
    if stat --version &>/dev/null 2>&1; then
        stat -c %Y "$1" 2>/dev/null || echo 0
    else
        stat -f %m "$1" 2>/dev/null || echo 0
    fi
}

# ============================================================================
# HOOK HEALTH CHECK
# ============================================================================
HOOKS_OK="true"
HOOKS_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude/hooks"
for SCRIPT in session-start.sh prompt-capture.sh pre-compact.sh session-stop.sh; do
    if [ ! -f "$HOOKS_DIR/$SCRIPT" ] || [ ! -x "$HOOKS_DIR/$SCRIPT" ]; then
        HOOKS_OK="false"
        break
    fi
done

# ============================================================================
# SESSION MANAGEMENT
# ============================================================================
mkdir -p "$SESSION_DIR"
LAST_SESSION=$(ls -d "$SESSION_DIR"/session-* 2>/dev/null | sort -V | tail -1)

create_session_files() {
    local PATH_="$1" NUM="$2"
    mkdir -p "$PATH_"
    echo "# Session $NUM - Started $SESSION_TIME" > "$PATH_/memory.md"
    echo "---" >> "$PATH_/memory.md"
    echo "# Facts - Session $NUM" > "$PATH_/facts.md"
    echo "# Context - Session $NUM" > "$PATH_/context.md"
    echo "# Intent - Session $NUM" > "$PATH_/intent.md"
}

if [ -n "$LAST_SESSION" ] && [ -f "$LAST_SESSION/memory.md" ]; then
    LAST_MOD=$(file_mod_time "$LAST_SESSION/memory.md")
    NOW=$(date +%s)
    DIFF=$((NOW - LAST_MOD))

    if [ $DIFF -lt $RESUME_TIMEOUT ]; then
        SESSION_PATH="$LAST_SESSION"
        SESSION_NUM=$(basename "$LAST_SESSION" | sed 's/session-//')
        SESSION_STATUS="RESUMED"
        # Ensure marker files exist on resume
        [ ! -f "$SESSION_PATH/facts.md" ] && echo "# Facts - Session $SESSION_NUM" > "$SESSION_PATH/facts.md"
        [ ! -f "$SESSION_PATH/context.md" ] && echo "# Context - Session $SESSION_NUM" > "$SESSION_PATH/context.md"
        [ ! -f "$SESSION_PATH/intent.md" ] && echo "# Intent - Session $SESSION_NUM" > "$SESSION_PATH/intent.md"
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

# Write current session path for other hooks
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
# LOAD IDENTITY FILES (optional)
# ============================================================================
LOADED_CONTEXT=""
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-.}"

if [ -f "$PROJECT_ROOT/IDENTITY.md" ]; then
    IDENTITY=$(head -c 1000 "$PROJECT_ROOT/IDENTITY.md" 2>/dev/null)
    LOADED_CONTEXT="${LOADED_CONTEXT}

=== Identity ===
${IDENTITY}"
fi

if [ -f "$PROJECT_ROOT/PREFERENCES.md" ]; then
    PREFS=$(head -c 800 "$PROJECT_ROOT/PREFERENCES.md" 2>/dev/null)
    LOADED_CONTEXT="${LOADED_CONTEXT}

=== Preferences ===
${PREFS}"
fi

# ============================================================================
# LOAD .MCI (cascade: current → previous today → yesterday)
# ============================================================================
MCI_LOADED="false"

# Try current session
if [ -f "$SESSION_PATH/memory.mci" ] && [ -s "$SESSION_PATH/memory.mci" ]; then
    MCI_CONTENT=$(cat "$SESSION_PATH/memory.mci" 2>/dev/null)
    if [ -n "$MCI_CONTENT" ]; then
        MCI_LOADED="true"
        LOADED_CONTEXT="${LOADED_CONTEXT}

=== Session M/C/I (${SESSION_PATH}/memory.mci) ===
${MCI_CONTENT}"
    fi
fi

# Fallback: previous sessions today
if [ "$MCI_LOADED" = "false" ]; then
    for DIR in $(ls -dr "$SESSION_DIR"/session-* 2>/dev/null); do
        if [ -f "$DIR/memory.mci" ] && [ -s "$DIR/memory.mci" ]; then
            MCI_CONTENT=$(cat "$DIR/memory.mci" 2>/dev/null)
            if [ -n "$MCI_CONTENT" ]; then
                MCI_LOADED="true"
                LOADED_CONTEXT="${LOADED_CONTEXT}

=== Previous Session M/C/I (${DIR}/memory.mci) ===
${MCI_CONTENT}"
                break
            fi
        fi
    done
fi

# Fallback: yesterday
if [ "$MCI_LOADED" = "false" ]; then
    if date --version &>/dev/null 2>&1; then
        YESTERDAY=$(date -d "yesterday" +%Y-%m-%d)
    else
        YESTERDAY=$(date -v-1d +%Y-%m-%d)
    fi
    YESTERDAY_DIR="$MEMORY_BASE/sessions/$YESTERDAY"
    YESTERDAY_LAST=$(ls -d "$YESTERDAY_DIR"/session-* 2>/dev/null | sort -V | tail -1)
    if [ -n "$YESTERDAY_LAST" ] && [ -f "$YESTERDAY_LAST/memory.mci" ]; then
        MCI_CONTENT=$(cat "$YESTERDAY_LAST/memory.mci" 2>/dev/null)
        if [ -n "$MCI_CONTENT" ]; then
            MCI_LOADED="true"
            LOADED_CONTEXT="${LOADED_CONTEXT}

=== Yesterday's M/C/I (${YESTERDAY_LAST}/memory.mci) ===
${MCI_CONTENT}"
        fi
    fi
fi

# ============================================================================
# M/C/I RULES (always injected)
# ============================================================================

MCI_RULES="
=== M/C/I MEMORY RULES ===

Markers are COMMANDS, not formatting. Type a marker = MUST write to its file in the SAME response.

| Marker | File | Action |
|--------|------|--------|
| [!] | facts.md | echo '## HH:MM - <fact>' >> $SESSION_PATH/facts.md |
| [*] | context.md | echo '## HH:MM - <context>' >> $SESSION_PATH/context.md |
| [>] | intent.md | echo '## HH:MM - <intent>' >> $SESSION_PATH/intent.md |
| [i] | memory.md | echo '## HH:MM - <info>' >> $SESSION_PATH/memory.md |
| [PC] | memory.mci | Write Memory/Context/Intent triplet to $SESSION_PATH/memory.mci |
| [AC] | memory.mci | READ .mci, recover intent (post-compact recovery) |
| [+] | (none) | Display only: success |
| [-] | (none) | Display only: failed |

Rule: TYPE marker -> WRITE to file -> SAME RESPONSE -> CONTINUE.

.mci format:
--- <label> ---
Memory: <what happened>
Context: <why it matters>
Intent: <where we're going>

Auto-save: When the hook warns about context -> write [PC] immediately. The .mci is your lifeline."

LOADED_CONTEXT="${LOADED_CONTEXT}
${MCI_RULES}"

# ============================================================================
# BUILD OUTPUT
# ============================================================================

COMPACT_ALERT=""
if [ "$IS_POST_COMPACT" = "true" ]; then
    COMPACT_ALERT="
=== POST-COMPACT RECOVERY ===
Auto-compact fired. Your .mci file is your lifeline.
Compact info: $COMPACT_INFO
ACTION: Read the M/C/I entries below. Recover your Intent. Continue work.
Do NOT ask what you were doing. The .mci TELLS you."
fi

CONTEXT="# M/C/I Session - $(date '+%Y-%m-%d %I:%M%p')

=== STATUS ===
[$([ "$HOOKS_OK" = "true" ] && echo "+" || echo "!")] HOOKS: $([ "$HOOKS_OK" = "true" ] && echo "All 4 scripts OK" || echo "ISSUES detected")
[+] SESSION: #$SESSION_NUM ($SESSION_STATUS)
Path: $SESSION_PATH
MCI: $([ "$MCI_LOADED" = "true" ] && echo "LOADED" || echo "EMPTY - fresh session")
Post-Compact: $([ "$IS_POST_COMPACT" = "true" ] && echo "YES - recovering" || echo "No")
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
