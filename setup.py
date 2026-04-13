#!/usr/bin/env python3
"""
MEMORY ENGINE SETUP — Cross-platform installer.
Sets up database, directories, and Claude Code MCP integration.
"""

import os
import sys
import json
import sqlite3
import shutil
from pathlib import Path


def main():
    print("[*] Memory Engine Setup")
    print(f"[i] Platform: {sys.platform}")
    print(f"[i] Python: {sys.version}")

    # Import config to get resolved paths
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "memory_engine"))
    from config import (
        DB_PATH, CHROMA_PATH, IMAGES_DIR, JSONL_DIR,
        AGENT_MEMORY_DIR, VIEWER_PORT, LOG_FILE, LOCK_FILE,
        print_config, _get_claude_config_dir, _get_engine_dir
    )

    print()
    print_config()
    print()

    # 1. Create directories
    print("[*] Creating directories...")
    for d in [
        Path(CHROMA_PATH),
        IMAGES_DIR,
        AGENT_MEMORY_DIR,
        Path(LOG_FILE).parent,
    ]:
        d.mkdir(parents=True, exist_ok=True)
        print(f"  [+] {d}")

    # 2. Initialize database
    print("[*] Initializing SQLite database...")
    db_path = Path(DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            role TEXT,
            session_id TEXT,
            timestamp TEXT,
            source_line INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            file_path TEXT,
            file_size INTEGER,
            file_hash TEXT,
            lines_processed INTEGER DEFAULT 0,
            last_processed_at TEXT,
            status TEXT DEFAULT 'new'
        );

        CREATE TABLE IF NOT EXISTS ingest_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            action TEXT,
            entries_added INTEGER DEFAULT 0,
            timestamp TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            source TEXT DEFAULT 'user',
            confidence REAL DEFAULT 1.0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            type TEXT NOT NULL,
            concept TEXT,
            content TEXT NOT NULL,
            confidence REAL DEFAULT 0.5,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS session_summaries (
            session_id TEXT PRIMARY KEY,
            request TEXT,
            investigated TEXT,
            learned TEXT,
            completed TEXT,
            next_steps TEXT,
            entry_count INTEGER,
            duration_minutes INTEGER,
            tools_used TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            tags TEXT,
            color TEXT DEFAULT '#58a6ff',
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS project_sessions (
            project_id INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            notes TEXT,
            added_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (project_id, session_id),
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE INDEX IF NOT EXISTS idx_entries_session ON entries(session_id);
        CREATE INDEX IF NOT EXISTS idx_entries_role ON entries(role);
        CREATE INDEX IF NOT EXISTS idx_entries_timestamp ON entries(timestamp);
        CREATE INDEX IF NOT EXISTS idx_observations_session ON observations(session_id);
        CREATE INDEX IF NOT EXISTS idx_observations_type ON observations(type);
        CREATE INDEX IF NOT EXISTS idx_knowledge_key ON knowledge(key);
    """)

    # FTS5 virtual table
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(content, content=entries, content_rowid=id)")
    except Exception as e:
        print(f"  [i] FTS5: {e}")

    conn.close()
    print(f"  [+] Database: {db_path}")

    # 3. Configure Claude Code MCP server
    print("[*] Configuring Claude Code MCP server...")
    claude_dir = _get_claude_config_dir()
    engine_dir = _get_engine_dir()
    mcp_server_path = engine_dir / "mcp_server.py"

    # Build MCP config entry
    mcp_config = {
        "command": sys.executable,
        "args": [str(mcp_server_path)],
        "env": {
            "MEMORY_DB": str(db_path),
            "MEMORY_CHROMA_PATH": str(CHROMA_PATH),
            "MEMORY_ENGINE_DIR": str(engine_dir),
        }
    }

    # Read existing .claude.json or create new
    claude_json = claude_dir / ".claude.json"
    config = {}
    if claude_json.exists():
        try:
            with open(claude_json) as f:
                config = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    if "mcpServers" not in config:
        config["mcpServers"] = {}

    config["mcpServers"]["memory-engine"] = mcp_config

    # Write back
    with open(claude_json, "w") as f:
        json.dump(config, f, indent=2)
    print(f"  [+] MCP config: {claude_json}")
    print(f"  [i] Server: {mcp_server_path}")

    # 4. Done
    print()
    print("[+] Setup complete!")
    print()
    print("[>] Next steps:")
    print(f"  1. Install dependencies:  pip install -r requirements.txt")
    print(f"  2. Ingest conversations:  python {engine_dir / 'auto_ingest.py'} all")
    print(f"  3. Start viewer:          python {engine_dir / 'viewer.py'}")
    print(f"  4. Open dashboard:        http://localhost:{VIEWER_PORT}")
    print(f"  5. (Optional) Embed:      python {engine_dir / 'embed_batch.py'}")
    print()
    print("[i] For semantic search, install chromadb: pip install chromadb")


if __name__ == "__main__":
    main()
