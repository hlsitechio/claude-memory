#!/bin/bash
# ============================================================================
# MCI v2 PRE-COMPACT — Snapshots FULL state.md into .mci
# PRIMARY: Read state.md content → write to .mci
# FALLBACK 1: Assemble from old marker files (backward compat)
# FALLBACK 2: Extract from JSONL (emergency)
# ============================================================================

MEMORY_BASE="/path/to/workspace"

# Cloud sync bridges
SYNC_BRIDGE="/opt/claude-memory-sync/hooks/sync-bridge.sh"
[ -f "$SYNC_BRIDGE" ] && source "$SYNC_BRIDGE"
SESSION_DATE_ISO=$(date +%Y-%m-%d)
SESSION_DATE_LEGACY=$(date +%m-%d-%Y)
TIMESTAMP=$(date +%H:%M:%S)
# CLAUDE_MEM_API removed — replaced by claude-memory-sync
CLAUDE_PROJECT_DIR="$MEMORY_BASE/.claude/projects/$(basename "$MEMORY_BASE")"
CURRENT_SESSION_FILE="$MEMORY_BASE/.claude-memory/current-session"

# ============================================================================
# RESOLVE SESSION PATH
# ============================================================================

SESSION_PATH=""

# Try .claude-memory first
if [ -f "$CURRENT_SESSION_FILE" ]; then
    PLUGIN_SESSION=$(cat "$CURRENT_SESSION_FILE" 2>/dev/null)
    if [ -n "$PLUGIN_SESSION" ] && [ -d "$PLUGIN_SESSION" ]; then
        SESSION_PATH="$PLUGIN_SESSION"
    fi
fi

# Fallback to memory_sessions
if [ -z "$SESSION_PATH" ]; then
    SESSION_BASE="$MEMORY_BASE/memory_sessions/$SESSION_DATE_LEGACY"
    SESSION_PATH=$(ls -d "$SESSION_BASE"/session-* 2>/dev/null | sort -V | tail -1)
fi

if [ -z "$SESSION_PATH" ]; then
    echo "Pre-compact: No session path found"
    exit 0
fi

MCI_FILE="$SESSION_PATH/memory.mci"
STATE_FILE="$SESSION_PATH/state.md"
COMPACT_FILE="$SESSION_PATH/compact-$TIMESTAMP.md"
JSONL_FILE=$(ls -t "$CLAUDE_PROJECT_DIR"/*.jsonl 2>/dev/null | head -1)

# ============================================================================
# STEP 0: CHECK DOCTOR MCI (AI-curated recovery — highest fidelity)
# If doctor agent is running, its doctor-mci.md is the richest recovery source.
# We don't modify it — just record its status for post-compact recovery.
# ============================================================================

DOCTOR_MCI_FILE="$SESSION_PATH/doctor-mci.md"
DOCTOR_MCI_STATUS="NOT_FOUND"
DOCTOR_MCI_AGE="N/A"

if [ -f "$DOCTOR_MCI_FILE" ]; then
    D_MTIME=$(stat -c %Y "$DOCTOR_MCI_FILE" 2>/dev/null || echo 0)
    D_NOW=$(date +%s)
    DOCTOR_MCI_AGE=$(( (D_NOW - D_MTIME) / 60 ))
    D_SIZE=$(wc -c < "$DOCTOR_MCI_FILE" 2>/dev/null || echo 0)

    if [ "$D_SIZE" -gt 100 ]; then
        if [ "$DOCTOR_MCI_AGE" -lt 30 ]; then
            DOCTOR_MCI_STATUS="FRESH (${DOCTOR_MCI_AGE}min, ${D_SIZE}b)"
        elif [ "$DOCTOR_MCI_AGE" -lt 60 ]; then
            DOCTOR_MCI_STATUS="STALE (${DOCTOR_MCI_AGE}min, ${D_SIZE}b)"
        else
            DOCTOR_MCI_STATUS="OLD (${DOCTOR_MCI_AGE}min, ${D_SIZE}b)"
        fi
    else
        DOCTOR_MCI_STATUS="EMPTY"
    fi
fi

# ============================================================================
# STEP 1: SNAPSHOT state.md INTO .mci (PRIMARY — v2 approach)
# Read the FULL state.md content and write it as .mci entry
# ============================================================================

MCI_WRITTEN="false"

if [ -f "$STATE_FILE" ]; then
    STATE_SIZE=$(wc -c < "$STATE_FILE" 2>/dev/null || echo 0)

    if [ "$STATE_SIZE" -gt 200 ]; then
        # state.md has real content — extract ALL sections with generous limits
        GOAL=$(sed -n '/^## Goal/,/^## /{ /^## Goal/d; /^## /d; p; }' "$STATE_FILE" 2>/dev/null | head -c 3000 | sed '/^$/d' | head -40)
        PROGRESS=$(sed -n '/^## Progress/,/^## /{ /^## Progress/d; /^## /d; p; }' "$STATE_FILE" 2>/dev/null | head -c 4000 | head -60)
        FINDINGS=$(sed -n '/^## Findings/,/^## /{ /^## Findings/d; /^## /d; p; }' "$STATE_FILE" 2>/dev/null | head -c 4000 | head -60)
        KEY_URLS=$(sed -n '/^## Key URLs/,/^## /{ /^## Key URLs/d; /^## /d; p; }' "$STATE_FILE" 2>/dev/null | head -c 1500 | head -20)
        KEY_CONFIGS=$(sed -n '/^## Key Configs/,/^## /{ /^## Key Configs/d; /^## /d; p; }' "$STATE_FILE" 2>/dev/null | head -c 1500 | head -20)

        # Build comprehensive .mci entry — capture everything worth recovering
        MCI_ENTRY="
--- [PC] state.md Snapshot @ $TIMESTAMP ---
Memory: GOAL: ${GOAL:-No goal set}
Context: PROGRESS: ${PROGRESS:-No progress tracked}
Intent: FINDINGS: ${FINDINGS:-No findings yet}"

        # Append optional sections if they exist
        [ -n "$KEY_URLS" ] && MCI_ENTRY="${MCI_ENTRY}
URLs: ${KEY_URLS}"
        [ -n "$KEY_CONFIGS" ] && MCI_ENTRY="${MCI_ENTRY}
Configs: ${KEY_CONFIGS}"

        echo "$MCI_ENTRY" >> "$MCI_FILE"
        MCI_WRITTEN="true"

        # ROTATION: Keep only last 10 entries to prevent .mci bloat
        # This prevents the feedback loop: bloated .mci → less context → faster compact → more bloat
        MCI_ENTRIES=$(grep -c '^--- \[' "$MCI_FILE" 2>/dev/null || echo 0)
        if [ "$MCI_ENTRIES" -gt 10 ]; then
            # Pure bash .mci rotation — keep last 10 entries (was python3, saves 300-500ms)
            # Find line number of 10th-from-last entry separator
            TOTAL_SEPS=$(grep -cn '^--- \[' "$MCI_FILE" 2>/dev/null || echo 0)
            KEEP_FROM=$((TOTAL_SEPS - 10 + 1))
            if [ "$KEEP_FROM" -gt 0 ]; then
                START_LINE=$(grep -n '^--- \[' "$MCI_FILE" 2>/dev/null | sed -n "${KEEP_FROM}p" | cut -d: -f1)
                if [ -n "$START_LINE" ]; then
                    tail -n "+${START_LINE}" "$MCI_FILE" > "${MCI_FILE}.tmp" && mv "${MCI_FILE}.tmp" "$MCI_FILE"
                fi
            fi
        fi
    fi
fi

# ============================================================================
# STEP 2: FALLBACK — Assemble from old marker files (backward compat)
# ============================================================================

if [ "$MCI_WRITTEN" = "false" ]; then
    FACTS_FILE="$SESSION_PATH/facts.md"
    CONTEXT_FILE="$SESSION_PATH/context.md"
    INTENT_FILE="$SESSION_PATH/intent.md"

    # Read ALL entries from each file (not just last line!)
    LATEST_FACTS=""
    LATEST_CONTEXT=""
    LATEST_INTENT=""

    if [ -f "$FACTS_FILE" ]; then
        LATEST_FACTS=$(grep "^## " "$FACTS_FILE" 2>/dev/null | tail -5 | sed 's/^## [0-9:]* - //' | tr '\n' '; ')
    fi
    if [ -f "$CONTEXT_FILE" ]; then
        LATEST_CONTEXT=$(grep "^## " "$CONTEXT_FILE" 2>/dev/null | tail -5 | sed 's/^## [0-9:]* - //' | tr '\n' '; ')
    fi
    if [ -f "$INTENT_FILE" ]; then
        LATEST_INTENT=$(grep "^## " "$INTENT_FILE" 2>/dev/null | tail -5 | sed 's/^## [0-9:]* - //' | tr '\n' '; ')
    fi

    if [ -n "$LATEST_FACTS" ] || [ -n "$LATEST_CONTEXT" ] || [ -n "$LATEST_INTENT" ]; then
        cat >> "$MCI_FILE" << MCIEOF

--- [PC] Assembled from marker files @ $TIMESTAMP ---
Memory: ${LATEST_FACTS:-No [!] markers captured}
Context: ${LATEST_CONTEXT:-No [*] markers captured}
Intent: ${LATEST_INTENT:-No [>] markers captured}
MCIEOF
        MCI_WRITTEN="true"
    fi
fi

# ============================================================================
# STEP 3: EMERGENCY — Extract from JSONL
# ============================================================================

if [ "$MCI_WRITTEN" = "false" ] && [ -f "$JSONL_FILE" ]; then
    # Extract Claude's text responses for markers
    MARKER_LINES=$(jq -r '
        select(.type == "assistant") |
        .message.content // [] |
        if type == "array" then .[] else . end |
        select(.type == "text") |
        .text // empty
    ' "$JSONL_FILE" 2>/dev/null | grep -E '^\[!\]|^\[\*\]|^\[>\]' | tail -20)

    # Last user messages
    LAST_USER=$(jq -r '
        select(.type == "user") |
        .message.content // "" |
        if type == "array" then
            [.[] | select(.type == "text") | .text // empty] | join(" ")
        elif type == "string" then .
        else empty end
    ' "$JSONL_FILE" 2>/dev/null | grep -v '^$' | tail -5 | head -c 500)

    # Last Claude responses
    LAST_CLAUDE=$(jq -r '
        select(.type == "assistant") |
        .message.content // [] |
        if type == "array" then
            [.[] | select(.type == "text" and ((.text // "") | length > 0)) | .text] | join(" ")
        else empty end
    ' "$JSONL_FILE" 2>/dev/null | grep -v '^$' | tail -3 | head -c 500)

    # Tool usage
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
        select(.type == "tool_use" and (.name == "Write" or .name == "Edit" or .name == "Read")) |
        .input.file_path // empty
    ' "$JSONL_FILE" 2>/dev/null | sort -u | tail -10 | tr '\n' ', ')

    # Build emergency entry
    E_MEMORY="[EMERGENCY] No state.md, no markers. Tools: ${TOOLS_USED:-none}. Files: ${FILES_TOUCHED:-none}"
    E_CONTEXT="User discussing: $(echo "$LAST_USER" | head -c 300)"
    E_INTENT="Compact interrupted. Check compact-$TIMESTAMP.md for raw conversation."

    # Overlay JSONL markers if found
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
# STEP 4: CREATE COMPACT BACKUP (raw conversation)
# ============================================================================

if [ -f "$JSONL_FILE" ]; then
    CONVO_EXTRACT=$(tail -500 "$JSONL_FILE" 2>/dev/null | jq -r '
        select(.type == "user" or .type == "assistant") |
        if .type == "user" then
            "## USER:\n" + (
                if .message.content | type == "string" then .message.content
                elif .message.content | type == "array" then
                    [.message.content[] |
                        if .type == "text" then .text // empty
                        elif .type == "tool_result" then "[result]"
                        else empty end
                    ] | join("\n")
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

    TOOL_SUMMARY=$(tail -500 "$JSONL_FILE" 2>/dev/null | jq -r '
        select(.type == "assistant") |
        .message.content // [] |
        if type == "array" then .[] else empty end |
        select(.type == "tool_use") | .name
    ' 2>/dev/null | sort | uniq -c | sort -rn | head -10)

    MSG_COUNT=$(tail -500 "$JSONL_FILE" 2>/dev/null | jq -r 'select(.type == "user")' 2>/dev/null | wc -l)

    cat > "$COMPACT_FILE" << EOF
# Pre-Compact State - $TIMESTAMP
## MCI: $([ "$MCI_WRITTEN" = "true" ] && echo "state.md snapshot" || echo "EMERGENCY")
## state.md: $([ -f "$STATE_FILE" ] && echo "EXISTS ($(wc -c < "$STATE_FILE" 2>/dev/null) bytes)" || echo "MISSING")
## doctor-mci.md: $DOCTOR_MCI_STATUS
## MCI Path: $MCI_FILE
## Messages: ~$MSG_COUNT
## Tools: $TOOL_SUMMARY

## Recent Conversation
$CONVO_EXTRACT
EOF
fi

# Update session memory.md
cat >> "$SESSION_PATH/memory.md" << EOF

---
## $TIMESTAMP - PRE-COMPACT [state.md: $([ -f "$STATE_FILE" ] && echo "SNAPSHOT" || echo "MISSING") | MCI: $([ "$MCI_WRITTEN" = "true" ] && echo "WRITTEN" || echo "EMERGENCY")]
Backup: $COMPACT_FILE
EOF

# ============================================================================
# STEP 6: SET COMPACT-PENDING MARKER
# ============================================================================

MARKER_DIR="/path/to/workspace/tmp"
mkdir -p "$MARKER_DIR"
echo "$TIMESTAMP|$MCI_FILE|$([ "$MCI_WRITTEN" = "true" ] && echo "state-snapshot" || echo "emergency")|$SESSION_PATH|doctor:$DOCTOR_MCI_STATUS" > "$MARKER_DIR/mci-compact-pending"

# ============================================================================
# STEP 7: CLOUD SYNC — Push state.md to sync server
# ============================================================================

if type sync_push &>/dev/null && [ -f "$STATE_FILE" ]; then
    export CLAUDE_MEMORY_SYNC_SOURCE="claude-code"
    sync_push "$STATE_FILE"
fi


# ============================================================================
# STEP 8: MEMORY-ENGINE AUTO-INGEST — Capture session data before compact
# ============================================================================

INGEST_SCRIPT="/path/to/workspace/infrastructure/memory-engine/auto_ingest.py"
if [ -f "$INGEST_SCRIPT" ]; then
    python3 "$INGEST_SCRIPT" latest &>/dev/null &
fi

echo "Pre-compact: state.md=$([ -f "$STATE_FILE" ] && echo "snapshot" || echo "missing") | doctor-mci=$DOCTOR_MCI_STATUS | $COMPACT_FILE"
exit 0
