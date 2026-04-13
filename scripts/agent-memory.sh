#!/bin/bash
# ============================================================================
# AGENT MEMORY — Cross-Platform Shared Memory via Supabase REST API
# Read/write/search memories that ALL agents can access from ANY device
#
# Usage:
#   agent-memory.sh save <namespace> <key> <content> [--meta '{"k":"v"}']
#   agent-memory.sh read <namespace> [key]
#   agent-memory.sh search <text>
#   agent-memory.sh target <domain>         # get all intel on a target
#   agent-memory.sh findings [domain]       # get all vuln findings
#   agent-memory.sh log <message>           # quick operational log
#   agent-memory.sh list                    # list all namespaces + counts
# ============================================================================

set -e

SUPABASE_URL="${SUPABASE_URL:?Set SUPABASE_URL environment variable}"
ANON_KEY="${SUPABASE_ANON_KEY:?Set SUPABASE_ANON_KEY environment variable}"
API_KEY="${SUPABASE_AGENT_API_KEY:-}"
AGENT_ID="${SUPABASE_AGENT_ID:-}"
USER_ID="${SUPABASE_USER_ID:?Set SUPABASE_USER_ID environment variable}"
REST_URL="$SUPABASE_URL/rest/v1"

sb_get() {
    curl -s "$REST_URL/$1" \
        -H "apikey: $ANON_KEY" \
        -H "Authorization: Bearer $ANON_KEY" \
        --max-time 10 2>/dev/null
}

sb_post() {
    curl -s -X POST "$REST_URL/$1" \
        -H "apikey: $ANON_KEY" \
        -H "Authorization: Bearer $ANON_KEY" \
        -H "Content-Type: application/json" \
        -H "Prefer: return=representation" \
        -d "$2" \
        --max-time 10 2>/dev/null
}

sb_upsert() {
    curl -s -X POST "$REST_URL/$1" \
        -H "apikey: $ANON_KEY" \
        -H "Authorization: Bearer $ANON_KEY" \
        -H "Content-Type: application/json" \
        -H "Prefer: resolution=merge-duplicates,return=representation" \
        -d "$2" \
        --max-time 10 2>/dev/null
}

ACTION="$1"
shift || true

case "$ACTION" in
    save|write|put)
        NS="$1"; KEY="$2"; CONTENT="$3"
        META="{}"
        if [ -z "$NS" ] || [ -z "$KEY" ] || [ -z "$CONTENT" ]; then
            echo "Usage: agent-memory.sh save <namespace> <key> <content> [--meta='{...}']"
            exit 1
        fi
        shift 3 || true
        for arg in "$@"; do
            case "$arg" in --meta=*) META="${arg#--meta=}" ;; esac
        done
        PAYLOAD=$(jq -cn \
            --arg uid "$USER_ID" \
            --arg aid "$AGENT_ID" \
            --arg ns "$NS" \
            --arg key "$KEY" \
            --arg content "$CONTENT" \
            --argjson meta "$META" \
            '{user_id:$uid, agent_id:$aid, namespace:$ns, key:$key, content:$content, metadata:$meta}')
        RESULT=$(sb_post "memories" "$PAYLOAD")
        ERR=$(echo "$RESULT" | jq -r '.code // empty' 2>/dev/null)
        if [ -n "$ERR" ]; then
            # Duplicate key — update instead
            PAYLOAD=$(jq -cn \
                --arg content "$CONTENT" \
                --argjson meta "$META" \
                '{content:$content, metadata:$meta}')
            curl -s -X PATCH "$REST_URL/memories?namespace=eq.$NS&key=eq.$KEY&user_id=eq.$USER_ID" \
                -H "apikey: $ANON_KEY" \
                -H "Authorization: Bearer $ANON_KEY" \
                -H "Content-Type: application/json" \
                -d "$PAYLOAD" \
                --max-time 10 2>/dev/null > /dev/null
            echo "[+] Updated: $NS/$KEY"
        else
            echo "[+] Saved: $NS/$KEY"
        fi
        ;;

    read|get)
        NS="$1"; KEY="$2"
        if [ -z "$NS" ]; then
            echo "Usage: agent-memory.sh read <namespace> [key]"
            exit 1
        fi
        if [ -n "$KEY" ]; then
            RESULT=$(sb_get "memories?namespace=eq.$NS&key=eq.$KEY&select=key,content,metadata,agent_id,created_at")
            echo "$RESULT" | jq '.[0] // "Not found"' 2>/dev/null || echo "$RESULT"
        else
            RESULT=$(sb_get "memories?namespace=eq.$NS&select=key,content,metadata,created_at&order=created_at.desc&limit=20")
            echo "$RESULT" | jq '.[] | {key, content: .content[0:200], metadata, created_at}' 2>/dev/null || echo "$RESULT"
        fi
        ;;

    search|find)
        QUERY="$1"
        if [ -z "$QUERY" ]; then
            echo "Usage: agent-memory.sh search <text>"
            exit 1
        fi
        # Full-text search on content
        RESULT=$(sb_get "memories?or=(content.ilike.*$QUERY*,key.ilike.*$QUERY*)&select=namespace,key,content,metadata,created_at&order=created_at.desc&limit=15")
        echo "$RESULT" | jq '.[] | {namespace, key, content: .content[0:200], metadata}' 2>/dev/null || echo "$RESULT"
        ;;

    target|intel)
        DOMAIN="$1"
        if [ -z "$DOMAIN" ]; then
            echo "Usage: agent-memory.sh target <domain>"
            exit 1
        fi
        echo "[*] All intel on: $DOMAIN"
        RESULT=$(sb_get "memories?or=(key.ilike.*$DOMAIN*,content.ilike.*$DOMAIN*)&select=namespace,key,content,metadata,created_at&order=namespace,created_at.desc&limit=50")
        COUNT=$(echo "$RESULT" | jq 'length' 2>/dev/null || echo 0)
        echo "[i] Found $COUNT entries"
        echo ""
        echo "$RESULT" | jq -r '.[] | "[\(.namespace)] \(.key)\n  \(.content[0:300])\n"' 2>/dev/null || echo "$RESULT"
        ;;

    findings|vulns)
        DOMAIN="${1:-}"
        if [ -n "$DOMAIN" ]; then
            FILTER="&or=(key.ilike.*$DOMAIN*,content.ilike.*$DOMAIN*)"
        else
            FILTER=""
        fi
        RESULT=$(sb_get "memories?namespace=in.(findings,vulns)${FILTER}&select=namespace,key,content,metadata,created_at&order=created_at.desc&limit=30")
        echo "$RESULT" | jq '.[] | {namespace, key, content: .content[0:300], severity: .metadata.severity, target: .metadata.target}' 2>/dev/null || echo "$RESULT"
        ;;

    log|note)
        MSG="$*"
        if [ -z "$MSG" ]; then
            echo "Usage: agent-memory.sh log <message>"
            exit 1
        fi
        TS=$(date +%Y%m%d_%H%M%S)
        HOST=$(hostname)
        PAYLOAD=$(jq -cn \
            --arg uid "$USER_ID" \
            --arg aid "$AGENT_ID" \
            --arg key "log_${TS}" \
            --arg content "$MSG" \
            --arg host "$HOST" \
            '{user_id:$uid, agent_id:$aid, namespace:"ops", key:$key, content:$content, metadata:{type:"log",host:$host}}')
        sb_post "memories" "$PAYLOAD" > /dev/null
        echo "[+] Logged: $MSG"
        ;;

    list|ns)
        echo "[*] Memory namespaces:"
        RESULT=$(sb_get "memories?select=namespace&user_id=eq.$USER_ID")
        echo "$RESULT" | jq -r '[.[] | .namespace] | group_by(.) | .[] | "  \(.[0]): \(length) entries"' 2>/dev/null || echo "$RESULT"
        ;;

    *)
        echo "Agent Memory — Cross-Platform Shared Brain"
        echo ""
        echo "Usage:"
        echo "  agent-memory.sh save <ns> <key> <content> [--meta='{...}']"
        echo "  agent-memory.sh read <namespace> [key]"
        echo "  agent-memory.sh search <text>"
        echo "  agent-memory.sh target <domain>"
        echo "  agent-memory.sh findings [domain]"
        echo "  agent-memory.sh log <message>"
        echo "  agent-memory.sh list"
        echo ""
        echo "Namespaces: recon, vulns, findings, scan, targets, ops, tasks"
        exit 1
        ;;
esac
