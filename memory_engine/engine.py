#!/usr/bin/env python3
"""
MEMORY ENGINE — The Brain Database
Indexes all Claude Code conversation history into a queryable SQLite database.
Replaces claude-mem. Pairs with FastMCP server for native Claude Code integration.
"""

import re
import sqlite3
import json
import os
import base64
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

# Import centralized config
try:
    from .config import DB_PATH, IMAGES_DIR
except ImportError:
    from config import DB_PATH, IMAGES_DIR

# Ensure images directory exists
Path(IMAGES_DIR).mkdir(parents=True, exist_ok=True)

# Agent tag taxonomy — customize for your use case
# Maps agent names to keyword lists for auto-classification
AGENT_TAGS = {
    # Example agents (override via config or subclass):
    # "research": ["paper", "study", "analysis", "finding", "methodology"],
    # "development": ["feature", "refactor", "deploy", "test", "build"],
}


class MemoryEngine:
    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self._connect()
        self._init_schema()

    def _connect(self):
        """Open (or reopen) the SQLite connection."""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")  # Crash-safe
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.row_factory = sqlite3.Row

    def reconnect(self):
        """Close stale connection and reopen from disk."""
        try:
            self.conn.close()
        except Exception:
            pass
        self._connect()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                role TEXT NOT NULL,           -- user/assistant/system/tool
                session_id TEXT,
                timestamp TEXT,
                source_file TEXT,
                source_line INTEGER,
                content_hash TEXT UNIQUE,     -- dedup
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                summary TEXT NOT NULL,
                details TEXT,
                agent TEXT,                   -- which agent this is relevant to
                tags TEXT,                    -- comma-separated tags
                source_entry_id INTEGER,      -- FK to entries
                status TEXT DEFAULT 'ACTIVE', -- ACTIVE/STALE/ARCHIVED
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                review_trigger TEXT,
                update_history TEXT DEFAULT '[]',
                FOREIGN KEY (source_entry_id) REFERENCES entries(id)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,          -- JSONL filename (UUID)
                file_path TEXT NOT NULL,
                file_size INTEGER,
                lines_processed INTEGER DEFAULT 0,
                total_lines INTEGER,
                last_processed_at TEXT,
                status TEXT DEFAULT 'pending', -- pending/processing/done
                summary TEXT                  -- LLM-generated session summary
            );

            CREATE TABLE IF NOT EXISTS ingest_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                entries_found INTEGER DEFAULT 0,
                knowledge_extracted INTEGER DEFAULT 0,
                started_at TEXT DEFAULT (datetime('now')),
                finished_at TEXT,
                status TEXT DEFAULT 'running'
            );

            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER,               -- FK to entries
                session_id TEXT,
                filename TEXT NOT NULL,          -- on-disk filename
                media_type TEXT DEFAULT 'image/png',
                width INTEGER,
                height INTEGER,
                file_size INTEGER,
                source_line INTEGER,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (entry_id) REFERENCES entries(id)
            );

            CREATE INDEX IF NOT EXISTS idx_images_entry ON images(entry_id);
            CREATE INDEX IF NOT EXISTS idx_images_session ON images(session_id);

            -- Full-text search index
            CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
                content, role, session_id,
                content='entries',
                content_rowid='id'
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                topic, summary, details, agent, tags,
                content='knowledge',
                content_rowid='id'
            );

            -- Triggers to keep FTS in sync
            CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
                INSERT INTO entries_fts(rowid, content, role, session_id)
                VALUES (new.id, new.content, new.role, new.session_id);
            END;

            CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge BEGIN
                INSERT INTO knowledge_fts(rowid, topic, summary, details, agent, tags)
                VALUES (new.id, new.topic, new.summary, new.details, new.agent, new.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS knowledge_au AFTER UPDATE ON knowledge BEGIN
                DELETE FROM knowledge_fts WHERE rowid = old.id;
                INSERT INTO knowledge_fts(rowid, topic, summary, details, agent, tags)
                VALUES (new.id, new.topic, new.summary, new.details, new.agent, new.tags);
            END;

            -- Projects
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                tags TEXT,                              -- comma-separated
                color TEXT DEFAULT '#58a6ff',
                status TEXT DEFAULT 'active',           -- active/archived
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS project_sessions (
                project_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                added_at TEXT DEFAULT (datetime('now')),
                notes TEXT,
                PRIMARY KEY (project_id, session_id),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            -- Indexes
            CREATE INDEX IF NOT EXISTS idx_entries_session ON entries(session_id);
            CREATE INDEX IF NOT EXISTS idx_entries_role ON entries(role);
            CREATE INDEX IF NOT EXISTS idx_entries_timestamp ON entries(timestamp);
            CREATE INDEX IF NOT EXISTS idx_knowledge_agent ON knowledge(agent);
            CREATE INDEX IF NOT EXISTS idx_knowledge_status ON knowledge(status);
            CREATE INDEX IF NOT EXISTS idx_knowledge_topic ON knowledge(topic);
            CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
            CREATE INDEX IF NOT EXISTS idx_projects_name ON projects(name);
            CREATE INDEX IF NOT EXISTS idx_ps_session ON project_sessions(session_id);
            CREATE INDEX IF NOT EXISTS idx_ps_project ON project_sessions(project_id);
        """)
        self.conn.commit()

        # Schema migrations (idempotent — safe to run on existing DBs)
        for sql in [
            "ALTER TABLE entries ADD COLUMN source TEXT DEFAULT 'claude_code'",
            "ALTER TABLE sessions ADD COLUMN source TEXT DEFAULT 'claude_code'",
            "ALTER TABLE sessions ADD COLUMN summary TEXT",
        ]:
            try:
                self.conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # Column already exists

        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_entries_source ON entries(source)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source)")
        self.conn.commit()

    # ── Search ──────────────────────────────────────────────────

    @staticmethod
    def _sanitize_fts(query):
        """Sanitize FTS5 query — quote terms with special chars."""
        import re
        # If user already used FTS5 syntax (AND, OR, NOT, quotes), pass through
        if any(op in query.upper() for op in [' AND ', ' OR ', ' NOT ', '"']):
            return query
        # Quote individual terms that contain hyphens or dots (e.g. CVE-2026, nginx/1.19)
        tokens = query.split()
        sanitized = []
        for t in tokens:
            if re.search(r'[-./:]', t):
                sanitized.append(f'"{t}"')
            else:
                sanitized.append(t)
        return ' '.join(sanitized)

    def search(self, query, agent=None, role=None, limit=20, days=None):
        """Full-text search across all entries."""
        conditions = []
        params = []
        query = self._sanitize_fts(query)

        sql = """
            SELECT e.id, e.content, e.role, e.session_id, e.timestamp, e.source_file,
                   rank
            FROM entries_fts fts
            JOIN entries e ON e.id = fts.rowid
            WHERE entries_fts MATCH ?
        """
        params.append(query)

        if role:
            sql += " AND e.role = ?"
            params.append(role)

        if days:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            sql += " AND e.timestamp >= ?"
            params.append(cutoff)

        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def search_knowledge(self, query, agent=None, status="ACTIVE", limit=20):
        """Search the knowledge base."""
        query = self._sanitize_fts(query)
        sql = """
            SELECT k.*, rank
            FROM knowledge_fts fts
            JOIN knowledge k ON k.id = fts.rowid
            WHERE knowledge_fts MATCH ?
        """
        params = [query]

        if agent:
            sql += " AND k.agent = ?"
            params.append(agent)

        if status:
            sql += " AND k.status = ?"
            params.append(status)

        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    # ── Timeline ────────────────────────────────────────────────

    def timeline(self, start=None, end=None, limit=50):
        """Get entries in chronological order for a time range."""
        sql = "SELECT * FROM entries WHERE 1=1"
        params = []

        if start:
            sql += " AND timestamp >= ?"
            params.append(start)
        if end:
            sql += " AND timestamp <= ?"
            params.append(end)

        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    # ── Knowledge CRUD ──────────────────────────────────────────

    def save_knowledge(self, topic, summary, details=None, agent=None, tags=None,
                       source_entry_id=None, review_trigger=None):
        """Save or update a knowledge entry. Deduplicates by topic+agent."""
        # Check for existing entry with same topic+agent
        existing = self.conn.execute(
            "SELECT * FROM knowledge WHERE topic = ? AND agent = ? AND status = 'ACTIVE'",
            (topic, agent)
        ).fetchone()

        now = datetime.now().isoformat()

        if existing:
            # Update existing — append to history
            history = json.loads(existing["update_history"] or "[]")
            history.append({
                "date": now,
                "old_summary": existing["summary"],
                "new_summary": summary,
                "reason": "Updated by memory engine"
            })
            self.conn.execute("""
                UPDATE knowledge
                SET summary = ?, details = ?, tags = ?, updated_at = ?, update_history = ?
                WHERE id = ?
            """, (summary, details or existing["details"], tags, now, json.dumps(history), existing["id"]))
            self.conn.commit()
            return {"action": "updated", "id": existing["id"]}
        else:
            cursor = self.conn.execute("""
                INSERT INTO knowledge (topic, summary, details, agent, tags, source_entry_id,
                                       review_trigger, update_history)
                VALUES (?, ?, ?, ?, ?, ?, ?, '[]')
            """, (topic, summary, details, agent, tags, source_entry_id, review_trigger))
            self.conn.commit()
            return {"action": "created", "id": cursor.lastrowid}

    def get_agent_knowledge(self, agent, status="ACTIVE", limit=50):
        """Get all knowledge for a specific agent."""
        sql = "SELECT * FROM knowledge WHERE agent = ?"
        params = [agent]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    # ── Ingestion ───────────────────────────────────────────────

    def ingest_jsonl(self, file_path, batch_size=1000, source="claude_code"):
        """Incrementally ingest a JSONL file. Resumes from last position."""
        file_path = str(file_path)
        session_id = Path(file_path).stem

        # Check if already processed
        session = self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()

        start_line = 0
        if session:
            # Check if file has grown since last ingest
            current_size = os.path.getsize(file_path)
            old_size = session["file_size"] or 0
            if session["status"] == "done" and current_size == old_size:
                return {"status": "already_done", "session_id": session_id}
            # Resume from where we left off (incremental ingest)
            start_line = session["lines_processed"] or 0

        # Log the ingest
        log_id = self.conn.execute(
            "INSERT INTO ingest_log (source) VALUES (?)", (file_path,)
        ).lastrowid

        entries_found = 0
        batch = []

        with open(file_path, 'r', errors='replace') as f:
            for line_num, line in enumerate(f):
                if line_num < start_line:
                    continue

                try:
                    data = json.loads(line.strip())
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type", "")

                # Extract meaningful content
                entry = self._extract_entry(data, msg_type, session_id, line_num)
                if entry:
                    entry["source"] = source
                    batch.append(entry)
                    entries_found += 1

                # Batch insert
                if len(batch) >= batch_size:
                    self._insert_batch(batch)
                    batch = []
                    # Update progress
                    self.conn.execute("""
                        INSERT INTO sessions (id, file_path, lines_processed, status, source)
                        VALUES (?, ?, ?, 'processing', ?)
                        ON CONFLICT(id) DO UPDATE SET lines_processed = ?, status = 'processing'
                    """, (session_id, file_path, line_num + 1, source, line_num + 1))
                    self.conn.commit()

        # Final batch
        if batch:
            self._insert_batch(batch)

        # Mark done with file size for growth detection
        total_lines = line_num + 1 if 'line_num' in dir() else 0
        current_size = os.path.getsize(file_path)
        self.conn.execute("""
            INSERT INTO sessions (id, file_path, file_size, lines_processed, total_lines,
                                  last_processed_at, status, source)
            VALUES (?, ?, ?, ?, ?, datetime('now'), 'done', ?)
            ON CONFLICT(id) DO UPDATE SET
                file_size = ?, lines_processed = ?, total_lines = ?,
                last_processed_at = datetime('now'), status = 'done'
        """, (session_id, file_path, current_size, total_lines, total_lines, source,
              current_size, total_lines, total_lines))

        self.conn.execute("""
            UPDATE ingest_log SET entries_found = ?, finished_at = datetime('now'), status = 'done'
            WHERE id = ?
        """, (entries_found, log_id))
        self.conn.commit()

        return {"status": "done", "session_id": session_id, "entries": entries_found, "lines": total_lines}

    def _save_image(self, base64_data, media_type, session_id, line_num, img_idx):
        """Save a base64 image to disk. Returns filename or None."""
        try:
            ext = "png"
            if "jpeg" in media_type or "jpg" in media_type:
                ext = "jpg"
            elif "gif" in media_type:
                ext = "gif"
            elif "webp" in media_type:
                ext = "webp"

            # Deterministic filename from content hash
            img_hash = hashlib.sha256(base64_data[:1000].encode()).hexdigest()[:12]
            filename = f"{session_id[:8]}_{line_num}_{img_idx}_{img_hash}.{ext}"
            filepath = IMAGES_DIR / filename

            if not filepath.exists():
                raw = base64.b64decode(base64_data)
                with open(filepath, "wb") as f:
                    f.write(raw)

            return filename, len(base64_data) * 3 // 4  # approx file size
        except Exception:
            return None, 0

    def _extract_entry(self, data, msg_type, session_id, line_num):
        """Extract a meaningful entry from a JSONL line."""
        if msg_type not in ("user", "assistant", "system"):
            return None

        message = data.get("message", {})
        content = message.get("content", "")
        images = []  # collected image metadata

        # Handle content blocks (list format)
        if isinstance(content, list):
            text_parts = []
            img_idx = 0
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "image":
                        src = block.get("source", {})
                        if src.get("type") == "base64" and src.get("data"):
                            media_type = src.get("media_type", "image/png")
                            filename, file_size = self._save_image(
                                src["data"], media_type, session_id, line_num, img_idx
                            )
                            if filename:
                                images.append({
                                    "filename": filename,
                                    "media_type": media_type,
                                    "file_size": file_size,
                                    "source_line": line_num,
                                })
                                text_parts.append(f"[IMAGE:{filename}]")
                                img_idx += 1
                    elif block.get("type") == "tool_use":
                        tool_name = block.get("name", "unknown")
                        tool_input = json.dumps(block.get("input", {}))[:500]
                        text_parts.append(f"[TOOL:{tool_name}] {tool_input}")
                    elif block.get("type") == "tool_result":
                        # Tool results contain output returned to Claude
                        tr_content = block.get("content", "")
                        if isinstance(tr_content, list):
                            for sub in tr_content:
                                if isinstance(sub, dict) and sub.get("type") == "text":
                                    text_parts.append(sub.get("text", "")[:2000])
                        elif isinstance(tr_content, str) and tr_content.strip():
                            text_parts.append(tr_content[:2000])
            content = "\n".join(text_parts)

        if not content or len(content.strip()) < 10:
            # Even if text is short, if there's an image, keep the entry
            if not images:
                return None

        # Truncate very long content but keep enough for context
        if len(content) > 5000:
            content = content[:5000] + "\n... [truncated]"

        content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]

        # Try to extract timestamp
        timestamp = data.get("timestamp") or data.get("message", {}).get("timestamp")
        if not timestamp:
            # Use file mod time as fallback
            timestamp = datetime.now().isoformat()

        return {
            "content": content,
            "role": msg_type,
            "session_id": session_id,
            "timestamp": timestamp,
            "source_file": session_id,
            "source_line": line_num,
            "content_hash": content_hash,
            "images": images,
        }

    def ingest_prompt_history(self, file_path):
        """Ingest prompt history (CONFIG/history.jsonl format).

        Format: {"display": "user text", "timestamp": epoch_ms, "project": "/path", "sessionId": "uuid", "pastedContents": {}}
        These are user prompts only (no assistant responses). Stored as role='user_prompt' to distinguish from full conversation entries.
        """
        file_path = str(file_path)
        source_id = "prompt-history"

        # Check if already ingested
        session = self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (source_id,)
        ).fetchone()

        start_line = 0
        if session:
            if session["status"] == "done":
                return {"status": "already_done", "source": source_id}
            start_line = session["lines_processed"] or 0

        log_id = self.conn.execute(
            "INSERT INTO ingest_log (source) VALUES (?)", (file_path,)
        ).lastrowid

        entries_found = 0
        batch = []

        with open(file_path, 'r', errors='replace') as f:
            for line_num, line in enumerate(f):
                if line_num < start_line:
                    continue

                try:
                    data = json.loads(line.strip())
                except json.JSONDecodeError:
                    continue

                display = data.get("display", "").strip()
                if not display or len(display) < 5:
                    continue

                # Convert epoch ms to ISO timestamp
                ts_ms = data.get("timestamp", 0)
                if ts_ms:
                    timestamp = datetime.fromtimestamp(ts_ms / 1000).isoformat() + "Z"
                else:
                    timestamp = None

                session_id = data.get("sessionId", "unknown")
                project = data.get("project", "")

                # Include project path in content for context
                content = display
                if project:
                    content = f"[project:{project}] {display}"

                # Handle pasted contents
                pasted = data.get("pastedContents", {})
                if pasted:
                    for fname, pcontent in pasted.items():
                        if isinstance(pcontent, str) and len(pcontent) > 10:
                            content += f"\n[pasted:{fname}] {pcontent[:2000]}"

                # Truncate
                if len(content) > 5000:
                    content = content[:5000]

                content_hash = hashlib.sha256(content.encode()).hexdigest()

                batch.append({
                    "content": content,
                    "role": "user_prompt",
                    "session_id": session_id,
                    "timestamp": timestamp,
                    "source_file": "prompt-history",
                    "source_line": line_num,
                    "content_hash": content_hash,
                })
                entries_found += 1

                if len(batch) >= 1000:
                    self._insert_batch(batch)
                    batch = []
                    self.conn.execute("""
                        INSERT INTO sessions (id, file_path, lines_processed, status)
                        VALUES (?, ?, ?, 'processing')
                        ON CONFLICT(id) DO UPDATE SET lines_processed = ?, status = 'processing'
                    """, (source_id, file_path, line_num + 1, line_num + 1))
                    self.conn.commit()

        if batch:
            self._insert_batch(batch)

        total_lines = line_num + 1 if 'line_num' in dir() else 0
        self.conn.execute("""
            INSERT INTO sessions (id, file_path, lines_processed, total_lines,
                                  last_processed_at, status)
            VALUES (?, ?, ?, ?, datetime('now'), 'done')
            ON CONFLICT(id) DO UPDATE SET
                lines_processed = ?, total_lines = ?,
                last_processed_at = datetime('now'), status = 'done'
        """, (source_id, file_path, total_lines, total_lines, total_lines, total_lines))

        self.conn.execute("""
            UPDATE ingest_log SET entries_found = ?, finished_at = datetime('now'), status = 'done'
            WHERE id = ?
        """, (entries_found, log_id))
        self.conn.commit()

        return {"status": "done", "source": source_id, "entries": entries_found, "lines": total_lines}

    def ingest_copilot_jsonl(self, file_path):
        """Ingest a GitHub Copilot CLI session JSONL file.
        Format: {type: "user.message"|"assistant.message"|..., data: {content: "..."}, timestamp: "..."}
        Supports both <uuid>.jsonl and <uuid>/events.jsonl layouts.
        """
        file_path = str(file_path)
        p = Path(file_path)
        # For <uuid>/events.jsonl, use parent dir name as session ID
        if p.stem == "events":
            session_id = p.parent.name
        else:
            session_id = p.stem

        # Check if already done — but allow re-ingest if file has grown
        existing = self.conn.execute("SELECT status, lines_processed FROM sessions WHERE id = ?", (session_id,)).fetchone()
        start_line = 0
        if existing and existing["status"] == "done":
            prev_lines = existing["lines_processed"] or 0
            current_lines = sum(1 for _ in open(file_path, "r", encoding="utf-8", errors="replace"))
            if current_lines <= prev_lines:
                return {"status": "already_done", "session_id": session_id, "entries": 0}
            start_line = prev_lines

        entries_found = 0
        batch = []
        line_num = -1

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            for line_num, line in enumerate(f):
                if line_num < start_line:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = data.get("type", "")
                timestamp = data.get("timestamp", "")
                inner = data.get("data", {})
                content = ""
                role = ""

                if entry_type == "user.message":
                    content = inner.get("content", "")
                    role = "user"
                elif entry_type == "assistant.message":
                    content = inner.get("content", "")
                    role = "assistant"
                    # Append tool call info
                    tool_reqs = inner.get("toolRequests", [])
                    if tool_reqs:
                        tools_str = "\n".join(f"[TOOL:{t.get('name', '?')}]" for t in tool_reqs)
                        content = f"{content}\n{tools_str}" if content else tools_str
                elif entry_type == "tool.execution_complete":
                    tool_name = inner.get("name", "tool")
                    result = inner.get("result", "")
                    content = f"[TOOL:{tool_name}] Result: {str(result)[:500]}"
                    role = "tool"
                else:
                    continue

                if not content:
                    continue

                content_hash = hashlib.sha256(f"{session_id}:{line_num}:{content}".encode()).hexdigest()
                batch.append({
                    "content": content,
                    "role": role,
                    "session_id": session_id,
                    "timestamp": timestamp,
                    "source_file": file_path,
                    "source_line": line_num,
                    "content_hash": content_hash,
                    "source": "copilot",
                })
                entries_found += 1

        if batch:
            self._insert_batch(batch)

        total_lines = line_num + 1 if line_num >= 0 else 0
        self.conn.execute("""
            INSERT INTO sessions (id, file_path, lines_processed, total_lines, last_processed_at, status, source)
            VALUES (?, ?, ?, ?, datetime('now'), 'done', 'copilot')
            ON CONFLICT(id) DO UPDATE SET
                lines_processed = ?, total_lines = ?, last_processed_at = datetime('now'), status = 'done'
        """, (session_id, file_path, total_lines, total_lines, total_lines, total_lines))
        self.conn.commit()

        return {"status": "done", "session_id": session_id, "entries": entries_found, "lines": total_lines}

    def ingest_codex_jsonl(self, file_path):
        """Ingest an OpenAI Codex CLI session JSONL file.
        Format: {type: "response_item", payload: {role: "user"|"assistant", content: [{type: "input_text", text: "..."}]}}
        """
        file_path = str(file_path)
        # Extract session UUID from filename: rollout-YYYY-MM-DDThh-mm-ss-UUID.jsonl
        fname = Path(file_path).stem
        m = re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$', fname)
        session_id = m.group(1) if m else fname

        existing = self.conn.execute("SELECT status, lines_processed FROM sessions WHERE id = ?", (session_id,)).fetchone()
        start_line = 0
        if existing and existing["status"] == "done":
            prev_lines = existing["lines_processed"] or 0
            current_lines = sum(1 for _ in open(file_path, "r", encoding="utf-8", errors="replace"))
            if current_lines <= prev_lines:
                return {"status": "already_done", "session_id": session_id, "entries": 0}
            start_line = prev_lines

        entries_found = 0
        batch = []
        line_num = -1

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            for line_num, line in enumerate(f):
                if line_num < start_line:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = data.get("type", "")
                timestamp = data.get("timestamp", "")
                payload = data.get("payload", {})

                if entry_type != "response_item":
                    continue

                role_raw = payload.get("role", "")

                # Skip developer/system messages (huge prompts, permissions, etc.)
                if role_raw in ("developer", "system"):
                    continue

                content_blocks = payload.get("content") or []

                # Extract text from content blocks
                texts = []
                for block in content_blocks:
                    if isinstance(block, dict):
                        text = block.get("text", "")
                        if text:
                            texts.append(text)
                    elif isinstance(block, str):
                        texts.append(block)

                content = "\n".join(texts)
                if not content:
                    continue

                # Skip system/environment context injected as user messages
                if content.startswith("<environment_context>") or content.startswith("<permissions"):
                    continue

                # Map roles
                if role_raw in ("user",):
                    role = "user"
                elif role_raw in ("assistant",):
                    role = "assistant"
                else:
                    role = role_raw or "unknown"

                content_hash = hashlib.sha256(f"{session_id}:{line_num}:{content}".encode()).hexdigest()
                batch.append({
                    "content": content,
                    "role": role,
                    "session_id": session_id,
                    "timestamp": timestamp,
                    "source_file": file_path,
                    "source_line": line_num,
                    "content_hash": content_hash,
                    "source": "codex",
                })
                entries_found += 1

        if batch:
            self._insert_batch(batch)

        total_lines = line_num + 1 if line_num >= 0 else 0
        self.conn.execute("""
            INSERT INTO sessions (id, file_path, lines_processed, total_lines, last_processed_at, status, source)
            VALUES (?, ?, ?, ?, datetime('now'), 'done', 'codex')
            ON CONFLICT(id) DO UPDATE SET
                lines_processed = ?, total_lines = ?, last_processed_at = datetime('now'), status = 'done'
        """, (session_id, file_path, total_lines, total_lines, total_lines, total_lines))
        self.conn.commit()

        return {"status": "done", "session_id": session_id, "entries": entries_found, "lines": total_lines}

    def _insert_batch(self, batch):
        """Insert a batch of entries, skipping duplicates. Also saves images."""
        for entry in batch:
            try:
                cursor = self.conn.execute("""
                    INSERT OR IGNORE INTO entries
                    (content, role, session_id, timestamp, source_file, source_line, content_hash, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    entry["content"], entry["role"], entry["session_id"],
                    entry["timestamp"], entry["source_file"], entry["source_line"],
                    entry["content_hash"], entry.get("source", "claude_code")
                ))

                # Save associated images
                if cursor.lastrowid and entry.get("images"):
                    entry_id = cursor.lastrowid
                    for img in entry["images"]:
                        try:
                            self.conn.execute("""
                                INSERT INTO images
                                (entry_id, session_id, filename, media_type, file_size, source_line)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, (
                                entry_id, entry["session_id"],
                                img["filename"], img["media_type"],
                                img.get("file_size", 0), img.get("source_line", 0)
                            ))
                        except Exception:
                            pass  # Image insert failed, entry still saved

            except sqlite3.IntegrityError:
                pass  # Duplicate — skip

    # ── Auto-classify ───────────────────────────────────────────

    def classify_entry(self, content):
        """Classify content to relevant agents based on keyword matching."""
        content_lower = content.lower()
        scores = {}

        for agent, keywords in AGENT_TAGS.items():
            score = sum(1 for kw in keywords if kw in content_lower)
            if score > 0:
                scores[agent] = score

        # Return agents sorted by relevance score
        return sorted(scores.items(), key=lambda x: -x[1])

    # ── Lifecycle management ────────────────────────────────────

    def run_lifecycle(self):
        """Auto-manage ACTIVE → STALE → ARCHIVED lifecycle."""
        now = datetime.now()
        stale_cutoff = (now - timedelta(hours=24)).isoformat()
        archive_cutoff = (now - timedelta(days=2)).isoformat()
        delete_cutoff = (now - timedelta(days=5)).isoformat()

        # ACTIVE → STALE (>24h old, not updated)
        stale = self.conn.execute("""
            UPDATE knowledge SET status = 'STALE', updated_at = datetime('now')
            WHERE status = 'ACTIVE' AND updated_at < ?
        """, (stale_cutoff,)).rowcount

        # STALE → ARCHIVED (>2 days)
        archived = self.conn.execute("""
            UPDATE knowledge SET status = 'ARCHIVED', updated_at = datetime('now')
            WHERE status = 'STALE' AND updated_at < ?
        """, (archive_cutoff,)).rowcount

        # ARCHIVED → DELETE (>5 days)
        deleted = self.conn.execute("""
            DELETE FROM knowledge WHERE status = 'ARCHIVED' AND updated_at < ?
        """, (delete_cutoff,)).rowcount

        self.conn.commit()
        return {"stale": stale, "archived": archived, "deleted": deleted}

    # ── Stats ───────────────────────────────────────────────────

    def stats(self):
        """Get database statistics."""
        entries = self.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        knowledge = self.conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        sessions = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        sessions_done = self.conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE status = 'done'"
        ).fetchone()[0]

        by_agent = {}
        for row in self.conn.execute(
            "SELECT agent, COUNT(*) as cnt FROM knowledge GROUP BY agent"
        ).fetchall():
            by_agent[row["agent"]] = row["cnt"]

        by_status = {}
        for row in self.conn.execute(
            "SELECT status, COUNT(*) as cnt FROM knowledge GROUP BY status"
        ).fetchall():
            by_status[row["status"]] = row["cnt"]

        return {
            "entries": entries,
            "knowledge": knowledge,
            "sessions_total": sessions,
            "sessions_done": sessions_done,
            "by_agent": by_agent,
            "by_status": by_status,
        }

    # ── Topic Intelligence ─────────────────────────────────────

    def topic_deep_search(self, topic, limit=200):
        """Search for a topic across all entries, grouped by session with context."""
        topic_sanitized = self._sanitize_fts(topic)

        # Get all matching entries
        rows = self.conn.execute("""
            SELECT e.id, e.content, e.role, e.session_id, e.timestamp, e.source_line,
                   rank
            FROM entries_fts fts
            JOIN entries e ON e.id = fts.rowid
            WHERE entries_fts MATCH ?
            ORDER BY e.timestamp ASC
            LIMIT ?
        """, (topic_sanitized, limit)).fetchall()

        if not rows:
            return {"sessions": [], "total_hits": 0, "topic": topic}

        # Group by session
        sessions = {}
        for r in rows:
            sid = r["session_id"]
            if sid not in sessions:
                sessions[sid] = {
                    "session_id": sid,
                    "first_ts": r["timestamp"],
                    "last_ts": r["timestamp"],
                    "entries": [],
                    "user_msgs": [],
                    "assistant_msgs": [],
                    "tools_used": set(),
                }
            s = sessions[sid]
            s["last_ts"] = r["timestamp"]
            s["entries"].append(dict(r))

            content = r["content"]
            if r["role"] == "user" and not content.startswith("[TOOL:"):
                # Clean user message
                clean = content.strip()
                if len(clean) > 20 and not clean.startswith("<"):
                    s["user_msgs"].append(clean[:500])
            elif r["role"] == "assistant":
                if content.startswith("[TOOL:"):
                    tool_name = content.split("]")[0].replace("[TOOL:", "")
                    s["tools_used"].add(tool_name)
                else:
                    clean = content.strip()
                    if len(clean) > 30:
                        s["assistant_msgs"].append(clean[:500])

        # Convert sets to lists for JSON
        session_list = []
        for sid, s in sorted(sessions.items(), key=lambda x: x[1]["first_ts"]):
            s["tools_used"] = list(s["tools_used"])
            s["hit_count"] = len(s["entries"])
            del s["entries"]  # Don't send raw entries, too large
            session_list.append(s)

        return {
            "topic": topic,
            "total_hits": len(rows),
            "sessions_count": len(session_list),
            "sessions": session_list,
        }

    def topic_extract_narrative(self, topic, max_chars=4000):
        """Build a readable narrative of everything known about a topic."""
        data = self.topic_deep_search(topic, limit=300)

        if not data["sessions"]:
            return f"No data found for topic: {topic}"

        lines = [
            f"# Topic: {topic}",
            f"",
            f"**Coverage:** {data['total_hits']} mentions across {data['sessions_count']} sessions",
            f"**Timeline:** {data['sessions'][0]['first_ts'][:10]} → {data['sessions'][-1]['last_ts'][:10]}",
            f"",
        ]

        for s in data["sessions"]:
            date = s["first_ts"][:10] if s["first_ts"] else "?"
            sid = s["session_id"][:8] if s["session_id"] else "?"
            lines.append(f"## {date} — Session {sid}… ({s['hit_count']} hits)")

            if s["tools_used"]:
                lines.append(f"Tools: {', '.join(s['tools_used'][:10])}")

            # Show key user questions
            for msg in s["user_msgs"][:3]:
                short = msg.replace("\n", " ")[:200]
                lines.append(f"  [user] {short}")

            # Show key assistant responses
            for msg in s["assistant_msgs"][:3]:
                short = msg.replace("\n", " ")[:200]
                lines.append(f"  [assistant] {short}")

            lines.append("")

            # Check length
            if len("\n".join(lines)) > max_chars:
                lines.append("... (truncated, use memory_search for full results)")
                break

        return "\n".join(lines)

    def topic_list_all(self, min_hits=5, limit=50):
        """Discover topics by finding frequently mentioned terms across sessions.
        Returns terms that appear in multiple sessions."""

        # Get high-frequency meaningful words from user messages
        rows = self.conn.execute("""
            SELECT content FROM entries
            WHERE role = 'user' AND length(content) > 20
            AND content NOT LIKE '[TOOL:%'
            AND content NOT LIKE '<%'
            ORDER BY timestamp DESC
            LIMIT 2000
        """).fetchall()

        # Simple frequency analysis
        import re
        from collections import Counter

        word_freq = Counter()
        stop_words = {
            'the', 'and', 'for', 'that', 'this', 'with', 'from', 'are', 'was',
            'have', 'has', 'had', 'not', 'but', 'what', 'all', 'can', 'will',
            'you', 'your', 'our', 'they', 'them', 'been', 'would', 'could',
            'should', 'there', 'their', 'which', 'about', 'into', 'just',
            'also', 'some', 'than', 'then', 'when', 'where', 'how', 'let',
            'use', 'make', 'like', 'need', 'want', 'get', 'got', 'see',
            'now', 'here', 'file', 'run', 'try', 'one', 'two', 'new',
        }

        for r in rows:
            text = r["content"].lower()
            # Extract multi-word phrases and single words
            words = re.findall(r'[a-z][a-z-]{2,}', text)
            for w in words:
                if w not in stop_words and len(w) > 3:
                    word_freq[w] += 1

        # Filter to terms with enough hits
        topics = [(word, count) for word, count in word_freq.most_common(200)
                  if count >= min_hits][:limit]

        return topics

    # ── Projects ───────────────────────────────────────────────────

    def _resolve_project(self, name_or_id):
        """Resolve project by name or numeric ID string."""
        if isinstance(name_or_id, int) or (isinstance(name_or_id, str) and name_or_id.isdigit()):
            return self.conn.execute(
                "SELECT * FROM projects WHERE id = ?", (int(name_or_id),)
            ).fetchone()
        return self.conn.execute(
            "SELECT * FROM projects WHERE name = ? COLLATE NOCASE", (name_or_id,)
        ).fetchone()

    def create_project(self, name, description=None, tags=None, color=None):
        """Create a new project."""
        color = color or "#58a6ff"
        try:
            cursor = self.conn.execute("""
                INSERT INTO projects (name, description, tags, color)
                VALUES (?, ?, ?, ?)
            """, (name, description, tags, color))
            self.conn.commit()
            return {"action": "created", "id": cursor.lastrowid, "name": name}
        except sqlite3.IntegrityError:
            return {"action": "exists", "name": name}

    def update_project(self, project_id, **kwargs):
        """Update project fields. Only non-None kwargs are applied."""
        allowed = {"name", "description", "tags", "color", "status"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return {"action": "no_changes", "id": project_id}

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [project_id]

        self.conn.execute(
            f"UPDATE projects SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
            values
        )
        self.conn.commit()
        return {"action": "updated", "id": project_id}

    def delete_project(self, project_id):
        """Delete a project and its session mappings (CASCADE)."""
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self.conn.commit()
        return {"action": "deleted", "id": project_id}

    def get_project(self, project_id):
        """Get a single project with session count."""
        row = self.conn.execute("""
            SELECT p.*,
                   (SELECT COUNT(*) FROM project_sessions ps WHERE ps.project_id = p.id) as session_count
            FROM projects p WHERE p.id = ?
        """, (project_id,)).fetchone()
        return dict(row) if row else None

    def list_projects(self, status="active", limit=50):
        """List all projects with session counts."""
        sql = """
            SELECT p.*,
                   (SELECT COUNT(*) FROM project_sessions ps WHERE ps.project_id = p.id) as session_count
            FROM projects p
        """
        params = []
        if status:
            sql += " WHERE p.status = ?"
            params.append(status)
        sql += " ORDER BY p.updated_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def assign_session(self, project_id, session_id, notes=None):
        """Assign a session to a project. Idempotent."""
        try:
            self.conn.execute("""
                INSERT OR IGNORE INTO project_sessions (project_id, session_id, notes)
                VALUES (?, ?, ?)
            """, (project_id, session_id, notes))
            self.conn.commit()
            changed = self.conn.execute("SELECT changes()").fetchone()[0]
            return {"action": "assigned" if changed else "already_assigned",
                    "project_id": project_id, "session_id": session_id}
        except Exception as e:
            return {"action": "error", "error": str(e)}

    def unassign_session(self, project_id, session_id):
        """Remove a session from a project."""
        self.conn.execute(
            "DELETE FROM project_sessions WHERE project_id = ? AND session_id = ?",
            (project_id, session_id)
        )
        self.conn.commit()
        return {"action": "unassigned", "project_id": project_id, "session_id": session_id}

    def get_project_sessions(self, project_id, limit=200):
        """Get all sessions assigned to a project with metadata."""
        rows = self.conn.execute("""
            SELECT ps.session_id, ps.notes, ps.added_at,
                   s.file_path, s.total_lines, s.last_processed_at,
                   (SELECT COUNT(*) FROM entries e WHERE e.session_id = ps.session_id) as entry_count,
                   (SELECT MIN(e.timestamp) FROM entries e WHERE e.session_id = ps.session_id) as first_ts,
                   (SELECT MAX(e.timestamp) FROM entries e WHERE e.session_id = ps.session_id) as last_ts
            FROM project_sessions ps
            LEFT JOIN sessions s ON s.id = ps.session_id
            WHERE ps.project_id = ?
            ORDER BY ps.added_at DESC
            LIMIT ?
        """, (project_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_session_projects(self, session_id):
        """Get all projects a session belongs to."""
        rows = self.conn.execute("""
            SELECT p.* FROM projects p
            JOIN project_sessions ps ON ps.project_id = p.id
            WHERE ps.session_id = ?
            ORDER BY p.name
        """, (session_id,)).fetchall()
        return [dict(r) for r in rows]

    def project_search(self, project_id, query, role=None, limit=20):
        """FTS search scoped to a project's sessions."""
        query = self._sanitize_fts(query)
        sql = """
            SELECT e.id, e.content, e.role, e.session_id, e.timestamp, e.source_file, rank
            FROM entries_fts fts
            JOIN entries e ON e.id = fts.rowid
            WHERE entries_fts MATCH ?
            AND e.session_id IN (SELECT session_id FROM project_sessions WHERE project_id = ?)
        """
        params = [query, project_id]
        if role:
            sql += " AND e.role = ?"
            params.append(role)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def project_stats(self, project_id):
        """Get aggregate stats for a project."""
        session_count = self.conn.execute(
            "SELECT COUNT(*) FROM project_sessions WHERE project_id = ?", (project_id,)
        ).fetchone()[0]

        entry_count = self.conn.execute("""
            SELECT COUNT(*) FROM entries
            WHERE session_id IN (SELECT session_id FROM project_sessions WHERE project_id = ?)
        """, (project_id,)).fetchone()[0]

        obs_count = self.conn.execute("""
            SELECT COUNT(*) FROM observations
            WHERE session_id IN (SELECT session_id FROM project_sessions WHERE project_id = ?)
        """, (project_id,)).fetchone()[0]

        date_range = self.conn.execute("""
            SELECT MIN(e.timestamp) as first_ts, MAX(e.timestamp) as last_ts
            FROM entries e
            WHERE e.session_id IN (SELECT session_id FROM project_sessions WHERE project_id = ?)
        """, (project_id,)).fetchone()

        by_role = {}
        for r in self.conn.execute("""
            SELECT role, COUNT(*) as cnt FROM entries
            WHERE session_id IN (SELECT session_id FROM project_sessions WHERE project_id = ?)
            GROUP BY role
        """, (project_id,)).fetchall():
            by_role[r["role"]] = r["cnt"]

        return {
            "sessions": session_count,
            "entries": entry_count,
            "observations": obs_count,
            "first_ts": date_range["first_ts"] if date_range else None,
            "last_ts": date_range["last_ts"] if date_range else None,
            "by_role": by_role,
        }

    def project_observations(self, project_id, obs_type=None, limit=50):
        """Get observations scoped to a project's sessions."""
        sql = """
            SELECT o.* FROM observations o
            WHERE o.session_id IN (SELECT session_id FROM project_sessions WHERE project_id = ?)
        """
        params = [project_id]
        if obs_type:
            sql += " AND o.type = ?"
            params.append(obs_type)
        sql += " ORDER BY o.confidence DESC, o.created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def suggest_project_sessions(self, project_id, limit=20):
        """Auto-suggest sessions that might belong to a project based on name/tags."""
        project = self.get_project(project_id)
        if not project:
            return []

        terms = [project["name"]]
        if project.get("tags"):
            terms.extend(t.strip() for t in project["tags"].split(",") if t.strip())

        fts_query = " OR ".join(f'"{self._sanitize_fts(t)}"' for t in terms if t)
        if not fts_query:
            return []

        try:
            rows = self.conn.execute("""
                SELECT e.session_id, COUNT(*) as match_count,
                       MIN(e.timestamp) as first_ts, MAX(e.timestamp) as last_ts
                FROM entries_fts fts
                JOIN entries e ON e.id = fts.rowid
                WHERE entries_fts MATCH ?
                AND e.session_id NOT IN (
                    SELECT session_id FROM project_sessions WHERE project_id = ?
                )
                AND e.session_id IS NOT NULL
                GROUP BY e.session_id
                ORDER BY match_count DESC
                LIMIT ?
            """, (fts_query, project_id, limit)).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def bulk_assign_sessions(self, project_id, session_ids):
        """Assign multiple sessions to a project."""
        assigned = 0
        already = 0
        for sid in session_ids:
            r = self.assign_session(project_id, sid)
            if r["action"] == "assigned":
                assigned += 1
            else:
                already += 1
        return {"assigned": assigned, "already_assigned": already}

    def close(self):
        self.conn.close()


if __name__ == "__main__":
    engine = MemoryEngine()
    print(f"[+] Memory Engine initialized at {engine.db_path}")
    print(f"[+] Stats: {json.dumps(engine.stats(), indent=2)}")
