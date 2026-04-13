#!/bin/bash
# bootstrap-agent-memory.sh — Creates agent memory directories and seeds MEMORY.md templates
# Part of the Agent Memory Frontmatter integration
# Created: 2026-02-18

set -e

# Config
AGENT_MEMORY_DIR="$HOME/.claude/agent-memory"
TEMPLATE_DIR="/path/to/workspace/scripts/agent-memory-templates"

# All 10 agents
AGENTS=(
    "recon-discovery"
    "webhunter-appsec"
    "redteam-offensive"
    "blueteam-defensive"
    "gatherer-osint"
    "security-opsec"
    "reporter-documentation"
    "whitehat-compliance"
    "exploit-blackops"
    "memory-organizer"
)

# Version check
CLAUDE_VERSION=$(claude --version 2>/dev/null | head -1 | grep -oP '[\d.]+' || echo "0.0.0")
REQUIRED="2.1.33"

version_ge() {
    printf '%s\n%s' "$2" "$1" | sort -V -C
}

if ! version_ge "$CLAUDE_VERSION" "$REQUIRED"; then
    echo "[-] Claude Code version $CLAUDE_VERSION is below required $REQUIRED"
    echo "[>] Run: claude update"
    exit 1
fi

echo "[+] Claude Code v$CLAUDE_VERSION >= $REQUIRED — OK"

# Check templates exist
if [ ! -d "$TEMPLATE_DIR" ]; then
    echo "[-] Template directory not found: $TEMPLATE_DIR"
    exit 1
fi

echo "[*] Creating agent memory directories..."

for agent in "${AGENTS[@]}"; do
    dir="$AGENT_MEMORY_DIR/$agent"
    template="$TEMPLATE_DIR/$agent.md"

    # Create directory
    mkdir -p "$dir"

    # Copy template if exists and MEMORY.md doesn't already exist
    if [ -f "$template" ]; then
        if [ ! -f "$dir/MEMORY.md" ]; then
            cp "$template" "$dir/MEMORY.md"
            echo "[+] $agent: Created with template"
        else
            echo "[i] $agent: MEMORY.md already exists, skipping (won't overwrite)"
        fi
    else
        echo "[-] $agent: No template found at $template"
    fi
done

echo ""
echo "[+] Bootstrap complete. Directories created:"
echo ""

for agent in "${AGENTS[@]}"; do
    dir="$AGENT_MEMORY_DIR/$agent"
    if [ -f "$dir/MEMORY.md" ]; then
        lines=$(wc -l < "$dir/MEMORY.md")
        echo "  [+] $agent/MEMORY.md ($lines lines)"
    else
        echo "  [-] $agent/MEMORY.md MISSING"
    fi
done

echo ""
echo "[>] Next: Add 'memory: user' to all agent frontmatter files"
