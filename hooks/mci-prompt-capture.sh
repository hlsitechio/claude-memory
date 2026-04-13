#!/bin/bash
# ============================================================================
# MCI v2 PROMPT CAPTURE — Context estimation + state.md health check
# Fires on every UserPromptSubmit. Must be FAST (<2s).
# PRIMARY: Estimate context usage, warn when compact approaches
# SECONDARY: Check state.md exists and has content
# LEGACY: Auto-capture markers from JSONL (backward compat)
# ============================================================================

# Suppress ALL stderr — Claude Code treats any stderr as hook error
exec 2>/dev/null

MEMORY_BASE="/path/to/workspace"
TODAY_ISO=$(date +%Y-%m-%d)
DAILY_LOG="$MEMORY_BASE/memory/$TODAY_ISO.md"
TIMESTAMP=$(date +%H:%M:%S)
SESSION_DATE_LEGACY=$(date +%m-%d-%Y)
CLAUDE_PROJECT_DIR="$MEMORY_BASE/.claude/projects/$(basename "$MEMORY_BASE")"
CURRENT_SESSION_FILE="$MEMORY_BASE/.claude-memory/current-session"


# JSONL file (needed for external change detection + legacy markers)
JSONL_FILE=$(ls -t "$CLAUDE_PROJECT_DIR"/*.jsonl 2>/dev/null | head -1)

# Prompt counter for periodic heartbeat (every 5th prompt)
PROMPT_COUNTER_FILE="$MEMORY_BASE/.claude-memory/prompt-counter"
PROMPT_COUNT=0
if [ -f "$PROMPT_COUNTER_FILE" ]; then
    PROMPT_COUNT=$(cat "$PROMPT_COUNTER_FILE" 2>/dev/null || echo 0)
fi
PROMPT_COUNT=$((PROMPT_COUNT + 1))
echo "$PROMPT_COUNT" > "$PROMPT_COUNTER_FILE"

# Context estimation thresholds (calibrated)
CONTEXT_LIMIT_BYTES=1000000
WARN_BYTES=700000
CRITICAL_BYTES=850000
EMERGENCY_BYTES=950000

# Read hook input from stdin (200ms timeout — don't let stdin hang)
HOOK_INPUT=$(timeout 0.2 cat 2>/dev/null || echo "{}")

# Extract prompt text
USER_PROMPT=$(echo "$HOOK_INPUT" | jq -r '
    .hookInput.userPrompt //
    .hookInput.prompt //
    .input.prompt //
    empty
' 2>/dev/null)

# ============================================================================
# PROMPT LOGGING
# ============================================================================

if [ -n "$USER_PROMPT" ] && [ "$USER_PROMPT" != "null" ]; then
    mkdir -p "$MEMORY_BASE/memory"
    [ ! -f "$DAILY_LOG" ] && echo "# Session Notes - $TODAY_ISO" > "$DAILY_LOG"
    TRUNCATED=$(echo "$USER_PROMPT" | head -c 500)
    echo "" >> "$DAILY_LOG"
    echo "**$TIMESTAMP** - $TRUNCATED" >> "$DAILY_LOG"
fi

# ============================================================================
# RESOLVE SESSION PATH
# ============================================================================

SESSION_PATH=""
if [ -f "$CURRENT_SESSION_FILE" ]; then
    PLUGIN_SESSION=$(cat "$CURRENT_SESSION_FILE" 2>/dev/null)
    if [ -n "$PLUGIN_SESSION" ] && [ -d "$PLUGIN_SESSION" ]; then
        SESSION_PATH="$PLUGIN_SESSION"
    fi
fi
if [ -z "$SESSION_PATH" ]; then
    SESSION_BASE="$MEMORY_BASE/memory_sessions/$SESSION_DATE_LEGACY"
    SESSION_PATH=$(ls -d "$SESSION_BASE"/session-* 2>/dev/null | sort -V | tail -1)
fi

# ============================================================================
# STATE.MD HEALTH CHECK + EXTERNAL CHANGE DETECTION
# ============================================================================

STATE_WARNING=""
EXTERNAL_UPDATE=""
if [ -n "$SESSION_PATH" ]; then
    STATE_FILE="$SESSION_PATH/state.md"
    MTIME_TRACKER="$SESSION_PATH/.state-mtime"

    if [ ! -f "$STATE_FILE" ]; then
        STATE_WARNING="[!] state.md MISSING at $SESSION_PATH/state.md — create it now!"
    else
        STATE_SIZE=$(wc -c < "$STATE_FILE" 2>/dev/null || echo 0)
        if [ "$STATE_SIZE" -lt 200 ]; then
            STATE_WARNING="[i] state.md is still template-only. Update Goal/Progress when you start working."
        fi

        # External change detection (Claude Desktop → Claude Code sync)
        CURRENT_MTIME=$(stat -c %Y "$STATE_FILE" 2>/dev/null || echo 0)
        if [ -f "$MTIME_TRACKER" ]; then
            LAST_MTIME=$(cat "$MTIME_TRACKER" 2>/dev/null || echo 0)
            if [ "$CURRENT_MTIME" != "$LAST_MTIME" ]; then
                # state.md changed since last prompt — check if WE did it
                # If the JSONL was modified MORE recently than state.md, Code probably wrote it
                if [ -f "$JSONL_FILE" ]; then
                    JSONL_MTIME=$(stat -c %Y "$JSONL_FILE" 2>/dev/null || echo 0)
                    # If state.md is NEWER than JSONL, an external process wrote it
                    if [ "$CURRENT_MTIME" -gt "$JSONL_MTIME" ]; then
                        EXTERNAL_UPDATE="[!] state.md was updated externally (Claude Desktop?). Re-read it:\n$(cat "$STATE_FILE" 2>/dev/null)"
                    fi
                else
                    # No JSONL = definitely external
                    EXTERNAL_UPDATE="[!] state.md was updated externally. Re-read it:\n$(cat "$STATE_FILE" 2>/dev/null)"
                fi
            fi
        fi
        # Update mtime tracker
        echo "$CURRENT_MTIME" > "$MTIME_TRACKER"
    fi
fi

# ============================================================================
# LEGACY MARKER AUTO-CAPTURE (backward compat)
# Captures markers from JSONL and writes to old marker files + memory.md
# ============================================================================

# JSONL_FILE already resolved at top of script

if [ -f "$JSONL_FILE" ] && [ -n "$SESSION_PATH" ]; then
    LAST_RESPONSE=$(tail -50 "$JSONL_FILE" 2>/dev/null | jq -r '
        select(.type == "assistant") |
        .message.content // [] |
        if type == "array" then
            [.[] | select(.type == "text") | .text // empty] | join("\n")
        else empty end
    ' 2>/dev/null | tail -1)

    if [ -n "$LAST_RESPONSE" ]; then
        MARKER_TS=$(date +%H:%M)

        # [i] → memory.md (session log — always capture these)
        INFOS=$(echo "$LAST_RESPONSE" | grep -oP '^\[i\]\s*\K.*' 2>/dev/null | head -5)
        if [ -n "$INFOS" ]; then
            [ ! -f "$SESSION_PATH/memory.md" ] && echo "# Memory - $(basename "$SESSION_PATH")" > "$SESSION_PATH/memory.md"
            echo "$INFOS" | while IFS= read -r line; do
                echo "" >> "$SESSION_PATH/memory.md"
                echo "## $MARKER_TS - $line" >> "$SESSION_PATH/memory.md"
            done
        fi

        # Legacy marker files (backward compat — keep for older systems)
        FACTS=$(echo "$LAST_RESPONSE" | grep -oP '^\[!\]\s*\K.*' 2>/dev/null | head -5)
        if [ -n "$FACTS" ]; then
            [ ! -f "$SESSION_PATH/facts.md" ] && echo "# Facts" > "$SESSION_PATH/facts.md"
            echo "$FACTS" | while IFS= read -r line; do
                echo "" >> "$SESSION_PATH/facts.md"
                echo "## $MARKER_TS - $line" >> "$SESSION_PATH/facts.md"
            done
        fi

        CONTEXTS=$(echo "$LAST_RESPONSE" | grep -oP '^\[\*\]\s*\K.*' 2>/dev/null | head -5)
        if [ -n "$CONTEXTS" ]; then
            [ ! -f "$SESSION_PATH/context.md" ] && echo "# Context" > "$SESSION_PATH/context.md"
            echo "$CONTEXTS" | while IFS= read -r line; do
                echo "" >> "$SESSION_PATH/context.md"
                echo "## $MARKER_TS - $line" >> "$SESSION_PATH/context.md"
            done
        fi

        INTENTS=$(echo "$LAST_RESPONSE" | grep -oP '^\[>\]\s*\K.*' 2>/dev/null | head -5)
        if [ -n "$INTENTS" ]; then
            [ ! -f "$SESSION_PATH/intent.md" ] && echo "# Intent" > "$SESSION_PATH/intent.md"
            echo "$INTENTS" | while IFS= read -r line; do
                echo "" >> "$SESSION_PATH/intent.md"
                echo "## $MARKER_TS - $line" >> "$SESSION_PATH/intent.md"
            done
        fi
    fi
fi

# ============================================================================
# CONTEXT ESTIMATION
# ============================================================================

CONTEXT_WARNING=""

if [ -f "$JSONL_FILE" ]; then
    LAST_SUMMARY_LINE=$(grep -n '"type":"summary"' "$JSONL_FILE" 2>/dev/null | tail -1 | cut -d: -f1)
    TOTAL_SIZE=$(wc -c < "$JSONL_FILE" 2>/dev/null)

    LAST_SESSION_START=$(grep -n '"hookEvent":"SessionStart"' "$JSONL_FILE" 2>/dev/null | tail -1 | cut -d: -f1)

    if [ -n "$LAST_SESSION_START" ] && [ "$LAST_SESSION_START" -gt 5 ]; then
        START_OFFSET=$(head -n "$LAST_SESSION_START" "$JSONL_FILE" 2>/dev/null | wc -c)
        CURRENT_CONTEXT_BYTES=$((TOTAL_SIZE - START_OFFSET))
        CURRENT_CONTEXT_BYTES=$((CURRENT_CONTEXT_BYTES + 60000))
    elif [ -n "$LAST_SUMMARY_LINE" ] && [ "$LAST_SUMMARY_LINE" -gt 0 ]; then
        SUMMARY_OFFSET=$(head -n "$LAST_SUMMARY_LINE" "$JSONL_FILE" 2>/dev/null | wc -c)
        CURRENT_CONTEXT_BYTES=$((TOTAL_SIZE - SUMMARY_OFFSET))
    else
        CURRENT_CONTEXT_BYTES=$TOTAL_SIZE
    fi

    if [ "$CURRENT_CONTEXT_BYTES" -gt 0 ]; then
        EST_PERCENT=$((CURRENT_CONTEXT_BYTES * 100 / CONTEXT_LIMIT_BYTES))
        [ "$EST_PERCENT" -gt 100 ] && EST_PERCENT=100
        REMAINING=$((100 - EST_PERCENT))
    fi

    # Microcompact adjustment
    MICROCOMPACT_COUNT=$(grep -c '"microcompact_boundary"' "$JSONL_FILE" 2>/dev/null | head -1 || echo 0)
    MICROCOMPACT_COUNT=${MICROCOMPACT_COUNT:-0}
    MICROCOMPACT_COUNT=$((MICROCOMPACT_COUNT + 0))
    if [ "$MICROCOMPACT_COUNT" -gt 0 ] && [ "$CURRENT_CONTEXT_BYTES" -lt "$WARN_BYTES" ]; then
        MICRO_ADJUSTMENT=$((MICROCOMPACT_COUNT * 250000))
        CURRENT_CONTEXT_BYTES=$((CURRENT_CONTEXT_BYTES + MICRO_ADJUSTMENT))
    fi

    # State.md status for warnings
    STATE_INFO=""
    if [ -n "$SESSION_PATH" ] && [ -f "$SESSION_PATH/state.md" ]; then
        SS=$(wc -c < "$SESSION_PATH/state.md" 2>/dev/null || echo 0)
        if [ "$SS" -gt 200 ]; then
            STATE_INFO="state.md: ACTIVE"
        else
            STATE_INFO="state.md: TEMPLATE (update it!)"
        fi
    else
        STATE_INFO="state.md: MISSING"
    fi

    # Generate warnings
    if [ "$CURRENT_CONTEXT_BYTES" -ge "$EMERGENCY_BYTES" ]; then
        CONTEXT_WARNING="[!] EMERGENCY: Context ~${REMAINING}% remaining. Compact IMMINENT. Ensure state.md is current! $STATE_INFO"
    elif [ "$CURRENT_CONTEXT_BYTES" -ge "$CRITICAL_BYTES" ]; then
        CONTEXT_WARNING="[!] WARNING: Context ~${REMAINING}% remaining. Update state.md now if it's stale. $STATE_INFO"
    elif [ "$CURRENT_CONTEXT_BYTES" -ge "$WARN_BYTES" ]; then
        CONTEXT_WARNING="[i] Context ~${REMAINING}% remaining. Keep state.md current. $STATE_INFO"
    fi

    # Post-compact detection
    if [ -n "$LAST_SUMMARY_LINE" ] && [ "$CURRENT_CONTEXT_BYTES" -lt 10000 ]; then
        if [ -n "$SESSION_PATH" ] && [ -f "$SESSION_PATH/state.md" ]; then
            CONTEXT_WARNING="[AC] Post-compact detected. Read your state.md for full recovery: $SESSION_PATH/state.md"
        elif [ -n "$SESSION_PATH" ] && [ -f "$SESSION_PATH/memory.mci" ]; then
            CONTEXT_WARNING="[AC] Post-compact detected. Read your .mci: $SESSION_PATH/memory.mci"
        fi
    fi
fi

# ============================================================================
# OUTPUT
# ============================================================================

# ============================================================================
# TASK INBOX CHECK — pick up tasks from Android/Web
# ============================================================================

TASK_INBOX="/path/to/workspace/.claude-memory/inbox"
TASK_INJECTION=""
if [ -d "$TASK_INBOX" ]; then
    TASK_FILES=$(ls "$TASK_INBOX"/*.task 2>/dev/null)
    if [ -n "$TASK_FILES" ]; then
        TASK_INJECTION="[!] REMOTE TASK RECEIVED:\n"
        for tf in $TASK_FILES; do
            T_PROMPT=$(jq -r '.prompt' "$tf" 2>/dev/null)
            T_SOURCE=$(jq -r '.source' "$tf" 2>/dev/null)
            T_PRIORITY=$(jq -r '.priority' "$tf" 2>/dev/null)
            T_ID=$(jq -r '.id' "$tf" 2>/dev/null)
            TASK_INJECTION="${TASK_INJECTION}From: $T_SOURCE | Priority: $T_PRIORITY\nTask: $T_PROMPT\nID: $T_ID\n---\n"
            # Move to processed
            mv "$tf" "${tf}.done" 2>/dev/null
        done
        TASK_INJECTION="${TASK_INJECTION}[>] Execute these tasks. Update state.md with results. The sender is watching via the sync server."
    fi
fi

COMMAND_INJECTION=""

# ============================================================================
# DOCTOR AGENT HEALTH CHECK
# ============================================================================

DOCTOR_WARNING=""
if [ -n "$SESSION_PATH" ]; then
    DOCTOR_ID_FILE="$SESSION_PATH/doctor.id"
    DOCTOR_VITALS="$SESSION_PATH/vitals.md"
    DOCTOR_MCI="$SESSION_PATH/doctor-mci.md"

    if [ -f "$DOCTOR_VITALS" ]; then
        # Doctor exists — check if still alive (vitals.md freshness)
        V_MTIME=$(stat -c %Y "$DOCTOR_VITALS" 2>/dev/null || echo 0)
        V_NOW=$(date +%s)
        V_AGE=$(( (V_NOW - V_MTIME) / 60 ))

        if [ "$V_AGE" -gt 30 ]; then
            DOCTOR_WARNING="[!] Doctor agent vitals stale (${V_AGE}min). Doctor may be offline. Check vitals.md or respawn."
        fi

        # Check if doctor flagged anything critical
        DOCTOR_STATUS=$(head -5 "$DOCTOR_VITALS" 2>/dev/null | grep -oP 'Status: \K.*' | head -1)
        if [ "$DOCTOR_STATUS" = "CRITICAL" ]; then
            DOCTOR_WARNING="[!] Doctor reports CRITICAL status! Read $DOCTOR_VITALS immediately."
        fi
    fi
fi

# Combine task injection, command injection, state warning, external update, doctor, and context warning
ALL_WARNINGS=""
[ -n "$COMMAND_INJECTION" ] && ALL_WARNINGS="$COMMAND_INJECTION"
[ -n "$TASK_INJECTION" ] && { [ -n "$ALL_WARNINGS" ] && ALL_WARNINGS="$ALL_WARNINGS\n$TASK_INJECTION" || ALL_WARNINGS="$TASK_INJECTION"; }
[ -n "$EXTERNAL_UPDATE" ] && { [ -n "$ALL_WARNINGS" ] && ALL_WARNINGS="$ALL_WARNINGS\n$EXTERNAL_UPDATE" || ALL_WARNINGS="$EXTERNAL_UPDATE"; }
if [ -n "$STATE_WARNING" ]; then
    [ -n "$ALL_WARNINGS" ] && ALL_WARNINGS="$ALL_WARNINGS\n$STATE_WARNING" || ALL_WARNINGS="$STATE_WARNING"
fi
if [ -n "$DOCTOR_WARNING" ]; then
    [ -n "$ALL_WARNINGS" ] && ALL_WARNINGS="$ALL_WARNINGS\n$DOCTOR_WARNING" || ALL_WARNINGS="$DOCTOR_WARNING"
fi
if [ -n "$CONTEXT_WARNING" ]; then
    [ -n "$ALL_WARNINGS" ] && ALL_WARNINGS="$ALL_WARNINGS\n$CONTEXT_WARNING" || ALL_WARNINGS="$CONTEXT_WARNING"
fi

if [ -n "$ALL_WARNINGS" ]; then
    WARNING_ESCAPED=$(echo -e "$ALL_WARNINGS" | jq -Rs .)
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
