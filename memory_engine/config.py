"""
CROSS-PLATFORM CONFIGURATION
All paths resolve dynamically based on OS and environment variables.
No hardcoded Linux paths.

Override any path via environment variables:
  MEMORY_DB          — SQLite database path
  MEMORY_CHROMA_PATH — Chroma vector DB directory
  MEMORY_IMAGES_DIR  — Extracted images directory
  MEMORY_JSONL_DIR   — Claude Code JSONL conversation directory
  MEMORY_VIEWER_PORT — Viewer HTTP port (default 37888)
  MEMORY_ENGINE_DIR  — Base directory for memory-engine files

On Windows, defaults use %USERPROFILE%/.claude-mem/
On Linux/Mac, defaults use ~/.claude-mem/
"""

import os
import sys
from pathlib import Path

# ── Base directories ──────────────────────────────────────────────

def _get_home():
    """Get user home directory cross-platform."""
    return Path.home()

def _get_claude_config_dir():
    """Get Claude Code config directory."""
    if sys.platform == "win32":
        # Windows: %APPDATA%/claude or %USERPROFILE%/.claude
        appdata = os.environ.get("APPDATA")
        if appdata:
            p = Path(appdata) / "claude"
            if p.exists():
                return p
    return _get_home() / ".claude"

def _get_claude_mem_dir():
    """Get claude-mem data directory."""
    return Path(os.environ.get("CLAUDE_MEM_DIR", str(_get_home() / ".claude-mem")))

def _get_engine_dir():
    """Get memory-engine base directory (where this code lives)."""
    env = os.environ.get("MEMORY_ENGINE_DIR")
    if env:
        return Path(env)
    return Path(__file__).parent

# ── Resolved paths ───────────────────────────────────────────────

# SQLite database
DB_PATH = os.environ.get("MEMORY_DB", str(_get_engine_dir() / "memory.db"))

# Chroma vector database
CHROMA_PATH = os.environ.get("MEMORY_CHROMA_PATH", str(_get_claude_mem_dir() / "vector-db"))

# Images extracted from conversations
IMAGES_DIR = Path(os.environ.get("MEMORY_IMAGES_DIR", str(_get_engine_dir() / "images")))

# Claude Code JSONL conversation files
def _detect_jsonl_dir():
    """Auto-detect JSONL directory based on Claude Code's project structure.
    Returns the projects/ root so all project dirs are accessible."""
    claude_dir = _get_claude_config_dir()

    # Check env override
    env = os.environ.get("MEMORY_JSONL_DIR")
    if env:
        return Path(env)

    # Return the projects/ root — iter_claude_code_files() scans all subdirs
    projects_dir = claude_dir / "projects"
    if projects_dir.exists():
        return projects_dir

    # Fallback: claude config dir itself
    return claude_dir

JSONL_DIR = _detect_jsonl_dir()


def iter_claude_code_files():
    """Iterate ALL Claude Code session JSONL files across all project directories.
    Includes main sessions and subagent sessions (recursive).
    Returns sorted by modification time (newest first)."""
    if not JSONL_DIR or not Path(JSONL_DIR).exists():
        return []
    return sorted(
        Path(JSONL_DIR).rglob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

# ── Multi-source conversation directories ──────────────────────

def _detect_copilot_dir():
    """Auto-detect GitHub Copilot CLI session state directory."""
    env = os.environ.get("MEMORY_COPILOT_DIR")
    if env:
        return Path(env)
    copilot_dir = _get_home() / ".copilot" / "session-state"
    if copilot_dir.exists():
        return copilot_dir
    return None

def _detect_codex_dir():
    """Auto-detect OpenAI Codex CLI sessions directory."""
    env = os.environ.get("MEMORY_CODEX_DIR")
    if env:
        return Path(env)
    codex_dir = _get_home() / ".codex" / "sessions"
    if codex_dir.exists():
        return codex_dir
    return None

COPILOT_JSONL_DIR = _detect_copilot_dir()
CODEX_JSONL_DIR = _detect_codex_dir()


def iter_copilot_files():
    """Iterate Copilot CLI session JSONL files (top-level + subdirectory events.jsonl)."""
    if not COPILOT_JSONL_DIR or not COPILOT_JSONL_DIR.exists():
        return []
    files = list(COPILOT_JSONL_DIR.glob("*.jsonl"))
    # Newer Copilot versions store sessions as <uuid>/events.jsonl
    files += list(COPILOT_JSONL_DIR.glob("*/events.jsonl"))
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def iter_codex_files():
    """Iterate Codex CLI session JSONL files (recursive — date-based dirs)."""
    if not CODEX_JSONL_DIR or not CODEX_JSONL_DIR.exists():
        return []
    return sorted(CODEX_JSONL_DIR.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)


# Agent memory directory
AGENT_MEMORY_DIR = Path(os.environ.get("MEMORY_AGENT_DIR", str(_get_claude_config_dir() / "agent-memory")))

# Viewer port
VIEWER_PORT = int(os.environ.get("MEMORY_VIEWER_PORT", "37888"))

# Chroma collection name
COLLECTION_NAME = os.environ.get("MEMORY_COLLECTION", "memory_engine")

# Session state directory (for MCI hooks)
SESSION_BASE = os.environ.get("MEMORY_SESSION_BASE", "")

# Ingest log and lock
LOG_FILE = Path(os.environ.get("MEMORY_LOG_FILE", str(_get_engine_dir() / "ingest.log")))
LOCK_FILE = Path(os.environ.get("MEMORY_LOCK_FILE", str(_get_engine_dir() / ".ingest.lock")))


def get_claude_config_dir():
    """Public access to Claude config directory."""
    return _get_claude_config_dir()


def print_config():
    """Print resolved configuration for debugging."""
    print(f"[i] Platform:     {sys.platform}")
    print(f"[i] Home:         {_get_home()}")
    print(f"[i] Claude dir:   {_get_claude_config_dir()}")
    print(f"[i] Engine dir:   {_get_engine_dir()}")
    print(f"[i] DB_PATH:      {DB_PATH}")
    print(f"[i] CHROMA_PATH:  {CHROMA_PATH}")
    print(f"[i] IMAGES_DIR:   {IMAGES_DIR}")
    print(f"[i] JSONL_DIR:    {JSONL_DIR}")
    print(f"[i] COPILOT_DIR:  {COPILOT_JSONL_DIR or 'not found'}")
    print(f"[i] CODEX_DIR:    {CODEX_JSONL_DIR or 'not found'}")
    print(f"[i] AGENT_DIR:    {AGENT_MEMORY_DIR}")
    print(f"[i] VIEWER_PORT:  {VIEWER_PORT}")
    print(f"[i] LOG_FILE:     {LOG_FILE}")


if __name__ == "__main__":
    print_config()
