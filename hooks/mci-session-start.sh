#!/bin/bash
# ============================================================================
# MCI v2 SESSION START — state.md based memory system
# Creates: state.md (living state) + memory.md (session log)
# Loads: Identity (SOUL+USER) + Full_context + .mci
# Post-compact: Tells Claude to READ state.md for full recovery
# ============================================================================

MEMORY_BASE="/path/to/workspace"
SESSION_DATE_ISO=$(date +%Y-%m-%d)
SESSION_DATE_LEGACY=$(date +%m-%d-%Y)
SESSION_TIME=$(date +%H:%M)
CURRENT_SESSION_FILE="$MEMORY_BASE/.claude-memory/current-session"

# ============================================================================
# VPN CHECK (optional — set MEMORY_ENGINE_VPN_CHECK=1 to enable)
# ============================================================================
VPN_OK="true"
VPN_LINE="[i] VPN: check disabled (set MEMORY_ENGINE_VPN_CHECK=1 to enable)"

if [ "${MEMORY_ENGINE_VPN_CHECK:-0}" = "1" ]; then
    VPN_CMD="${MEMORY_ENGINE_VPN_CMD:-nordvpn status}"
    VPN_RAW=$(timeout 3 $VPN_CMD 2>/dev/null || echo "Status: Disconnected")
    if echo "$VPN_RAW" | grep -qiE "Status:[[:space:]]*Connected" && ! echo "$VPN_RAW" | grep -qi "Disconnected"; then
        VPN_CITY=$(echo "$VPN_RAW" | grep -i "city" | cut -d: -f2 | xargs 2>/dev/null || echo "?")
        VPN_IP=$(echo "$VPN_RAW" | grep -i "server ip" | cut -d: -f2 | xargs 2>/dev/null || echo "?")
        VPN_LINE="[+] VPN: ON ($VPN_CITY - $VPN_IP)"
        VPN_OK="true"
    else
        VPN_LINE="[!] VPN: OFF — CONNECT BEFORE PROCEEDING"
        VPN_OK="false"
    fi
fi

# ============================================================================
# MOUNT CHECK (drive access critical)
# ============================================================================
if mount | grep -q /path/to/workspace; then
    MOUNT_LINE="[+] BOUNTY: Mounted"
    MOUNT_OK="true"
else
    MOUNT_LINE="[!] BOUNTY: NOT MOUNTED"
    MOUNT_OK="false"
fi

# ============================================================================
# HOOK HEALTH CHECK
# ============================================================================
HOOKS_OK="true"
HOOKS_ISSUES=""

HOOK_SCRIPTS=(
    "/home/YOUR_USER/.claude/scripts/mci-session-start.sh:SessionStart"
    "/home/YOUR_USER/.claude/scripts/mci-prompt-capture.sh:UserPromptSubmit"
    "/home/YOUR_USER/.claude/scripts/mci-pre-compact.sh:PreCompact"
    "/home/YOUR_USER/.claude/scripts/mci-stop.sh:Stop"
    "/home/YOUR_USER/.device-vault/bin/device-vault:DeviceVault"
)

for entry in "${HOOK_SCRIPTS[@]}"; do
    SCRIPT="${entry%%:*}"
    LABEL="${entry##*:}"
    if [ ! -f "$SCRIPT" ]; then
        HOOKS_OK="false"
        HOOKS_ISSUES="${HOOKS_ISSUES}MISSING:${LABEL} "
    elif [ ! -x "$SCRIPT" ]; then
        HOOKS_ISSUES="${HOOKS_ISSUES}NOEXEC:${LABEL} "
    fi
done

SETTINGS_FILE="$MEMORY_BASE/.claude/settings.json"
if [ -f "$SETTINGS_FILE" ]; then
    for EVENT in SessionStart UserPromptSubmit PreCompact Stop; do
        if ! grep -q "\"$EVENT\"" "$SETTINGS_FILE" 2>/dev/null; then
            HOOKS_OK="false"
            HOOKS_ISSUES="${HOOKS_ISSUES}NOEVENT:${EVENT} "
        fi
    done
fi

if [ "$HOOKS_OK" = "true" ] && [ -z "$HOOKS_ISSUES" ]; then
    HOOKS_LINE="[+] HOOKS: All 5 scripts OK, 4 events configured"
else
    HOOKS_LINE="[!] HOOKS: ISSUES — $HOOKS_ISSUES"
fi

# ============================================================================
# SESSION PATH RESOLUTION
# Prefer .claude-memory/current-session, fallback to memory_sessions
# ============================================================================

SESSION_PATH=""
SESSION_NUM=""
SESSION_STATUS=""
FORCE_NEW="${CLAUDE_FORCE_NEW_SESSION:-0}"

if [ "$MOUNT_OK" = "true" ]; then
    SESSION_BASE_CM="$MEMORY_BASE/.claude-memory/sessions/$SESSION_DATE_ISO"

    # ── FORCE NEW SESSION (desktop launcher / --new flag) ──
    if [ "$FORCE_NEW" = "1" ]; then
        mkdir -p "$SESSION_BASE_CM"
        EXISTING_CM=$(ls -d "$SESSION_BASE_CM"/session-* 2>/dev/null | wc -l)
        SESSION_NUM=$((EXISTING_CM + 1))
        SESSION_PATH="$SESSION_BASE_CM/session-$SESSION_NUM"
        mkdir -p "$SESSION_PATH"
        # Update current-session pointer
        echo "$SESSION_PATH" > "$CURRENT_SESSION_FILE"
        SESSION_STATUS="NEW"

    # ── Try .claude-memory first (plugin-managed sessions) ──
    elif [ -f "$CURRENT_SESSION_FILE" ]; then
        PLUGIN_SESSION=$(cat "$CURRENT_SESSION_FILE" 2>/dev/null)
        if [ -n "$PLUGIN_SESSION" ] && [ -d "$PLUGIN_SESSION" ]; then
            SESSION_PATH="$PLUGIN_SESSION"
            SESSION_NUM=$(basename "$SESSION_PATH" | sed 's/session-//')
            # Check if this is a fresh or resumed session
            if [ -f "$SESSION_PATH/state.md" ] || [ -f "$SESSION_PATH/memory.md" ]; then
                LAST_MOD=$(stat -c %Y "$SESSION_PATH" 2>/dev/null || echo 0)
                NOW=$(date +%s)
                DIFF=$((NOW - LAST_MOD))
                if [ $DIFF -lt 1800 ]; then
                    SESSION_STATUS="RESUMED"
                else
                    SESSION_STATUS="NEW"
                fi
            else
                SESSION_STATUS="NEW"
            fi
        fi
    fi

    # Fallback to memory_sessions (legacy)
    if [ -z "$SESSION_PATH" ]; then
        SESSION_BASE="$MEMORY_BASE/memory_sessions/$SESSION_DATE_LEGACY"
        mkdir -p "$SESSION_BASE"
        LAST_SESSION=$(ls -d "$SESSION_BASE"/session-* 2>/dev/null | sort -V | tail -1)

        if [ -n "$LAST_SESSION" ] && [ -f "$LAST_SESSION/memory.md" ]; then
            LAST_MOD=$(stat -c %Y "$LAST_SESSION/memory.md" 2>/dev/null || echo 0)
            NOW=$(date +%s)
            DIFF=$((NOW - LAST_MOD))
            if [ $DIFF -lt 1800 ]; then
                SESSION_PATH="$LAST_SESSION"
                SESSION_NUM=$(basename "$LAST_SESSION" | sed 's/session-//')
                SESSION_STATUS="RESUMED"
            else
                EXISTING=$(ls -d "$SESSION_BASE"/session-* 2>/dev/null | wc -l)
                SESSION_NUM=$((EXISTING + 1))
                SESSION_PATH="$SESSION_BASE/session-$SESSION_NUM"
                mkdir -p "$SESSION_PATH"
                SESSION_STATUS="NEW"
            fi
        else
            SESSION_NUM=1
            SESSION_PATH="$SESSION_BASE/session-$SESSION_NUM"
            mkdir -p "$SESSION_PATH"
            SESSION_STATUS="NEW"
        fi
    fi

    # ========================================================================
    # CREATE SESSION FILES (state.md + memory.md)
    # ========================================================================
    if [ "$SESSION_STATUS" = "NEW" ] || [ ! -f "$SESSION_PATH/state.md" ]; then
        # Create state.md — the living state file
        if [ ! -f "$SESSION_PATH/state.md" ]; then
            # ATOMIC WRITE: tmp → mv (crash-safe)
            cat > "$SESSION_PATH/state.md.tmp" << 'STATEEOF'
# Session State
> Last updated: --:--

## Goal
(Set your mission here. What target? What scope? What are we hunting?)

## Progress
- [ ] Waiting for direction

## Findings
(none yet)
STATEEOF
            mv "$SESSION_PATH/state.md.tmp" "$SESSION_PATH/state.md"
        fi

        # Create memory.md — session log (atomic)
        if [ ! -f "$SESSION_PATH/memory.md" ]; then
            cat > "$SESSION_PATH/memory.md.tmp" << EOF
# Session $SESSION_NUM - Started $SESSION_TIME
---
EOF
            mv "$SESSION_PATH/memory.md.tmp" "$SESSION_PATH/memory.md"
        fi

        # Backward compat: create old marker files if missing (for older hooks/plugins)
        [ ! -f "$SESSION_PATH/facts.md" ] && echo "# Facts - Session $SESSION_NUM" > "$SESSION_PATH/facts.md"
        [ ! -f "$SESSION_PATH/context.md" ] && echo "# Context - Session $SESSION_NUM" > "$SESSION_PATH/context.md"
        [ ! -f "$SESSION_PATH/intent.md" ] && echo "# Intent - Session $SESSION_NUM" > "$SESSION_PATH/intent.md"

    fi

    SESSION_LINE="[+] SESSION: #$SESSION_NUM ($SESSION_STATUS)"
else
    SESSION_NUM="0"
    SESSION_PATH=""
    SESSION_LINE="[!] SESSION: Cannot create"
fi

# ============================================================================
# POST-COMPACT + CRASH DETECTION
# ============================================================================
COMPACT_MARKER="/path/to/workspace/tmp/mci-compact-pending"
IS_POST_COMPACT="false"
IS_CRASH_RECOVERY="false"
COMPACT_INFO=""

if [ -f "$COMPACT_MARKER" ]; then
    IS_POST_COMPACT="true"
    COMPACT_INFO=$(cat "$COMPACT_MARKER" 2>/dev/null)
    rm -f "$COMPACT_MARKER"
elif [ "$SESSION_STATUS" = "RESUMED" ] && [ -n "$SESSION_PATH" ] && [ -f "$SESSION_PATH/state.md" ]; then
    # No compact marker but session is resumed with real state.md
    # This means Claude crashed/was killed without PreCompact firing
    STATE_SIZE_CHECK=$(wc -c < "$SESSION_PATH/state.md" 2>/dev/null || echo 0)
    if [ "$STATE_SIZE_CHECK" -gt 200 ]; then
        IS_CRASH_RECOVERY="true"
        COMPACT_INFO="CRASH — no PreCompact hook fired. state.md has ${STATE_SIZE_CHECK}b of context."
    fi
fi

# ============================================================================
# CONTEXT LOADING
# ============================================================================

LOADED_CONTEXT=""

# --- IDENTITY: SOUL.md ---
if [ -f "$MEMORY_BASE/SOUL.md" ]; then
    SOUL=$(cat "$MEMORY_BASE/SOUL.md" 2>/dev/null | head -c 1000)
    LOADED_CONTEXT="${LOADED_CONTEXT}

=== SOUL (Identity) ===
${SOUL}"
fi

# --- IDENTITY: USER.md ---
if [ -f "$MEMORY_BASE/USER.md" ]; then
    USER_PREFS=$(cat "$MEMORY_BASE/USER.md" 2>/dev/null | head -c 800)
    LOADED_CONTEXT="${LOADED_CONTEXT}

=== USER (Preferences) ===
${USER_PREFS}"
fi

# --- FULL CONTEXT — NOT pre-loaded (29KB kills context window) ---
# Full_context.md is a DRAWER: read on demand with Read tool, not injected at startup.
# This saves ~29KB of context per session/compact cycle.
FULL_CTX_PATH="$MEMORY_BASE/memory/Full_context.md"
FULL_CTX_LOADED="false"
if [ -f "$FULL_CTX_PATH" ]; then
    FULL_CTX_LOADED="true"
fi

# --- DOCTOR MCI: AI-curated recovery document (highest fidelity) ---
DOCTOR_MCI_LOADED="false"
DOCTOR_MCI_CONTENT=""

if [ -n "$SESSION_PATH" ] && [ -f "$SESSION_PATH/doctor-mci.md" ]; then
    DOCTOR_AGE=0
    DOCTOR_MTIME=$(stat -c %Y "$SESSION_PATH/doctor-mci.md" 2>/dev/null || echo 0)
    NOW_TS=$(date +%s)
    DOCTOR_AGE=$(( (NOW_TS - DOCTOR_MTIME) / 60 ))

    # Only load if <60 min old (stale doctor notes are less trustworthy)
    if [ "$DOCTOR_AGE" -lt 60 ]; then
        DOCTOR_MCI_CONTENT=$(cat "$SESSION_PATH/doctor-mci.md" 2>/dev/null | head -c 3000)
        if [ -n "$DOCTOR_MCI_CONTENT" ]; then
            DOCTOR_MCI_LOADED="true"
            LOADED_CONTEXT="${LOADED_CONTEXT}

=== DOCTOR MCI (AI-curated recovery — ${DOCTOR_AGE}min old) ===
${DOCTOR_MCI_CONTENT}"
        fi
    fi
fi

# --- DOCTOR VITALS: Background agent health status ---
if [ -n "$SESSION_PATH" ] && [ -f "$SESSION_PATH/vitals.md" ]; then
    VITALS_STATUS=$(head -5 "$SESSION_PATH/vitals.md" 2>/dev/null | grep -oP 'Status: \K.*' | head -1)
    if [ -n "$VITALS_STATUS" ]; then
        LOADED_CONTEXT="${LOADED_CONTEXT}

=== DOCTOR STATUS ===
[i] Doctor Agent vitals: $VITALS_STATUS (see $SESSION_PATH/vitals.md)"
    fi
fi

# --- DOCTOR SPAWN REQUEST ---
# Signal Claude to spawn a doctor agent if one isn't already running
DOCTOR_ID_FILE="$SESSION_PATH/doctor.id"
DOCTOR_SPAWN_REQUEST=""
if [ ! -f "$DOCTOR_ID_FILE" ]; then
    DOCTOR_SPAWN_REQUEST="[>] DOCTOR: No background doctor agent detected. Consider spawning one for cognitive monitoring."
elif [ -f "$SESSION_PATH/vitals.md" ]; then
    VITALS_MTIME=$(stat -c %Y "$SESSION_PATH/vitals.md" 2>/dev/null || echo 0)
    VITALS_AGE=$(( (NOW_TS - VITALS_MTIME) / 60 ))
    if [ "$VITALS_AGE" -gt 30 ]; then
        DOCTOR_SPAWN_REQUEST="[!] DOCTOR: Last vitals ${VITALS_AGE}min ago — doctor may be dead. Consider respawning."
    fi
fi

# --- M/C/I: Latest .mci file (fallback to doctor-mci.md) ---
MCI_LOADED="false"
MCI_CONTENT=""

# Try current session .mci first — ONLY load LAST entry to minimize context usage
# state.md is the real brain — .mci is just a safety net for recovery
# doctor-mci.md is preferred over .mci when available
if [ -n "$SESSION_PATH" ] && [ -f "$SESSION_PATH/memory.mci" ]; then
    # Pure bash: extract LAST entry (was python3 — saves 300-500ms)
    MCI_CONTENT=$(tac "$SESSION_PATH/memory.mci" 2>/dev/null | sed '/^--- \[/q' | tac)
    if [ -n "$MCI_CONTENT" ]; then
        MCI_LOADED="true"
        MCI_TOTAL=$(grep -c '^--- \[' "$SESSION_PATH/memory.mci" 2>/dev/null || echo 0)
        LOADED_CONTEXT="${LOADED_CONTEXT}

=== SESSION .mci (${SESSION_PATH}/memory.mci) — latest of ${MCI_TOTAL} entries ===
${MCI_CONTENT}"
    fi
fi

# Fallback: check previous sessions today
if [ "$MCI_LOADED" = "false" ]; then
    # Check .claude-memory sessions
    CM_BASE="$MEMORY_BASE/.claude-memory/sessions/$SESSION_DATE_ISO"
    for SESSION_DIR in $(ls -dr "$CM_BASE"/session-* 2>/dev/null); do
        if [ -f "$SESSION_DIR/memory.mci" ]; then
            MCI_CONTENT=$(cat "$SESSION_DIR/memory.mci" 2>/dev/null)
            if [ -n "$MCI_CONTENT" ]; then
                MCI_LOADED="true"
                LOADED_CONTEXT="${LOADED_CONTEXT}

=== PREVIOUS SESSION .mci (${SESSION_DIR}/memory.mci) ===
${MCI_CONTENT}"
                break
            fi
        fi
    done
fi

# Fallback: check memory_sessions
if [ "$MCI_LOADED" = "false" ]; then
    LEGACY_BASE="$MEMORY_BASE/memory_sessions/$SESSION_DATE_LEGACY"
    for SESSION_DIR in $(ls -dr "$LEGACY_BASE"/session-* 2>/dev/null); do
        if [ -f "$SESSION_DIR/memory.mci" ]; then
            MCI_CONTENT=$(cat "$SESSION_DIR/memory.mci" 2>/dev/null)
            if [ -n "$MCI_CONTENT" ]; then
                MCI_LOADED="true"
                LOADED_CONTEXT="${LOADED_CONTEXT}

=== PREVIOUS SESSION .mci (${SESSION_DIR}/memory.mci) ===
${MCI_CONTENT}"
                break
            fi
        fi
    done
fi

# Fallback: check yesterday
if [ "$MCI_LOADED" = "false" ]; then
    YESTERDAY_ISO=$(date -d "yesterday" +%Y-%m-%d 2>/dev/null || date +%Y-%m-%d)
    YESTERDAY_LEGACY=$(date -d "yesterday" +%m-%d-%Y 2>/dev/null || date +%m-%d-%Y)
    for BASE_DIR in "$MEMORY_BASE/.claude-memory/sessions/$YESTERDAY_ISO" "$MEMORY_BASE/memory_sessions/$YESTERDAY_LEGACY"; do
        YESTERDAY_LAST=$(ls -d "$BASE_DIR"/session-* 2>/dev/null | sort -V | tail -1)
        if [ -n "$YESTERDAY_LAST" ] && [ -f "$YESTERDAY_LAST/memory.mci" ]; then
            MCI_CONTENT=$(cat "$YESTERDAY_LAST/memory.mci" 2>/dev/null)
            if [ -n "$MCI_CONTENT" ]; then
                MCI_LOADED="true"
                LOADED_CONTEXT="${LOADED_CONTEXT}

=== YESTERDAY .mci (${YESTERDAY_LAST}/memory.mci) ===
${MCI_CONTENT}"
                break
            fi
        fi
    done
fi

# --- STATE.MD STATUS ---
STATE_STATUS="EMPTY"
if [ -n "$SESSION_PATH" ] && [ -f "$SESSION_PATH/state.md" ]; then
    STATE_SIZE=$(wc -c < "$SESSION_PATH/state.md" 2>/dev/null || echo 0)
    if [ "$STATE_SIZE" -gt 200 ]; then
        STATE_STATUS="ACTIVE ($STATE_SIZE bytes)"
    else
        STATE_STATUS="TEMPLATE"
    fi
fi

# --- MEMORY ENGINE CONTEXT INJECTION ---
# Inject recent observations + session summaries (lightweight, ~1-2KB)
ME_CONTEXT=""
ME_SCRIPT="/path/to/workspace/infrastructure/memory-engine/observations.py"
if [ -f "$ME_SCRIPT" ]; then
    ME_CONTEXT=$(timeout 5 python3 "$ME_SCRIPT" context 2>/dev/null | head -c 3000)
    if [ -n "$ME_CONTEXT" ]; then
        LOADED_CONTEXT="${LOADED_CONTEXT}

=== MEMORY ENGINE (observations + summaries) ===
${ME_CONTEXT}"
    fi
fi

# --- DRAWERS INDEX ---
DRAWER_INDEX="
=== DRAWERS (read on demand, not pre-loaded) ===
- **state.md**: $SESSION_PATH/state.md ← YOUR EXTERNAL BRAIN (Read after compact!)
- **doctor-mci.md**: $SESSION_PATH/doctor-mci.md ← AI-curated recovery (if doctor is running)
- **vitals.md**: $SESSION_PATH/vitals.md ← Doctor's health dashboard
- MEMORY.md: $MEMORY_BASE/MEMORY.md (long-term knowledge, infra, discoveries)
- Topics: $MEMORY_BASE/topics/registry.json (bounty programs index)
- Session logs: $SESSION_PATH/memory.md (this session's log)
- claude-mem: MCP search tools (search, timeline, get_observations)
- Compact files: $SESSION_PATH/compact-*.md (raw conversation backups)

[i] state.md is your living state file. Read it after compact. Keep it updated as you work.
[i] doctor-mci.md has richer recovery than memory.mci — read it first after compact.
[i] Everything else is a drawer — open on demand."

LOADED_CONTEXT="${LOADED_CONTEXT}
${DRAWER_INDEX}"

# ============================================================================
# MCI v2 RULES
# ============================================================================

# MCI Rules removed — already in CLAUDE.md. Saves ~2KB per injection.
MCI_RULES=""

# ============================================================================
# BUILD OUTPUT
# ============================================================================

# Post-compact / crash recovery alert
COMPACT_ALERT=""
RECOVERY_TYPE="none"

if [ "$IS_POST_COMPACT" = "true" ] || [ "$IS_CRASH_RECOVERY" = "true" ]; then
    # Determine recovery type label
    if [ "$IS_POST_COMPACT" = "true" ]; then
        RECOVERY_TYPE="POST-COMPACT"
        RECOVERY_REASON="Auto-compact just fired. You lost conversation context."
    else
        RECOVERY_TYPE="CRASH-RECOVERY"
        RECOVERY_REASON="Session crashed or was killed without clean shutdown. PreCompact never fired. .mci may be stale — state.md is your best source."
    fi

    # Determine best recovery source
    RECOVERY_SOURCE="state.md"
    RECOVERY_EXTRA=""
    if [ -f "$SESSION_PATH/doctor-mci.md" ]; then
        D_MTIME=$(stat -c %Y "$SESSION_PATH/doctor-mci.md" 2>/dev/null || echo 0)
        D_AGE=$(( ($(date +%s) - D_MTIME) / 60 ))
        if [ "$D_AGE" -lt 60 ]; then
            RECOVERY_SOURCE="doctor-mci.md (AI-curated, ${D_AGE}min old)"
            RECOVERY_EXTRA="
[+] DOCTOR MCI AVAILABLE — richer recovery than state.md alone
1. Read $SESSION_PATH/doctor-mci.md FIRST — has narrative, tool state, identity
2. Then read $SESSION_PATH/state.md — has structured Goal/Progress/Findings
3. Together = ~90%+ recovery fidelity"
        fi
    fi

    # === INJECT state.md PREVIEW directly into context ===
    # So Claude has immediate context without needing a Read tool call
    STATE_PREVIEW=""
    if [ -n "$SESSION_PATH" ] && [ -f "$SESSION_PATH/state.md" ]; then
        STATE_PREVIEW_SIZE=$(wc -c < "$SESSION_PATH/state.md" 2>/dev/null || echo 0)
        if [ "$STATE_PREVIEW_SIZE" -gt 200 ]; then
            if [ "$IS_CRASH_RECOVERY" = "true" ]; then
                # CRASH: inject FULL state.md — it's the ONLY reliable source
                # .mci could be hours stale, state.md is ground truth
                STATE_PREVIEW=$(cat "$SESSION_PATH/state.md" 2>/dev/null | head -c 12000)
            else
                # POST-COMPACT: inject generous preview (PreCompact already saved .mci)
                STATE_PREVIEW=$(cat "$SESSION_PATH/state.md" 2>/dev/null | head -c 8000)
            fi
        fi
    fi

    COMPACT_ALERT="
=== [AC] ${RECOVERY_TYPE} ===
${RECOVERY_REASON}
Best recovery source: $RECOVERY_SOURCE
$RECOVERY_EXTRA

ACTION REQUIRED:
1. Read $SESSION_PATH/doctor-mci.md — AI-curated recovery (if exists)
2. Review the state.md preview below — your Goal/Progress/Findings are here
3. Read SOUL.md + USER.md — identity restoration
4. Check Progress section — resume from first unchecked item
5. DO NOT ask the user what you were doing — your files tell you

Recovery info: $COMPACT_INFO"

    # Append state.md content directly to alert
    if [ -n "$STATE_PREVIEW" ]; then
        COMPACT_ALERT="${COMPACT_ALERT}

=== STATE.MD (injected — ${STATE_PREVIEW_SIZE}b) ===
${STATE_PREVIEW}"
    fi
fi

# Compute recovery status line
RECOVERY_STATUS="No"
if [ "$IS_POST_COMPACT" = "true" ]; then
    RECOVERY_STATUS="POST-COMPACT — READ doctor-mci.md + state.md NOW"
elif [ "$IS_CRASH_RECOVERY" = "true" ]; then
    RECOVERY_STATUS="CRASH — READ state.md NOW (PreCompact never fired, .mci may be stale)"
fi

CONTEXT="# [Claude] MCI v2 Session - $(date '+%Y-%m-%d %I:%M%p %Z')

=== STATUS ===
$VPN_LINE
$MOUNT_LINE
$HOOKS_LINE
$SESSION_LINE
Path: $SESSION_PATH
state.md: $STATE_STATUS
MCI: $([ "$MCI_LOADED" = "true" ] && echo "LOADED" || echo "EMPTY")
Doctor MCI: $([ "$DOCTOR_MCI_LOADED" = "true" ] && echo "LOADED (${DOCTOR_AGE}min old)" || echo "NOT FOUND")
Full Context: $([ "$FULL_CTX_LOADED" = "true" ] && echo "LOADED" || echo "NOT FOUND")
Recovery: $RECOVERY_STATUS
$COMPACT_ALERT
$LOADED_CONTEXT"

CONTEXT_ESCAPED=$(echo "$CONTEXT" | jq -Rs .)

cat << EOF
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": $CONTEXT_ESCAPED
  },
  "systemMessage": "MCIv2 #$SESSION_NUM @ $SESSION_TIME | VPN:$VPN_OK | state:$STATE_STATUS | MCI:$MCI_LOADED"
}
EOF

exit 0
