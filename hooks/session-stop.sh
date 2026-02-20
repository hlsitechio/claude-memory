#!/bin/bash
# ============================================================================
# claude-memory v2 SESSION STOP — state.md snapshot + session summary
# Ensures session ends with valid .mci (snapshots state.md if available)
# Generates session-summary.md with tool stats and file list
# ============================================================================

MEMORY_BASE="${CLAUDE_PROJECT_DIR:-.}/.claude-memory"
TIMESTAMP=$(date +%H:%M:%S)

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

MCI_FILE="$SESSION_PATH/memory.mci"
STATE_FILE="$SESSION_PATH/state.md"

# Find JSONL
JSONL_FILE=""
if [ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ]; then
    JSONL_FILE="$TRANSCRIPT"
else
    CLAUDE_PROJECTS="$HOME/.claude/projects"
    if [ -d "$CLAUDE_PROJECTS" ]; then
        JSONL_FILE=$(find "$CLAUDE_PROJECTS" -name "*.jsonl" -newer "$SESSION_PATH/memory.md" 2>/dev/null | head -1)
    fi
fi

# ============================================================================
# STEP 1: SNAPSHOT state.md TO .mci (v2 — primary approach)
# ============================================================================

MCI_WRITTEN="false"

if [ -f "$STATE_FILE" ]; then
    STATE_SIZE=$(wc -c < "$STATE_FILE" 2>/dev/null || echo 0)
    if [ "$STATE_SIZE" -gt 200 ]; then
        GOAL=$(sed -n '/^## Goal/,/^## /{ /^## Goal/d; /^## /d; p; }' "$STATE_FILE" 2>/dev/null | head -c 1500 | sed '/^$/d' | head -20)
        PROGRESS=$(sed -n '/^## Progress/,/^## /{ /^## Progress/d; /^## /d; p; }' "$STATE_FILE" 2>/dev/null | head -c 2000 | head -30)
        FINDINGS=$(sed -n '/^## Findings/,/^## /{ /^## Findings/d; /^## /d; p; }' "$STATE_FILE" 2>/dev/null | head -c 2000 | head -30)

        cat >> "$MCI_FILE" << MCIEOF

--- [STOP] state.md Snapshot @ $TIMESTAMP ---
Memory: GOAL: ${GOAL:-No goal set}
Context: PROGRESS: ${PROGRESS:-No progress tracked}
Intent: FINDINGS: ${FINDINGS:-No findings yet}
MCIEOF
        MCI_WRITTEN="true"
    fi
fi

# ============================================================================
# STEP 2: FALLBACK — Auto-generate from JSONL if no state.md
# ============================================================================

if [ "$MCI_WRITTEN" = "false" ] && [ -f "$JSONL_FILE" ]; then
    TOOLS_USED=$(jq -r '
        select(.type == "assistant") |
        .message.content // [] |
        if type == "array" then .[] else empty end |
        select(.type == "tool_use") | .name
    ' "$JSONL_FILE" 2>/dev/null | sort | uniq -c | sort -rn | head -5 | tr '\n' ', ')

    FILES_MODIFIED=$(jq -r '
        select(.type == "assistant") |
        .message.content // [] |
        if type == "array" then .[] else empty end |
        select(.type == "tool_use" and (.name == "Write" or .name == "Edit")) |
        .input.file_path // empty
    ' "$JSONL_FILE" 2>/dev/null | sort -u | head -10 | tr '\n' ', ')

    LAST_USER=$(jq -r '
        select(.type == "user") |
        .message.content // "" |
        if type == "array" then
            [.[] | select(.type == "text") | .text // empty] | join(" ")
        elif type == "string" then .
        else empty end
    ' "$JSONL_FILE" 2>/dev/null | grep -v '^$' | tail -3 | head -c 300)

    MARKER_MEMORY=$(jq -r '
        select(.type == "assistant") |
        .message.content // [] |
        if type == "array" then .[] else . end |
        select(.type == "text") | .text // empty
    ' "$JSONL_FILE" 2>/dev/null | grep '^\[!\]' | tail -1 | sed 's/^\[!\] *//')

    MARKER_INTENT=$(jq -r '
        select(.type == "assistant") |
        .message.content // [] |
        if type == "array" then .[] else . end |
        select(.type == "text") | .text // empty
    ' "$JSONL_FILE" 2>/dev/null | grep '^\[>\]' | tail -1 | sed 's/^\[>\] *//')

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

# ============================================================================
# STEP 3: GENERATE SESSION SUMMARY
# ============================================================================

if [ -f "$JSONL_FILE" ]; then
    USER_COUNT=$(jq -r 'select(.type == "user")' "$JSONL_FILE" 2>/dev/null | wc -l)
    TOOL_STATS=$(jq -r '
        select(.type == "assistant") |
        .message.content // [] |
        if type == "array" then .[] else empty end |
        select(.type == "tool_use") | .name
    ' "$JSONL_FILE" 2>/dev/null | sort | uniq -c | sort -rn | head -15)
    TOOL_COUNT=$(echo "$TOOL_STATS" | awk '{s+=$1} END {print s+0}')
    FILES_ALL=$(jq -r '
        select(.type == "assistant") |
        .message.content // [] |
        if type == "array" then .[] else empty end |
        select(.type == "tool_use" and (.name == "Write" or .name == "Edit")) |
        .input.file_path // empty
    ' "$JSONL_FILE" 2>/dev/null | sort -u | head -20)
    START_TIME=$(head -1 "$SESSION_PATH/memory.md" 2>/dev/null | grep -oP '\d{2}:\d{2}' || echo "unknown")

    cat > "$SESSION_PATH/session-summary.md" << SUMMARYEOF
# Session Summary - $(date +%Y-%m-%d) $TIMESTAMP

## Duration
- Started: $START_TIME
- Ended: $TIMESTAMP

## Memory Status
- state.md: $([ -f "$STATE_FILE" ] && echo "EXISTS ($(wc -c < "$STATE_FILE" 2>/dev/null) bytes)" || echo "MISSING")
- MCI saved by: $([ "$MCI_WRITTEN" = "true" ] && echo "state.md snapshot" || echo "auto-generated from JSONL")
- MCI entries: $(grep -c "^Memory:" "$MCI_FILE" 2>/dev/null || echo 0)

## Stats
- User messages: ~$USER_COUNT
- Tool calls: $TOOL_COUNT

## Tools Used
$TOOL_STATS

## Files Modified
$FILES_ALL
SUMMARYEOF

    truncate -s "<8000" "$SESSION_PATH/session-summary.md" 2>/dev/null
fi

# Update session log
echo "" >> "$SESSION_PATH/memory.md"
echo "## $TIMESTAMP - SESSION ENDED [state.md: $([ -f "$STATE_FILE" ] && echo "EXISTS" || echo "MISSING")]" >> "$SESSION_PATH/memory.md"

echo '{"suppressOutput": true}'
exit 0
