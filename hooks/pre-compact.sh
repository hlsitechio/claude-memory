#!/bin/bash
# ============================================================================
# PRE-COMPACT - Safety net before auto-compact fires
# 3-tier fallback: .mci valid → assemble from markers → emergency from JSONL
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
COMPACT_FILE="$SESSION_PATH/compact-$TIMESTAMP.md"

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
# STEP 1: CHECK IF .MCI IS ALREADY VALID
# ============================================================================

MCI_VALID="false"
if [ -f "$MCI_FILE" ]; then
    HAS_MEMORY=$(grep -c "^Memory:" "$MCI_FILE" 2>/dev/null || echo 0)
    HAS_CONTEXT=$(grep -c "^Context:" "$MCI_FILE" 2>/dev/null || echo 0)
    HAS_INTENT=$(grep -c "^Intent:" "$MCI_FILE" 2>/dev/null || echo 0)

    if [ "$HAS_MEMORY" -gt 0 ] && [ "$HAS_CONTEXT" -gt 0 ] && [ "$HAS_INTENT" -gt 0 ]; then
        MCI_VALID="true"
    fi
fi

# ============================================================================
# STEP 2: ASSEMBLE FROM MARKER FILES (primary fallback)
# ============================================================================

ASSEMBLED="false"

if [ "$MCI_VALID" = "false" ]; then
    LATEST_FACT=""
    LATEST_CONTEXT=""
    LATEST_INTENT=""

    [ -f "$SESSION_PATH/facts.md" ] && LATEST_FACT=$(grep "^## " "$SESSION_PATH/facts.md" 2>/dev/null | tail -1 | sed 's/^## [0-9:]* - //')
    [ -f "$SESSION_PATH/context.md" ] && LATEST_CONTEXT=$(grep "^## " "$SESSION_PATH/context.md" 2>/dev/null | tail -1 | sed 's/^## [0-9:]* - //')
    [ -f "$SESSION_PATH/intent.md" ] && LATEST_INTENT=$(grep "^## " "$SESSION_PATH/intent.md" 2>/dev/null | tail -1 | sed 's/^## [0-9:]* - //')

    if [ -n "$LATEST_FACT" ] || [ -n "$LATEST_CONTEXT" ] || [ -n "$LATEST_INTENT" ]; then
        ASSEMBLED="true"
        cat >> "$MCI_FILE" << MCIEOF

--- [PC] Auto-Assembled from marker files @ $TIMESTAMP ---
Memory: ${LATEST_FACT:-No [!] markers captured this session}
Context: ${LATEST_CONTEXT:-No [*] markers captured this session}
Intent: ${LATEST_INTENT:-No [>] markers captured this session}
MCIEOF
    fi
fi

# ============================================================================
# STEP 3: EMERGENCY FALLBACK FROM JSONL (tertiary)
# ============================================================================

if [ "$MCI_VALID" = "false" ] && [ "$ASSEMBLED" = "false" ] && [ -f "$JSONL_FILE" ]; then
    # Extract markers from Claude's responses
    MARKER_LINES=$(jq -r '
        select(.type == "assistant") |
        .message.content // [] |
        if type == "array" then .[] else . end |
        select(.type == "text") | .text // empty
    ' "$JSONL_FILE" 2>/dev/null | grep -E '^\[!\]|^\[\*\]|^\[>\]' | tail -20)

    # Extract last user messages
    LAST_USER=$(jq -r '
        select(.type == "user") |
        .message.content // "" |
        if type == "array" then
            [.[] | select(.type == "text") | .text // empty] | join(" ")
        elif type == "string" then .
        else empty end
    ' "$JSONL_FILE" 2>/dev/null | grep -v '^$' | tail -5 | head -c 500)

    # Tool usage summary
    TOOLS_USED=$(jq -r '
        select(.type == "assistant") |
        .message.content // [] |
        if type == "array" then .[] else empty end |
        select(.type == "tool_use") | .name
    ' "$JSONL_FILE" 2>/dev/null | sort | uniq -c | sort -rn | head -5 | tr '\n' ', ')

    # Files touched
    FILES_TOUCHED=$(jq -r '
        select(.type == "assistant") |
        .message.content // [] |
        if type == "array" then .[] else empty end |
        select(.type == "tool_use" and (.name == "Write" or .name == "Edit")) |
        .input.file_path // empty
    ' "$JSONL_FILE" 2>/dev/null | sort -u | tail -10 | tr '\n' ', ')

    # Build emergency entry
    E_MEMORY="[EMERGENCY] Tools: ${TOOLS_USED:-none}. Files: ${FILES_TOUCHED:-none}"
    E_CONTEXT="User discussing: $(echo "$LAST_USER" | head -c 200)"
    E_INTENT="Session interrupted by compact. Review compact-$TIMESTAMP.md for raw conversation."

    # Override with marker data if found
    if [ -n "$MARKER_LINES" ]; then
        M=$(echo "$MARKER_LINES" | grep '^\[!\]' | tail -1 | sed 's/^\[!\] *//')
        C=$(echo "$MARKER_LINES" | grep '^\[\*\]' | tail -1 | sed 's/^\[\*\] *//')
        I=$(echo "$MARKER_LINES" | grep '^\[>\]' | tail -1 | sed 's/^\[>\] *//')
        [ -n "$M" ] && E_MEMORY="$M"
        [ -n "$C" ] && E_CONTEXT="$C"
        [ -n "$I" ] && E_INTENT="$I"
    fi

    cat >> "$MCI_FILE" << MCIEOF

--- [PC] EMERGENCY from JSONL @ $TIMESTAMP ---
Memory: $E_MEMORY
Context: $E_CONTEXT
Intent: $E_INTENT
MCIEOF
fi

# ============================================================================
# STEP 4: CREATE COMPACT BACKUP
# ============================================================================

if [ -f "$JSONL_FILE" ]; then
    CONVO=$(tail -500 "$JSONL_FILE" 2>/dev/null | jq -r '
        select(.type == "user" or .type == "assistant") |
        if .type == "user" then
            "## USER:\n" + (
                if .message.content | type == "string" then .message.content
                elif .message.content | type == "array" then
                    [.message.content[] | select(.type == "text") | .text // empty] | join("\n")
                else "..." end
            )
        elif .type == "assistant" then
            "## CLAUDE:\n" + (
                if .message.content | type == "array" then
                    [.message.content[] |
                        if .type == "text" and ((.text // "") | length > 0) then .text
                        elif .type == "tool_use" then "[tool: " + .name + "]"
                        else empty end
                    ] | join("\n")
                else "..." end
            )
        else empty end
    ' 2>/dev/null | tail -c 6000)

    MSG_COUNT=$(tail -500 "$JSONL_FILE" 2>/dev/null | jq -r 'select(.type == "user")' 2>/dev/null | wc -l)

    cat > "$COMPACT_FILE" << EOF
# Pre-Compact Backup - $TIMESTAMP
## MCI Status: $([ "$MCI_VALID" = "true" ] && echo "VALID" || echo "AUTO-GENERATED")
## Messages: ~$MSG_COUNT

## Recent Conversation
$CONVO
EOF
fi

# ============================================================================
# STEP 5: SET COMPACT-PENDING MARKER
# ============================================================================

echo "$TIMESTAMP|$MCI_FILE|$([ "$MCI_VALID" = "true" ] && echo "valid" || echo "emergency")" > "$MEMORY_BASE/compact-pending"

# Update session log
echo "" >> "$SESSION_PATH/memory.md"
echo "## $TIMESTAMP - PRE-COMPACT [MCI: $([ "$MCI_VALID" = "true" ] && echo "SAVED" || echo "EMERGENCY")]" >> "$SESSION_PATH/memory.md"

echo "Pre-compact: MCI=$([ "$MCI_VALID" = "true" ] && echo "valid" || echo "emergency")"
exit 0
