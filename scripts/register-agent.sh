#!/bin/bash
# ============================================================================
# REGISTER AGENT — One-time Supabase Agent Hub registration
# Creates agent + API key via gateway, outputs credentials for settings.json
# ============================================================================

set -e

GATEWAY_URL="${SUPABASE_GATEWAY_URL:?Set SUPABASE_GATEWAY_URL environment variable}"
SETTINGS_FILE="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"

echo "============================================"
echo "  Supabase Agent Hub — Agent Registration"
echo "============================================"
echo ""

# ============================================================================
# STEP 1: Get Supabase Auth Token
# ============================================================================

# Check if we have a token already
if [ -n "$SUPABASE_ACCESS_TOKEN" ]; then
    TOKEN="$SUPABASE_ACCESS_TOKEN"
    echo "[+] Using SUPABASE_ACCESS_TOKEN from environment"
else
    echo "[*] Need a Supabase auth token."
    echo ""
    echo "Option 1: Device pairing (recommended)"
    echo "  Run this first, then follow browser prompt:"
    echo ""

    # Try device pairing
    echo "[*] Initiating device authorization..."
    DEVICE_RESPONSE=$(curl -s -X POST "$GATEWAY_URL" \
        -H "Content-Type: application/json" \
        -d '{"action":"auth.device_authorize"}' \
        --max-time 10 2>/dev/null)

    if [ $? -ne 0 ] || [ -z "$DEVICE_RESPONSE" ]; then
        echo "[-] Gateway unreachable at $GATEWAY_URL"
        echo "[>] Check SUPABASE_GATEWAY_URL or deploy the gateway edge function"
        exit 1
    fi

    # Check for error
    ERROR=$(echo "$DEVICE_RESPONSE" | jq -r '.error // empty' 2>/dev/null)
    if [ -n "$ERROR" ]; then
        echo "[-] Gateway error: $ERROR"
        echo ""
        echo "Option 2: Manual token"
        echo "  Export SUPABASE_ACCESS_TOKEN=<your-jwt> and re-run"
        exit 1
    fi

    DEVICE_CODE=$(echo "$DEVICE_RESPONSE" | jq -r '.device_code // empty' 2>/dev/null)
    USER_CODE=$(echo "$DEVICE_RESPONSE" | jq -r '.user_code // empty' 2>/dev/null)
    VERIFY_URI=$(echo "$DEVICE_RESPONSE" | jq -r '.verification_uri // empty' 2>/dev/null)
    INTERVAL=$(echo "$DEVICE_RESPONSE" | jq -r '.interval // 5' 2>/dev/null)
    EXPIRES_IN=$(echo "$DEVICE_RESPONSE" | jq -r '.expires_in // 300' 2>/dev/null)

    if [ -z "$DEVICE_CODE" ] || [ -z "$USER_CODE" ]; then
        echo "[-] Device auth failed. Response:"
        echo "$DEVICE_RESPONSE" | jq . 2>/dev/null || echo "$DEVICE_RESPONSE"
        echo ""
        echo "Option 2: Manual token"
        echo "  Export SUPABASE_ACCESS_TOKEN=<your-jwt> and re-run"
        exit 1
    fi

    echo ""
    echo "============================================"
    echo "  PAIR YOUR DEVICE"
    echo "============================================"
    echo ""
    echo "  Code: $USER_CODE"
    echo "  URL:  $VERIFY_URI"
    echo ""
    echo "  Open the URL in your browser and enter the code."
    echo "  Waiting for approval (${EXPIRES_IN}s timeout)..."
    echo ""

    # Poll for token
    TOKEN=""
    ELAPSED=0
    while [ "$ELAPSED" -lt "$EXPIRES_IN" ]; do
        sleep "$INTERVAL"
        ELAPSED=$((ELAPSED + INTERVAL))

        POLL_RESPONSE=$(curl -s -X POST "$GATEWAY_URL" \
            -H "Content-Type: application/json" \
            -d "{\"action\":\"auth.token\",\"device_code\":\"$DEVICE_CODE\",\"grant_type\":\"urn:ietf:params:oauth:grant-type:device_code\"}" \
            --max-time 10 2>/dev/null)

        POLL_ERROR=$(echo "$POLL_RESPONSE" | jq -r '.error // empty' 2>/dev/null)

        if [ "$POLL_ERROR" = "authorization_pending" ]; then
            printf "."
            continue
        elif [ "$POLL_ERROR" = "slow_down" ]; then
            INTERVAL=$((INTERVAL + 2))
            printf "s"
            continue
        elif [ "$POLL_ERROR" = "expired_token" ]; then
            echo ""
            echo "[-] Device code expired. Re-run to try again."
            exit 1
        elif [ -n "$POLL_ERROR" ]; then
            echo ""
            echo "[-] Poll error: $POLL_ERROR"
            exit 1
        fi

        TOKEN=$(echo "$POLL_RESPONSE" | jq -r '.access_token // empty' 2>/dev/null)
        if [ -n "$TOKEN" ]; then
            echo ""
            echo "[+] Device paired successfully!"
            break
        fi
    done

    if [ -z "$TOKEN" ]; then
        echo ""
        echo "[-] Timed out waiting for approval."
        exit 1
    fi
fi

# ============================================================================
# STEP 2: Create Agent
# ============================================================================

HOSTNAME=$(hostname)
AGENT_NAME="${AGENT_NAME:-claude-code-$HOSTNAME}"
AGENT_TYPE="${AGENT_TYPE:-claude_code}"

echo ""
echo "[*] Creating agent: $AGENT_NAME (type: $AGENT_TYPE)"

AGENT_RESPONSE=$(curl -s -X POST "$GATEWAY_URL" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d "{\"action\":\"agents.create\",\"name\":\"$AGENT_NAME\",\"type\":\"$AGENT_TYPE\",\"capabilities\":{\"tools\":true,\"memory\":true,\"hooks\":true}}" \
    --max-time 10 2>/dev/null)

AGENT_ERROR=$(echo "$AGENT_RESPONSE" | jq -r '.error // empty' 2>/dev/null)
if [ -n "$AGENT_ERROR" ]; then
    echo "[-] Agent creation failed: $AGENT_ERROR"
    echo "$AGENT_RESPONSE" | jq . 2>/dev/null
    exit 1
fi

AGENT_ID=$(echo "$AGENT_RESPONSE" | jq -r '.agent.id // .id // empty' 2>/dev/null)
if [ -z "$AGENT_ID" ]; then
    echo "[-] No agent ID in response:"
    echo "$AGENT_RESPONSE" | jq . 2>/dev/null
    exit 1
fi

echo "[+] Agent created: $AGENT_ID"

# ============================================================================
# STEP 3: Create API Key
# ============================================================================

echo "[*] Creating API key..."

KEY_RESPONSE=$(curl -s -X POST "$GATEWAY_URL" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d "{\"action\":\"api_keys.create\",\"name\":\"$AGENT_NAME-hook-key\",\"scopes\":[\"memory.set\",\"memory.get\",\"memory.search\",\"memory.delete\",\"agents.heartbeat\",\"agents.update\"]}" \
    --max-time 10 2>/dev/null)

KEY_ERROR=$(echo "$KEY_RESPONSE" | jq -r '.error // empty' 2>/dev/null)
if [ -n "$KEY_ERROR" ]; then
    echo "[-] API key creation failed: $KEY_ERROR"
    echo "$KEY_RESPONSE" | jq . 2>/dev/null
    echo ""
    echo "[!] Agent was created ($AGENT_ID) but key failed."
    echo "[>] You can create a key manually via the gateway."
    exit 1
fi

API_KEY=$(echo "$KEY_RESPONSE" | jq -r '.key // .api_key // .raw_key // empty' 2>/dev/null)
if [ -z "$API_KEY" ]; then
    echo "[-] No API key in response:"
    echo "$KEY_RESPONSE" | jq . 2>/dev/null
    exit 1
fi

echo "[+] API key created (save this — it won't be shown again)"

# ============================================================================
# STEP 4: Output Credentials
# ============================================================================

echo ""
echo "============================================"
echo "  REGISTRATION COMPLETE"
echo "============================================"
echo ""
echo "  Agent ID:  $AGENT_ID"
echo "  API Key:   $API_KEY"
echo "  Gateway:   $GATEWAY_URL"
echo ""
echo "============================================"
echo ""

# ============================================================================
# STEP 5: Auto-update settings.json (if writable)
# ============================================================================

if [ -f "$SETTINGS_FILE" ] && command -v jq &>/dev/null; then
    echo "[*] Updating settings.json with credentials..."

    # Use jq to update env vars
    UPDATED=$(jq \
        --arg agent_id "$AGENT_ID" \
        --arg api_key "$API_KEY" \
        --arg gateway "$GATEWAY_URL" \
        '.env.SUPABASE_AGENT_ID = $agent_id |
         .env.SUPABASE_AGENT_API_KEY = $api_key |
         .env.SUPABASE_GATEWAY_URL = $gateway |
         .env.SUPABASE_SYNC_ENABLED = "true"' \
        "$SETTINGS_FILE" 2>/dev/null)

    if [ -n "$UPDATED" ]; then
        echo "$UPDATED" > "$SETTINGS_FILE"
        echo "[+] settings.json updated — Supabase sync ENABLED"
        echo "[!] Restart Claude Code for env vars to take effect"
    else
        echo "[-] Failed to update settings.json automatically"
        echo "[>] Manually set these in settings.json env section:"
        echo "    SUPABASE_AGENT_ID: $AGENT_ID"
        echo "    SUPABASE_AGENT_API_KEY: $API_KEY"
        echo "    SUPABASE_SYNC_ENABLED: true"
    fi
else
    echo "[>] Manually set these in settings.json env section:"
    echo "    SUPABASE_AGENT_ID: $AGENT_ID"
    echo "    SUPABASE_AGENT_API_KEY: $API_KEY"
    echo "    SUPABASE_SYNC_ENABLED: true"
fi

echo ""
echo "[+] Done. Your agent is registered and ready to sync."
echo "[>] Next session, hooks will push/pull state.md to Supabase."
