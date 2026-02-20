#!/bin/bash
# ============================================================================
# claude-memory v2 PRE-COMPACT — Snapshots FULL state.md into .mci
# PRIMARY: Read state.md content → write to .mci
# FALLBACK 1: Assemble from marker files (backward compat)
# FALLBACK 2: Extract from JSONL (emergency)
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
if [ -z "$SESSION_PATH" ]; then
    SESSION_PATH="$MEMORY_BASE/sessions/$(date +%Y-%m-%d)/session-1"
    mkdir -p "$SESSION_PATH"
fi

MCI_FILE="$SESSION_PATH/memory.mci"
STATE_FILE="$SESSION_PATH/state.md"
COMPACT_FILE="$SESSION_PATH/compact-$TIMESTAMP.md"

# Find JSONL
JSONL_FILE=""
if [ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ]; then
    JSONL_FILE="$TRANSCRIPT"
else
    CLAUDE_PROJECTS="$HOME/.claude/projects"
    [ -d "$CLAUDE_PROJECTS" ] && JSONL_FILE=$(find "$CLAUDE_PROJECTS" -name "*.jsonl" -newer "$SESSION_PATH/memory.md" 2>/dev/null | head -1)
fi

# ============================================================================
# STEP 1: SNAPSHOT state.md INTO .mci (PRIMARY — v2 approach)
# ============================================================================

MCI_WRITTEN="false"

if [ -f "$STATE_FILE" ]; then
    STATE_SIZE=$(wc -c < "$STATE_FILE" 2>/dev/null || echo 0)
    if [ "$STATE_SIZE" -gt 200 ]; then
        GOAL=$(sed -n '/^## Goal/,/^## /{ /^## Goal/d; /^## /d; p; }' "$STATE_FILE" 2>/dev/null | head -c 1500 | sed '/^$/d' | head -20)
        PROGRESS=$(sed -n '/^## Progress/,/^## /{ /^## Progress/d; /^## /d; p; }' "$STATE_FILE" 2>/dev/null | head -c 2000 | head -30)
        FINDINGS=$(sed -n '/^## Findings/,/^## /{ /^## Findings/d; /^## /d; p; }' "$STATE_FILE" 2>/dev/null | head -c 2000 | head -30)

        cat >> "$MCI_FILE" << MCIEOF

--- [PC] state.md Snapshot @ $TIMESTAMP ---
Memory: GOAL: ${GOAL:-No goal set}
Context: PROGRESS: ${PROGRESS:-No progress tracked}
Intent: FINDINGS: ${FINDINGS:-No findings yet}
MCIEOF
        MCI_WRITTEN="true"
    fi
fi

# ============================================================================
# STEP 2: FALLBACK — Assemble from marker files (backward compat)
# ============================================================================

if [ "$MCI_WRITTEN" = "false" ]; then
    LATEST_FACT="" LATEST_CONTEXT="" LATEST_INTENT=""
    [ -f "$SESSION_PATH/facts.md" ] && LATEST_FACT=$(grep "^## " "$SESSION_PATH/facts.md" 2>/dev/null | tail -5 | sed 's/^## [0-9:]* - //' | tr '\n' '; ')
    [ -f "$SESSION_PATH/context.md" ] && LATEST_CONTEXT=$(grep "^## " "$SESSION_PATH/context.md" 2>/dev/null | tail -5 | sed 's/^## [0-9:]* - //' | tr '\n' '; ')
    [ -f "$SESSION_PATH/intent.md" ] && LATEST_INTENT=$(grep "^## " "$SESSION_PATH/intent.md" 2>/dev/null | tail -5 | sed 's/^## [0-9:]* - //' | tr '\n' '; ')

    if [ -n "$LATEST_FACT" ] || [ -n "$LATEST_CONTEXT" ] || [ -n "$LATEST_INTENT" ]; then
        cat >> "$MCI_FILE" << MCIEOF

--- [PC] Assembled from marker files @ $TIMESTAMP ---
Memory: ${LATEST_FACT:-No [!] markers captured}
Context: ${LATEST_CONTEXT:-No [*] markers captured}
Intent: ${LATEST_INTENT:-No [>] markers captured}
MCIEOF
        MCI_WRITTEN="true"
    fi
fi

# ============================================================================
# STEP 3: EMERGENCY FROM JSONL
# ============================================================================

if [ "$MCI_WRITTEN" = "false" ] && [ -f "$JSONL_FILE" ]; then
    MARKER_LINES=$(jq -r 'select(.type == "assistant") | .message.content // [] | if type == "array" then .[] else . end | select(.type == "text") | .text // empty' "$JSONL_FILE" 2>/dev/null | grep -E '^\[!\]|^\[\*\]|^\[>\]' | tail -20)
    LAST_USER=$(jq -r 'select(.type == "user") | .message.content // "" | if type == "array" then [.[] | select(.type == "text") | .text // empty] | join(" ") elif type == "string" then . else empty end' "$JSONL_FILE" 2>/dev/null | grep -v '^$' | tail -5 | head -c 500)
    TOOLS_USED=$(jq -r 'select(.type == "assistant") | .message.content // [] | if type == "array" then .[] else empty end | select(.type == "tool_use") | .name' "$JSONL_FILE" 2>/dev/null | sort | uniq -c | sort -rn | head -5 | tr '\n' ', ')

    E_MEMORY="[EMERGENCY] Tools: ${TOOLS_USED:-none}"
    E_CONTEXT="User discussing: $(echo "$LAST_USER" | head -c 200)"
    E_INTENT="Compact interrupted. Check compact file for conversation."

    if [ -n "$MARKER_LINES" ]; then
        M=$(echo "$MARKER_LINES" | grep '^\[!\]' | tail -1 | sed 's/^\[!\] *//')
        C=$(echo "$MARKER_LINES" | grep '^\[\*\]' | tail -1 | sed 's/^\[\*\] *//')
        I=$(echo "$MARKER_LINES" | grep '^\[>\]' | tail -1 | sed 's/^\[>\] *//')
        [ -n "$M" ] && E_MEMORY="$M"; [ -n "$C" ] && E_CONTEXT="$C"; [ -n "$I" ] && E_INTENT="$I"
    fi

    cat >> "$MCI_FILE" << MCIEOF

--- [PC] EMERGENCY from JSONL @ $TIMESTAMP ---
Memory: $E_MEMORY
Context: $E_CONTEXT
Intent: $E_INTENT
MCIEOF
fi

# ============================================================================
# STEP 4: COMPACT BACKUP
# ============================================================================

if [ -f "$JSONL_FILE" ]; then
    CONVO=$(tail -500 "$JSONL_FILE" 2>/dev/null | jq -r '
        select(.type == "user" or .type == "assistant") |
        if .type == "user" then "## USER:\n" + (if .message.content | type == "string" then .message.content elif .message.content | type == "array" then [.message.content[] | select(.type == "text") | .text // empty] | join("\n") else "..." end)
        elif .type == "assistant" then "## CLAUDE:\n" + (if .message.content | type == "array" then [.message.content[] | if .type == "text" and ((.text // "") | length > 0) then .text elif .type == "tool_use" then "[tool: " + .name + "]" else empty end] | join("\n") else "..." end)
        else empty end
    ' 2>/dev/null | tail -c 6000)

    MSG_COUNT=$(tail -500 "$JSONL_FILE" 2>/dev/null | jq -r 'select(.type == "user")' 2>/dev/null | wc -l)

    cat > "$COMPACT_FILE" << EOF
# Pre-Compact Backup - $TIMESTAMP
## MCI: $([ "$MCI_WRITTEN" = "true" ] && echo "state.md snapshot" || echo "EMERGENCY")
## state.md: $([ -f "$STATE_FILE" ] && echo "EXISTS" || echo "MISSING")
## Messages: ~$MSG_COUNT

## Recent Conversation
$CONVO
EOF
fi

# Set compact-pending marker
echo "$TIMESTAMP|$MCI_FILE|$([ "$MCI_WRITTEN" = "true" ] && echo "state-snapshot" || echo "emergency")" > "$MEMORY_BASE/compact-pending"

echo "" >> "$SESSION_PATH/memory.md"
echo "## $TIMESTAMP - PRE-COMPACT [state.md: $([ -f "$STATE_FILE" ] && echo "SNAPSHOT" || echo "MISSING")]" >> "$SESSION_PATH/memory.md"

echo "Pre-compact: state.md=$([ -f "$STATE_FILE" ] && echo "snapshot" || echo "missing")"
exit 0
