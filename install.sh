#!/bin/bash
# ============================================================================
# claude-memory installer
# One-command setup for persistent memory in Claude Code
# Usage: ./install.sh [project-directory]
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="${1:-$(pwd)}"

echo "=================================="
echo "  claude-memory installer"
echo "=================================="
echo ""
echo "Project directory: $PROJECT_DIR"
echo ""

# --- Prerequisites ---
if ! command -v jq &>/dev/null; then
    echo "[!] jq is required but not installed."
    echo "    Install: https://jqlang.github.io/jq/download/"
    echo "    - macOS: brew install jq"
    echo "    - Ubuntu: sudo apt install jq"
    echo "    - Arch: sudo pacman -S jq"
    exit 1
fi

# --- Create directories ---
echo "[*] Creating directories..."
mkdir -p "$PROJECT_DIR/.claude/hooks"
mkdir -p "$PROJECT_DIR/.claude-memory/sessions"

# --- Copy hooks ---
echo "[*] Installing hooks..."
for hook in session-start.sh prompt-capture.sh pre-compact.sh session-stop.sh; do
    cp "$SCRIPT_DIR/hooks/$hook" "$PROJECT_DIR/.claude/hooks/$hook"
    chmod +x "$PROJECT_DIR/.claude/hooks/$hook"
done
echo "[+] 4 hooks installed"

# --- Copy CLAUDE.md ---
if [ -f "$PROJECT_DIR/CLAUDE.md" ]; then
    echo ""
    echo "[?] CLAUDE.md already exists. What do you want to do?"
    echo "    1) Overwrite with claude-memory template"
    echo "    2) Append memory rules to existing CLAUDE.md"
    echo "    3) Skip (merge manually later)"
    read -rp "    Choice [1/2/3]: " CHOICE
    case "$CHOICE" in
        1) cp "$SCRIPT_DIR/CLAUDE.md" "$PROJECT_DIR/CLAUDE.md"
           echo "[+] CLAUDE.md replaced" ;;
        2) echo "" >> "$PROJECT_DIR/CLAUDE.md"
           echo "---" >> "$PROJECT_DIR/CLAUDE.md"
           echo "" >> "$PROJECT_DIR/CLAUDE.md"
           cat "$SCRIPT_DIR/CLAUDE.md" >> "$PROJECT_DIR/CLAUDE.md"
           echo "[+] memory rules appended to CLAUDE.md" ;;
        *) echo "[i] Skipped. Merge from: $SCRIPT_DIR/CLAUDE.md" ;;
    esac
else
    cp "$SCRIPT_DIR/CLAUDE.md" "$PROJECT_DIR/CLAUDE.md"
    echo "[+] CLAUDE.md installed"
fi

# --- Generate settings ---
SETTINGS_FILE="$PROJECT_DIR/.claude/settings.local.json"
if [ -f "$SETTINGS_FILE" ]; then
    echo ""
    echo "[!] $SETTINGS_FILE already exists."
    echo "    Add hooks manually. See README.md for the configuration."
else
    cat > "$SETTINGS_FILE" << 'SETTINGS_EOF'
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash \"$CLAUDE_PROJECT_DIR/.claude/hooks/session-start.sh\""
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash \"$CLAUDE_PROJECT_DIR/.claude/hooks/prompt-capture.sh\"",
            "timeout": 5
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash \"$CLAUDE_PROJECT_DIR/.claude/hooks/pre-compact.sh\""
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash \"$CLAUDE_PROJECT_DIR/.claude/hooks/session-stop.sh\"",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
SETTINGS_EOF
    echo "[+] Settings generated: $SETTINGS_FILE"
fi

# --- Optional: identity templates ---
echo ""
read -rp "[?] Install identity templates (IDENTITY.md, PREFERENCES.md)? [y/N]: " REPLY
if [[ "$REPLY" =~ ^[Yy]$ ]]; then
    cp "$SCRIPT_DIR/templates/IDENTITY.md" "$PROJECT_DIR/IDENTITY.md"
    cp "$SCRIPT_DIR/templates/PREFERENCES.md" "$PROJECT_DIR/PREFERENCES.md"
    echo "[+] Templates installed"
else
    echo "[i] Skipped. Available at: $SCRIPT_DIR/templates/"
fi

# --- Done ---
echo ""
echo "=================================="
echo "  Installation complete!"
echo "=================================="
echo ""
echo "  Start Claude Code in your project:"
echo "    cd $PROJECT_DIR && claude"
echo ""
echo "  Claude will now:"
echo "    - Load your last session state on startup"
echo "    - Track context usage and warn before compact"
echo "    - Save emergency state if compact fires"
echo "    - Generate session summaries on exit"
echo ""
echo "  Use markers in conversation:"
echo "    [!] critical facts    [*] why it matters"
echo "    [>] next steps        [i] observations"
echo ""
echo "  Sessions stored at:"
echo "    $PROJECT_DIR/.claude-memory/sessions/"
echo ""
