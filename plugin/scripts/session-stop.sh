#!/bin/bash
# ============================================================================
# SESSION STOP - Ensures session ends with valid .mci for next pickup
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
[ -z "$JSONL_FILE" ] || [ ! -f "$JSONL_FILE" ] && { echo '{"suppressOutput": true}'; exit 0; }

# ============================================================================
# STEP 1: VALIDATE .MCI
# ============================================================================

MCI_COMPLETE="false"
if [ -f "$MCI_FILE" ]; then
    HAS_M=$(grep -c "^Memory:" "$MCI_FILE" 2>/dev/null || echo 0)
    HAS_C=$(grep -c "^Context:" "$MCI_FILE" 2>/dev/null || echo 0)
    HAS_I=$(grep -c "^Intent:" "$MCI_FILE" 2>/dev/null || echo 0)
    [ "$HAS_M" -gt 0 ] && [ "$HAS_C" -gt 0 ] && [ "$HAS_I" -gt 0 ] && MCI_COMPLETE="true"
fi

# ============================================================================
# STEP 2: AUTO-GENERATE .MCI IF INCOMPLETE
# ============================================================================

if [ "$MCI_COMPLETE" = "false" ]; then
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

    # Try to find markers in Claude's output
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

## M/C/I Status
- Complete: $([ "$MCI_COMPLETE" = "true" ] && echo "YES (saved by Claude)" || echo "NO (auto-generated at stop)")
- Entries: $(grep -c "^Memory:" "$MCI_FILE" 2>/dev/null || echo 0)

## Stats
- User messages: ~$USER_COUNT
- Tool calls: $TOOL_COUNT

## Tools Used
$TOOL_STATS

## Files Modified
$FILES_ALL
SUMMARYEOF

# Truncate if too long
truncate -s "<8000" "$SESSION_PATH/session-summary.md" 2>/dev/null

# Update session log
echo "" >> "$SESSION_PATH/memory.md"
echo "## $TIMESTAMP - SESSION ENDED [MCI: $([ "$MCI_COMPLETE" = "true" ] && echo "COMPLETE" || echo "AUTO-GENERATED")]" >> "$SESSION_PATH/memory.md"

echo '{"suppressOutput": true}'
exit 0
