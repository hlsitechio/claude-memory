#!/bin/bash
# ============================================================================
# claude-memory v2 PROMPT CAPTURE — state.md health + context estimation
# Fires on every UserPromptSubmit — must be FAST (<2s)
# Also captures legacy markers from assistant responses (backward compat)
# ============================================================================

MEMORY_BASE="${CLAUDE_PROJECT_DIR:-.}/.claude-memory"
TIMESTAMP=$(date +%H:%M)

# Context estimation thresholds (calibrated for ~200K token context window)
CONTEXT_LIMIT=1000000   # ~167K tokens in JSONL bytes
WARN_BYTES=700000       # ~70% - gentle checkpoint
CRITICAL_BYTES=850000   # ~85% - strong warning
EMERGENCY_BYTES=950000  # ~95% - save NOW

# Read hook input
HOOK_INPUT=$(timeout 1 cat 2>/dev/null || echo "{}")
TRANSCRIPT=$(echo "$HOOK_INPUT" | jq -r '.hookInput.transcriptPath // .transcriptPath // empty' 2>/dev/null)

# Find current session
SESSION_PATH=""
if [ -f "$MEMORY_BASE/current-session" ]; then
    SESSION_PATH=$(cat "$MEMORY_BASE/current-session" 2>/dev/null)
fi
if [ -z "$SESSION_PATH" ] || [ ! -d "$SESSION_PATH" ]; then
    SESSION_DATE=$(date +%Y-%m-%d)
    SESSION_PATH=$(ls -d "$MEMORY_BASE/sessions/$SESSION_DATE"/session-* 2>/dev/null | sort -V | tail -1)
fi
[ -z "$SESSION_PATH" ] && { echo '{"suppressOutput": true}'; exit 0; }

STATE_FILE="$SESSION_PATH/state.md"

# ============================================================================
# STEP 1: state.md HEALTH CHECK (v2 — primary concern)
# ============================================================================

STATE_WARNING=""
if [ ! -f "$STATE_FILE" ]; then
    STATE_WARNING="[!] state.md MISSING at $STATE_FILE — Create it with Goal/Progress/Findings sections using Edit tool."
else
    STATE_SIZE=$(wc -c < "$STATE_FILE" 2>/dev/null || echo 0)
    if [ "$STATE_SIZE" -lt 200 ]; then
        STATE_WARNING="[i] state.md is still template (~${STATE_SIZE}b). Update Goal/Progress/Findings with your current work using Edit tool."
    fi
fi

# ============================================================================
# STEP 2: LEGACY MARKER AUTO-CAPTURE (backward compat)
# ============================================================================

JSONL_FILE=""
if [ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ]; then
    JSONL_FILE="$TRANSCRIPT"
else
    CLAUDE_PROJECTS="$HOME/.claude/projects"
    if [ -d "$CLAUDE_PROJECTS" ]; then
        JSONL_FILE=$(find "$CLAUDE_PROJECTS" -name "*.jsonl" -newer "$SESSION_PATH/memory.md" 2>/dev/null | head -1)
    fi
fi

if [ -f "$JSONL_FILE" ]; then
    LAST_RESPONSE=$(tail -50 "$JSONL_FILE" 2>/dev/null | jq -r '
        select(.type == "assistant") |
        .message.content // [] |
        if type == "array" then
            [.[] | select(.type == "text") | .text // empty] | join("\n")
        else empty end
    ' 2>/dev/null | tail -1)

    if [ -n "$LAST_RESPONSE" ]; then
        # [!] -> facts.md
        FACTS=$(echo "$LAST_RESPONSE" | grep -oP '^\[!\]\s*\K.*' 2>/dev/null | head -5)
        if [ -n "$FACTS" ]; then
            echo "$FACTS" | while IFS= read -r line; do
                echo "" >> "$SESSION_PATH/facts.md"
                echo "## $TIMESTAMP - $line" >> "$SESSION_PATH/facts.md"
            done
        fi
        # [*] -> context.md
        CONTEXTS=$(echo "$LAST_RESPONSE" | grep -oP '^\[\*\]\s*\K.*' 2>/dev/null | head -5)
        if [ -n "$CONTEXTS" ]; then
            echo "$CONTEXTS" | while IFS= read -r line; do
                echo "" >> "$SESSION_PATH/context.md"
                echo "## $TIMESTAMP - $line" >> "$SESSION_PATH/context.md"
            done
        fi
        # [>] -> intent.md
        INTENTS=$(echo "$LAST_RESPONSE" | grep -oP '^\[>\]\s*\K.*' 2>/dev/null | head -5)
        if [ -n "$INTENTS" ]; then
            echo "$INTENTS" | while IFS= read -r line; do
                echo "" >> "$SESSION_PATH/intent.md"
                echo "## $TIMESTAMP - $line" >> "$SESSION_PATH/intent.md"
            done
        fi
        # [i] -> memory.md
        INFOS=$(echo "$LAST_RESPONSE" | grep -oP '^\[i\]\s*\K.*' 2>/dev/null | head -5)
        if [ -n "$INFOS" ]; then
            echo "$INFOS" | while IFS= read -r line; do
                echo "" >> "$SESSION_PATH/memory.md"
                echo "## $TIMESTAMP - $line" >> "$SESSION_PATH/memory.md"
            done
        fi
    fi
fi

# ============================================================================
# STEP 3: CONTEXT ESTIMATION
# ============================================================================

CONTEXT_WARNING=""

if [ -f "$JSONL_FILE" ]; then
    TOTAL_SIZE=$(wc -c < "$JSONL_FILE" 2>/dev/null)
    LAST_SUMMARY_LINE=$(grep -n '"type":"summary"' "$JSONL_FILE" 2>/dev/null | tail -1 | cut -d: -f1)

    if [ -n "$LAST_SUMMARY_LINE" ] && [ "$LAST_SUMMARY_LINE" -gt 0 ]; then
        SUMMARY_OFFSET=$(head -n "$LAST_SUMMARY_LINE" "$JSONL_FILE" 2>/dev/null | wc -c)
        CURRENT_BYTES=$((TOTAL_SIZE - SUMMARY_OFFSET))
    else
        CURRENT_BYTES=$TOTAL_SIZE
    fi

    if [ "$CURRENT_BYTES" -gt 0 ]; then
        EST_PERCENT=$((CURRENT_BYTES * 100 / CONTEXT_LIMIT))
        [ "$EST_PERCENT" -gt 100 ] && EST_PERCENT=100
        REMAINING=$((100 - EST_PERCENT))
    fi

    MCI_FILE="$SESSION_PATH/memory.mci"
    MCI_ENTRIES=0
    [ -f "$MCI_FILE" ] && MCI_ENTRIES=$(grep -c "^Memory:" "$MCI_FILE" 2>/dev/null | head -1 || echo 0)
    MCI_ENTRIES=${MCI_ENTRIES:-0}
    MCI_ENTRIES=$((MCI_ENTRIES + 0))

    # state.md status for warnings
    STATE_STATUS="MISSING"
    if [ -f "$STATE_FILE" ]; then
        SS=$(wc -c < "$STATE_FILE" 2>/dev/null || echo 0)
        [ "$SS" -gt 200 ] && STATE_STATUS="ACTIVE" || STATE_STATUS="TEMPLATE"
    fi

    if [ "$CURRENT_BYTES" -ge "$EMERGENCY_BYTES" ]; then
        CONTEXT_WARNING="EMERGENCY: ~${REMAINING}% context remaining. Auto-compact IMMINENT. Update state.md NOW — it survives compact. state.md: $STATE_STATUS (.mci entries: $MCI_ENTRIES)"
    elif [ "$CURRENT_BYTES" -ge "$CRITICAL_BYTES" ]; then
        CONTEXT_WARNING="WARNING: ~${REMAINING}% context remaining. Ensure state.md is current (Goal/Progress/Findings). state.md: $STATE_STATUS (.mci entries: $MCI_ENTRIES)"
    elif [ "$CURRENT_BYTES" -ge "$WARN_BYTES" ]; then
        CONTEXT_WARNING="Context checkpoint: ~${REMAINING}% remaining. Good time to update state.md with current progress."
    fi
fi

# ============================================================================
# OUTPUT
# ============================================================================

COMBINED_WARNING=""
[ -n "$STATE_WARNING" ] && COMBINED_WARNING="$STATE_WARNING"
if [ -n "$CONTEXT_WARNING" ]; then
    [ -n "$COMBINED_WARNING" ] && COMBINED_WARNING="$COMBINED_WARNING\n$CONTEXT_WARNING" || COMBINED_WARNING="$CONTEXT_WARNING"
fi

if [ -n "$COMBINED_WARNING" ]; then
    WARNING_ESCAPED=$(echo -e "$COMBINED_WARNING" | jq -Rs .)
    cat << EOF
{
  "hookSpecificOutput": {
    "additionalContext": $WARNING_ESCAPED
  }
}
EOF
else
    echo '{"suppressOutput": true}'
fi

exit 0
