#!/bin/bash
# ============================================================================
# MCI v2 STOP HOOK — Validates state.md + .mci, generates summary
# PRIMARY: Snapshot state.md to .mci if not already done
# SECONDARY: Generate session-summary.md, push to claude-mem
# ============================================================================

MEMORY_BASE="/path/to/workspace"

# Cloud sync bridges
SYNC_BRIDGE="/opt/claude-memory-sync/hooks/sync-bridge.sh"
[ -f "$SYNC_BRIDGE" ] && source "$SYNC_BRIDGE"

SESSION_DATE_ISO=$(date +%Y-%m-%d)
SESSION_DATE_LEGACY=$(date +%m-%d-%Y)
TIMESTAMP=$(date +%H:%M:%S)
# claude-mem references removed — replaced by claude-memory-sync
CLAUDE_PROJECT_DIR="$MEMORY_BASE/.claude/projects/$(basename "$MEMORY_BASE")"
CURRENT_SESSION_FILE="$MEMORY_BASE/.claude-memory/current-session"
MAX_SUMMARY_CHARS=8000

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
[ -z "$SESSION_PATH" ] && exit 0

MCI_FILE="$SESSION_PATH/memory.mci"
STATE_FILE="$SESSION_PATH/state.md"
JSONL_FILE=$(ls -t "$CLAUDE_PROJECT_DIR"/*.jsonl 2>/dev/null | head -1)
[ -z "$JSONL_FILE" ] && exit 0

# ============================================================================
# DEBOUNCE: Skip if Stop fired within last 120 seconds
# ============================================================================
DEBOUNCE_FILE="$SESSION_PATH/.stop-debounce"
NOW=$(date +%s)
if [ -f "$DEBOUNCE_FILE" ]; then
    LAST_STOP=$(cat "$DEBOUNCE_FILE" 2>/dev/null || echo 0)
    DIFF=$((NOW - LAST_STOP))
    if [ "$DIFF" -lt 120 ]; then
        echo '{"suppressOutput": true}'
        exit 0
    fi
fi
echo "$NOW" > "$DEBOUNCE_FILE"

# ============================================================================
# STEP 1: ENSURE .MCI HAS FINAL STATE
# ============================================================================

MCI_COMPLETE="false"
if [ -f "$MCI_FILE" ]; then
    HAS_MEMORY=$(grep -c "^Memory:" "$MCI_FILE" 2>/dev/null || echo 0)
    HAS_CONTEXT=$(grep -c "^Context:" "$MCI_FILE" 2>/dev/null || echo 0)
    HAS_INTENT=$(grep -c "^Intent:" "$MCI_FILE" 2>/dev/null || echo 0)
    if [ "$HAS_MEMORY" -gt 0 ] && [ "$HAS_CONTEXT" -gt 0 ] && [ "$HAS_INTENT" -gt 0 ]; then
        MCI_COMPLETE="true"
    fi
fi

# ============================================================================
# STEP 2: SNAPSHOT state.md IF .MCI INCOMPLETE
# ============================================================================

if [ "$MCI_COMPLETE" = "false" ]; then
    # Try state.md first (v2)
    if [ -f "$STATE_FILE" ]; then
        STATE_SIZE=$(wc -c < "$STATE_FILE" 2>/dev/null || echo 0)
        if [ "$STATE_SIZE" -gt 200 ]; then
            GOAL=$(sed -n '/^## Goal/,/^## /{ /^## Goal/d; /^## /d; p; }' "$STATE_FILE" 2>/dev/null | head -c 1500 | sed '/^$/d' | head -20)
            PROGRESS=$(sed -n '/^## Progress/,/^## /{ /^## Progress/d; /^## /d; p; }' "$STATE_FILE" 2>/dev/null | head -c 2000 | head -30)
            FINDINGS=$(sed -n '/^## Findings/,/^## /{ /^## Findings/d; /^## /d; p; }' "$STATE_FILE" 2>/dev/null | head -c 2000 | head -30)

            cat >> "$MCI_FILE" << MCIEOF

--- [STOP] state.md Final Snapshot @ $TIMESTAMP ---
Memory: GOAL: ${GOAL:-No goal set}
Context: PROGRESS: ${PROGRESS:-No progress tracked}
Intent: FINDINGS: ${FINDINGS:-No findings yet}
MCIEOF
            MCI_COMPLETE="true"
        fi
    fi

    # Fallback: extract from JSONL — SINGLE jq pass (was 5 separate passes)
    if [ "$MCI_COMPLETE" = "false" ] && [ -f "$JSONL_FILE" ]; then
        JSONL_EXTRACT=$(jq -r '
            if .type == "user" then
                "USERMSG:" + ((.message.content // "") |
                    if type == "array" then [.[] | select(.type == "text") | .text // empty] | join(" ")
                    elif type == "string" then . else "" end)
            elif .type == "assistant" then
                (.message.content // []) | if type == "array" then .[] else . end |
                if .type == "tool_use" then
                    "TOOL:" + .name,
                    if (.name == "Write" or .name == "Edit") then "FILE:" + (.input.file_path // "") else empty end
                elif .type == "text" then
                    (.text // "") | split("\n")[] |
                    if startswith("[!]") then "BANG:" + . elif startswith("[>]") then "NEXT:" + . else empty end
                else empty end
            else empty end
        ' "$JSONL_FILE" 2>/dev/null)

        TOOLS_USED=$(echo "$JSONL_EXTRACT" | grep "^TOOL:" | sed 's/^TOOL://' | sort | uniq -c | sort -rn | head -5 | tr '\n' ', ')
        FILES_MODIFIED=$(echo "$JSONL_EXTRACT" | grep "^FILE:" | sed 's/^FILE://' | sort -u | head -10 | tr '\n' ', ')
        LAST_USER=$(echo "$JSONL_EXTRACT" | grep "^USERMSG:" | sed 's/^USERMSG://' | grep -v '^$' | tail -3 | head -c 300)
        MARKER_MEMORY=$(echo "$JSONL_EXTRACT" | grep "^BANG:" | sed 's/^BANG:\[!\] *//' | tail -1)
        MARKER_INTENT=$(echo "$JSONL_EXTRACT" | grep "^NEXT:" | sed 's/^NEXT:\[>\] *//' | tail -1)

        STOP_MEMORY="${MARKER_MEMORY:-[STOP] Session ended. Tools: ${TOOLS_USED:-none}. Files: ${FILES_MODIFIED:-none}}"
        STOP_CONTEXT="Session ended at $TIMESTAMP. Last user topic: $(echo "$LAST_USER" | head -c 150)"
        STOP_INTENT="${MARKER_INTENT:-Continue from last topic next session.}"

        cat >> "$MCI_FILE" << MCIEOF

--- [STOP] Auto-Generated @ $TIMESTAMP ---
Memory: $STOP_MEMORY
Context: $STOP_CONTEXT
Intent: $STOP_INTENT
MCIEOF
    fi
fi

# ============================================================================
# STEP 3: GENERATE SESSION SUMMARY
# ============================================================================

# SINGLE jq pass for summary stats (was 3 separate passes)
SUMMARY_RAW=$(jq -r '
    if .type == "user" then "U"
    elif .type == "assistant" then
        (.message.content // []) | if type == "array" then .[] else empty end |
        if .type == "tool_use" then
            "T:" + .name,
            if (.name == "Write" or .name == "Edit") then "F:" + (.input.file_path // "") else empty end
        else empty end
    else empty end
' "$JSONL_FILE" 2>/dev/null)

USER_COUNT=$(echo "$SUMMARY_RAW" | grep -c "^U$" || echo 0)
TOOL_STATS=$(echo "$SUMMARY_RAW" | grep "^T:" | sed 's/^T://' | sort | uniq -c | sort -rn | head -15)
TOOL_COUNT=$(echo "$TOOL_STATS" | awk '{s+=$1} END {print s+0}')
FILES_ALL=$(echo "$SUMMARY_RAW" | grep "^F:" | sed 's/^F://' | sort -u | head -20)

START_TIME=$(head -1 "$SESSION_PATH/memory.md" 2>/dev/null | grep -oP '\d{2}:\d{2}' || echo "unknown")

SUMMARY_FILE="$SESSION_PATH/session-summary.md"

# Include state.md status in summary
STATE_INFO="NOT FOUND"
if [ -f "$STATE_FILE" ]; then
    STATE_SIZE=$(wc -c < "$STATE_FILE" 2>/dev/null || echo 0)
    if [ "$STATE_SIZE" -gt 200 ]; then
        STATE_INFO="ACTIVE ($STATE_SIZE bytes)"
    else
        STATE_INFO="TEMPLATE ONLY"
    fi
fi

# Doctor MCI status for summary
DOCTOR_SUMMARY_STATUS="NOT FOUND"
if [ -f "$SESSION_PATH/doctor-mci.md" ]; then
    DS_SIZE=$(wc -c < "$SESSION_PATH/doctor-mci.md" 2>/dev/null || echo 0)
    DS_MTIME=$(stat -c %Y "$SESSION_PATH/doctor-mci.md" 2>/dev/null || echo 0)
    DS_AGE=$(( ($(date +%s) - DS_MTIME) / 60 ))
    DOCTOR_SUMMARY_STATUS="PRESENT (${DS_SIZE}b, ${DS_AGE}min old)"
fi
VITALS_SUMMARY_STATUS="NOT FOUND"
if [ -f "$SESSION_PATH/vitals.md" ]; then
    VS_STATUS=$(head -5 "$SESSION_PATH/vitals.md" 2>/dev/null | grep -oP 'Status: \K.*' | head -1)
    VITALS_SUMMARY_STATUS="${VS_STATUS:-UNKNOWN}"
fi

cat > "$SUMMARY_FILE" << SUMMARYEOF
# Session Summary - $SESSION_DATE_ISO $TIMESTAMP

## Duration
- Started: $START_TIME
- Ended: $TIMESTAMP

## Memory Status
- state.md: $STATE_INFO
- MCI: $MCI_FILE ($([ "$MCI_COMPLETE" = "true" ] && echo "complete" || echo "auto-generated"))
- MCI entries: $(grep -c "^Memory:" "$MCI_FILE" 2>/dev/null || echo 0)
- Doctor MCI: $DOCTOR_SUMMARY_STATUS
- Doctor Vitals: $VITALS_SUMMARY_STATUS

## Stats
- User messages: ~$USER_COUNT
- Tool calls: $TOOL_COUNT

## Tools Used
$TOOL_STATS

## Files Modified
$FILES_ALL
SUMMARYEOF

truncate -s "<$MAX_SUMMARY_CHARS" "$SUMMARY_FILE" 2>/dev/null

# ============================================================================
# STEP 4: UPDATE SESSION MEMORY.MD
# ============================================================================

cat >> "$SESSION_PATH/memory.md" << EOF

---
## $TIMESTAMP - SESSION ENDED [state.md: $STATE_INFO | MCI: $([ "$MCI_COMPLETE" = "true" ] && echo "COMPLETE" || echo "AUTO-GENERATED")]
Summary: $SUMMARY_FILE
EOF

# ============================================================================
# STEP 6: CLOUD SYNC — Push final state.md
# ============================================================================

if type sync_push &>/dev/null && [ -f "$STATE_FILE" ]; then
    export CLAUDE_MEMORY_SYNC_SOURCE="claude-code"
    sync_push "$STATE_FILE"
fi


# ============================================================================
# STEP 7: MEMORY-ENGINE AUTO-INGEST — Feed conversation into memory DB
# ============================================================================

INGEST_SCRIPT="/path/to/workspace/infrastructure/memory-engine/auto_ingest.py"
if [ -f "$INGEST_SCRIPT" ]; then
    # Ingest the latest session + re-process recent ones (catches updates)
    python3 "$INGEST_SCRIPT" recent 3 &>/dev/null &
fi

echo '{"suppressOutput": true}'
exit 0
