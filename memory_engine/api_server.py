#!/usr/bin/env python3
"""
MEMORY ENGINE API SERVER — JSON API backend for the Next.js dashboard.
Runs on port 37888. All endpoints return JSON.
No HTML rendering — the Next.js app at localhost:3000 is the UI.
"""

import sqlite3
import json
import os
import re
import sys
import shutil
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DB_PATH, VIEWER_PORT

PORT = VIEWER_PORT


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


class APIHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # Silence request logs

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        routes = {
            "": self._handle_root,
            "/api/stats": self._handle_stats,
            "/api/search": self._handle_search,
            "/api/latest": self._handle_latest,
            "/api/session": self._handle_session,
            "/api/sessions": self._handle_sessions,
            "/api/session/digest": self._handle_session_digest,
            "/api/session/summary": self._handle_session_summary_get,
            "/api/pulse": self._handle_pulse,
            "/api/export": self._handle_export,
            "/api/launch": self._handle_launch,
            "/api/tools": self._handle_tools,
            "/api/setup/detect": self._handle_setup_detect,
            "/api/setup/test": self._handle_setup_test,
            "/api/setup/config": self._handle_setup_config,
        }

        handler = routes.get(path)
        if handler:
            handler(params)
        else:
            self.send_json({"error": "not found", "path": path}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length).decode("utf-8")

        if path == "/api/session/summary":
            self._handle_session_summary_post(post_data)
        elif path == "/api/setup/install":
            self._handle_setup_install(post_data)
        elif path == "/api/setup/ingest":
            self._handle_setup_ingest()
        else:
            self.send_json({"error": "not found"}, 404)

    # ── Root ─────────────────────────────────────────────────────────

    def _handle_root(self, params):
        self.send_json({
            "name": "Memory Engine API",
            "version": "2.1.0",
            "docs": "Start the Next.js dashboard: cd web && npm run dev",
            "endpoints": [
                "/api/stats", "/api/search?q=...", "/api/latest",
                "/api/sessions", "/api/session?id=...",
                "/api/session/digest?id=...", "/api/session/summary?id=...",
                "/api/pulse", "/api/export?id=...",
            ],
        })

    # ── Stats ────────────────────────────────────────────────────────

    def _handle_stats(self, params):
        source = params.get("source", [""])[0]
        conn = get_db()
        if source:
            total = conn.execute("SELECT COUNT(*) FROM entries WHERE source = ?", (source,)).fetchone()[0]
            sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE status='done' AND source = ?", (source,)).fetchone()[0]
            roles = {r[0]: r[1] for r in conn.execute("SELECT role, COUNT(*) FROM entries WHERE source = ? GROUP BY role", (source,)).fetchall()}
        else:
            total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE status='done'").fetchone()[0]
            roles = {r[0]: r[1] for r in conn.execute("SELECT role, COUNT(*) FROM entries GROUP BY role").fetchall()}
        conn.close()
        self.send_json({"entries": total, "sessions": sessions, "by_role": roles})

    # ── Search ───────────────────────────────────────────────────────

    def _handle_search(self, params):
        q = params.get("q", [""])[0]
        source = params.get("source", [""])[0]
        role = params.get("role", [""])[0]
        limit = min(int(params.get("limit", ["20"])[0] or 20), 100)

        if not q:
            self.send_json([])
            return

        conn = get_db()
        try:
            safe_q = q
            for ch in ['"', "'", "(", ")", "*", ":", ";", "!", "?"]:
                safe_q = safe_q.replace(ch, " ")
            safe_q = " ".join(w for w in safe_q.split() if len(w) > 1)
            if not safe_q:
                self.send_json([])
                conn.close()
                return

            sql = """
                SELECT e.id, e.content, e.role, e.session_id, e.timestamp, e.source_line
                FROM entries_fts fts
                JOIN entries e ON e.id = fts.rowid
                WHERE entries_fts MATCH ?
            """
            sql_params = [safe_q]
            if source:
                sql += " AND e.source = ?"
                sql_params.append(source)
            if role:
                sql += " AND e.role = ?"
                sql_params.append(role)
            sql += " ORDER BY rank LIMIT ?"
            sql_params.append(limit)

            rows = conn.execute(sql, sql_params).fetchall()
            results = [dict(r) for r in rows]
        except Exception:
            results = []
        conn.close()
        self.send_json(results)

    # ── Latest ───────────────────────────────────────────────────────

    def _handle_latest(self, params):
        source = params.get("source", [""])[0]
        role = params.get("role", [""])[0]
        limit = min(int(params.get("limit", ["20"])[0] or 20), 100)

        conn = get_db()
        sql = "SELECT id, content, role, session_id, timestamp, source_line FROM entries WHERE 1=1"
        sql_params = []
        if source:
            sql += " AND source = ?"
            sql_params.append(source)
        if role:
            sql += " AND role = ?"
            sql_params.append(role)
        sql += " ORDER BY id DESC LIMIT ?"
        sql_params.append(limit)

        rows = conn.execute(sql, sql_params).fetchall()
        conn.close()
        self.send_json([dict(r) for r in rows])

    # ── Session Detail ───────────────────────────────────────────────

    def _handle_session(self, params):
        session_id = params.get("id", [""])[0]
        if not session_id:
            self.send_json({"error": "id required"}, 400)
            return

        page = int(params.get("page", ["1"])[0] or 1)
        per_page = min(int(params.get("per_page", ["100"])[0] or 100), 500)
        offset = (page - 1) * per_page

        conn = get_db()
        total = conn.execute("SELECT COUNT(*) FROM entries WHERE session_id = ?", (session_id,)).fetchone()[0]
        rows = conn.execute("""
            SELECT content, role, timestamp, source_line FROM entries
            WHERE session_id = ? ORDER BY source_line ASC LIMIT ? OFFSET ?
        """, (session_id, per_page, offset)).fetchall()

        meta = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        conn.close()

        result = {
            "session_id": session_id,
            "total_entries": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page,
        }
        if meta:
            result["meta"] = {k: meta[k] for k in meta.keys()}
        result["entries"] = [dict(r) for r in rows]
        self.send_json(result)

    # ── Sessions List ────────────────────────────────────────────────

    def _handle_sessions(self, params):
        limit = min(int(params.get("limit", ["20"])[0] or 20), 100)
        off = int(params.get("offset", ["0"])[0] or 0)
        q = params.get("q", [""])[0]
        source = params.get("source", [""])[0]

        conn = get_db()
        conditions = []
        sql_params = []

        if source:
            conditions.append("s.source = ?")
            sql_params.append(source)

        if q:
            conditions.append("(s.id LIKE ? OR EXISTS (SELECT 1 FROM entries_fts fts JOIN entries e2 ON e2.id = fts.rowid WHERE e2.session_id = s.id AND entries_fts MATCH ?))")
            sql_params.extend([f"%{q}%", q])

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        rows = conn.execute(f"""
            SELECT s.id, s.status, s.last_processed_at, s.source, s.summary,
                   COUNT(e.id) as entry_count,
                   MIN(e.timestamp) as started_at,
                   MAX(e.timestamp) as ended_at
            FROM sessions s LEFT JOIN entries e ON e.session_id = s.id
            {where}
            GROUP BY s.id ORDER BY s.last_processed_at DESC LIMIT ? OFFSET ?
        """, sql_params + [limit, off]).fetchall()

        if source:
            total = conn.execute("SELECT COUNT(*) FROM sessions WHERE source = ?", (source,)).fetchone()[0]
        else:
            total = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        conn.close()

        sessions = []
        for r in rows:
            s_obj = {
                "id": r["id"],
                "status": r["status"] or "done",
                "started_at": r["started_at"] or "",
                "ended_at": r["ended_at"] or "",
                "entries": r["entry_count"] or 0,
                "source": r["source"] or "claude_code",
            }
            if r["summary"]:
                s_obj["summary"] = r["summary"]
            sessions.append(s_obj)
        self.send_json({"total": total, "sessions": sessions})

    # ── Session Digest ───────────────────────────────────────────────

    def _handle_session_digest(self, params):
        session_id = params.get("id", [""])[0]
        if not session_id:
            self.send_json({"error": "id required"}, 400)
            return

        conn = get_db()
        meta = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not meta:
            conn.close()
            self.send_json({"error": "session not found"}, 404)
            return

        rows = conn.execute("""
            SELECT id, content, role, timestamp, source_line
            FROM entries WHERE session_id = ? ORDER BY source_line ASC
        """, (session_id,)).fetchall()
        conn.close()

        entries = [dict(r) for r in rows]
        if not entries:
            self.send_json({"session_id": session_id, "segments": [], "stats": {}})
            return

        # Stats
        role_counts = {}
        tool_calls = 0
        total_chars = 0
        for e in entries:
            role_counts[e["role"]] = role_counts.get(e["role"], 0) + 1
            total_chars += len(e["content"] or "")
            if (e["content"] or "").startswith("[TOOL:"):
                tool_calls += 1

        timestamps = [e["timestamp"] for e in entries if e["timestamp"]]
        stats = {
            "total_entries": len(entries),
            "by_role": role_counts,
            "tool_calls": tool_calls,
            "total_chars": total_chars,
            "time_start": timestamps[0] if timestamps else None,
            "time_end": timestamps[-1] if timestamps else None,
        }

        # Segment by user prompts
        segments = []
        current_segment = None

        for e in entries:
            content = e["content"] or ""
            is_tool = content.startswith("[TOOL:") or content.startswith('{"result":')
            is_user = e["role"] == "user" and not is_tool

            if is_user:
                if current_segment:
                    segments.append(current_segment)
                title = content[:120].replace("\n", " ").strip()
                if len(content) > 120:
                    title += "..."
                current_segment = {
                    "index": len(segments),
                    "title": title,
                    "start_line": e["source_line"],
                    "start_entry_id": e["id"],
                    "timestamp": e["timestamp"],
                    "entries": 1,
                    "tool_calls": 0,
                    "assistant_chars": 0,
                }
            elif current_segment:
                current_segment["entries"] += 1
                if is_tool:
                    current_segment["tool_calls"] += 1
                if e["role"] == "assistant" and not is_tool:
                    current_segment["assistant_chars"] += len(content)
            else:
                current_segment = {
                    "index": 0,
                    "title": "(session start)",
                    "start_line": e["source_line"],
                    "start_entry_id": e["id"],
                    "timestamp": e["timestamp"],
                    "entries": 1,
                    "tool_calls": 1 if is_tool else 0,
                    "assistant_chars": 0,
                }

        if current_segment:
            segments.append(current_segment)

        # Key moments
        assistant_entries = [
            e for e in entries
            if e["role"] == "assistant"
            and not (e["content"] or "").startswith("[TOOL:")
            and not (e["content"] or "").startswith('{"result":')
        ]
        assistant_entries.sort(key=lambda e: len(e["content"] or ""), reverse=True)
        key_moments = [
            {"source_line": e["source_line"], "preview": (e["content"] or "")[:200], "length": len(e["content"] or ""), "timestamp": e["timestamp"]}
            for e in assistant_entries[:10]
        ]

        self.send_json({
            "session_id": session_id,
            "stats": stats,
            "segments": segments,
            "segment_count": len(segments),
            "key_moments": key_moments,
        })

    # ── Session Summary ──────────────────────────────────────────────

    def _handle_session_summary_get(self, params):
        session_id = params.get("id", [""])[0]
        if not session_id:
            self.send_json({"error": "id required"}, 400)
            return
        conn = get_db()
        row = conn.execute("SELECT summary FROM sessions WHERE id = ?", (session_id,)).fetchone()
        conn.close()
        if not row:
            self.send_json({"error": "session not found"}, 404)
            return
        self.send_json({"session_id": session_id, "summary": row["summary"]})

    def _handle_session_summary_post(self, post_data):
        try:
            data = json.loads(post_data)
        except (json.JSONDecodeError, ValueError):
            self.send_json({"error": "invalid JSON"}, 400)
            return
        session_id = data.get("session_id", "")
        summary = data.get("summary", "")
        if not session_id or not summary:
            self.send_json({"error": "session_id and summary required"}, 400)
            return
        conn = get_db()
        exists = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not exists:
            conn.close()
            self.send_json({"error": "session not found"}, 404)
            return
        conn.execute("UPDATE sessions SET summary = ? WHERE id = ?", (summary, session_id))
        conn.commit()
        conn.close()
        self.send_json({"ok": True, "session_id": session_id})

    # ── Pulse (live status per source) ───────────────────────────────

    def _handle_pulse(self, params):
        conn = get_db()
        sources = ["claude_code", "copilot", "codex"]
        pulse = {}

        for src in sources:
            session = conn.execute("""
                SELECT s.id, s.status, s.summary, s.source,
                       COUNT(e.id) as entry_count,
                       MIN(e.timestamp) as started_at,
                       MAX(e.timestamp) as ended_at
                FROM sessions s LEFT JOIN entries e ON e.session_id = s.id
                WHERE s.source = ?
                GROUP BY s.id ORDER BY s.last_processed_at DESC LIMIT 1
            """, (src,)).fetchone()

            if not session:
                pulse[src] = {"active": False}
                continue

            is_live = False
            if session["ended_at"]:
                try:
                    last_ts = session["ended_at"].rstrip("Z")
                    if "+" not in last_ts and "-" not in last_ts[11:]:
                        last_dt = datetime.fromisoformat(last_ts).replace(tzinfo=timezone.utc)
                    else:
                        last_dt = datetime.fromisoformat(last_ts)
                    is_live = (datetime.now(timezone.utc) - last_dt).total_seconds() < 600
                except Exception:
                    pass

            recent = conn.execute("""
                SELECT content, role, timestamp, session_id
                FROM entries
                WHERE session_id = ? AND content NOT LIKE '[TOOL:%%' AND content NOT LIKE '{\"result\":%%'
                ORDER BY source_line DESC LIMIT 5
            """, (session["id"],)).fetchall()

            pulse[src] = {
                "active": True,
                "live": is_live,
                "session_id": session["id"],
                "entries": session["entry_count"] or 0,
                "started_at": session["started_at"] or "",
                "ended_at": session["ended_at"] or "",
                "summary": session["summary"],
                "recent": [dict(r) for r in reversed(recent)],
            }

        conn.close()
        self.send_json(pulse)

    # ── Export ────────────────────────────────────────────────────────

    def _handle_export(self, params):
        session_id = params.get("id", [""])[0]
        if not session_id:
            self.send_json({"error": "id required"}, 400)
            return

        custom_dir = params.get("dir", [""])[0]
        conn = get_db()

        meta = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not meta:
            conn.close()
            self.send_json({"error": f"Session {session_id} not found"}, 404)
            return

        rows = conn.execute("""
            SELECT id, content, role, session_id, timestamp, source_file,
                   source_line, content_hash, created_at
            FROM entries WHERE session_id = ? ORDER BY source_line ASC
        """, (session_id,)).fetchall()
        conn.close()

        entries = [dict(r) for r in rows]
        meta_dict = {k: meta[k] for k in meta.keys()}

        first_ts = entries[0]["timestamp"] if entries else None
        date_str = first_ts[:10] if first_ts else datetime.now().strftime("%Y-%m-%d")

        export_data = {
            "session_id": session_id,
            "exported_at": datetime.now().isoformat(),
            "date": date_str,
            "meta": meta_dict,
            "total_entries": len(entries),
            "entries": entries,
        }

        if custom_dir:
            export_base = Path(custom_dir)
        else:
            export_base = Path(__file__).parent.parent / "export"

        export_dir = export_base / date_str
        export_dir.mkdir(parents=True, exist_ok=True)
        export_path = export_dir / f"{session_id}.json"

        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False, default=str)

        self.send_json({
            "ok": True,
            "path": str(export_path),
            "session_id": session_id,
            "date": date_str,
            "entries": len(entries),
        })

    # ── Tools / Launch ────────────────────────────────────────────────

    TOOLS = {
        "claude_code": {
            "name": "Claude Code",
            "command": "claude",
            "check": ["claude", "--version"],
            "install": {
                "win32": "npm install -g @anthropic-ai/claude-code",
                "darwin": "npm install -g @anthropic-ai/claude-code",
                "linux": "npm install -g @anthropic-ai/claude-code",
            },
        },
        "codex": {
            "name": "Codex CLI",
            "command": "codex",
            "check": ["codex", "--version"],
            "install": {
                "win32": "npm install -g @openai/codex",
                "darwin": "npm install -g @openai/codex",
                "linux": "npm install -g @openai/codex",
            },
        },
        "copilot": {
            "name": "Copilot CLI",
            "command": "github-copilot-cli",
            "alt_commands": ["ghcs", "gh copilot"],
            "check": ["github-copilot-cli", "--version"],
            "install": {
                "win32": "gh extension install github/gh-copilot",
                "darwin": "gh extension install github/gh-copilot",
                "linux": "gh extension install github/gh-copilot",
            },
        },
    }

    def _handle_tools(self, params):
        """GET /api/tools — Detect installed CLI tools and platform info."""
        platform = sys.platform  # win32, darwin, linux

        results = {}
        for key, tool in self.TOOLS.items():
            # Check primary command and alternates
            found_cmd = None
            if shutil.which(tool["command"]):
                found_cmd = tool["command"]
            else:
                for alt in tool.get("alt_commands", []):
                    if shutil.which(alt.split()[0]):
                        found_cmd = alt
                        break

            version = None
            if found_cmd:
                try:
                    check_cmd = [found_cmd, "--version"] if " " not in found_cmd else found_cmd.split() + ["--version"]
                    r = subprocess.run(check_cmd, capture_output=True, text=True, timeout=5)
                    version = r.stdout.strip().split("\n")[0][:50] if r.returncode == 0 else None
                except Exception:
                    pass

            results[key] = {
                "name": tool["name"],
                "command": found_cmd or tool["command"],
                "installed": found_cmd is not None,
                "version": version,
                "install_cmd": tool["install"].get(platform, tool["install"]["linux"]),
            }

        self.send_json({"platform": platform, "tools": results})

    def _handle_launch(self, params):
        """GET /api/launch?tool=claude_code — Launch a CLI tool in an external terminal."""
        tool_key = params.get("tool", [""])[0]
        if tool_key not in self.TOOLS:
            self.send_json({"error": f"Unknown tool: {tool_key}. Valid: {list(self.TOOLS.keys())}"}, 400)
            return

        tool = self.TOOLS[tool_key]
        cmd = tool["command"]
        platform = sys.platform

        try:
            if platform == "win32":
                # npm tools are .cmd files — must run through cmd /k
                wt = shutil.which("wt")
                if wt:
                    subprocess.Popen(["wt", "new-tab", "--title", tool["name"], "cmd", "/k", cmd])
                else:
                    subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", cmd])
            elif platform == "darwin":
                # macOS: open Terminal.app with command
                script = f'tell application "Terminal" to do script "{cmd}"'
                subprocess.Popen(["osascript", "-e", script])
            else:
                # Linux: try common terminal emulators
                for term in ["x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "xterm"]:
                    if shutil.which(term):
                        if term == "gnome-terminal":
                            subprocess.Popen([term, "--", cmd])
                        elif term == "konsole":
                            subprocess.Popen([term, "-e", cmd])
                        else:
                            subprocess.Popen([term, "-e", cmd])
                        break
                else:
                    self.send_json({"error": "No terminal emulator found"}, 500)
                    return

            self.send_json({"ok": True, "tool": tool_key, "command": cmd, "platform": platform})
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    # ── Setup ────────────────────────────────────────────────────────

    def _handle_setup_detect(self, params):
        from config import _get_claude_config_dir, _get_engine_dir, JSONL_DIR
        python_path = sys.executable
        mcp_server = str(Path(__file__).parent / "mcp_server.py")
        jsonl_dir = str(JSONL_DIR) if JSONL_DIR else ""
        jsonl_count = len(list(Path(jsonl_dir).glob("*.jsonl"))) if jsonl_dir and Path(jsonl_dir).exists() else 0

        self.send_json({
            "python_path": python_path,
            "python_found": os.path.exists(python_path),
            "mcp_server_path": mcp_server,
            "mcp_server_found": os.path.exists(mcp_server),
            "jsonl_dir": jsonl_dir,
            "jsonl_dir_found": bool(jsonl_dir) and Path(jsonl_dir).exists(),
            "jsonl_count": jsonl_count,
            "db_path": DB_PATH,
            "db_exists": os.path.exists(DB_PATH),
        })

    def _handle_setup_test(self, params):
        db = params.get("db", [""])[0] or DB_PATH
        try:
            c = sqlite3.connect(db)
            tables = c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            entries = c.execute("SELECT COUNT(*) FROM entries").fetchone()[0] if tables > 0 else 0
            c.close()
            self.send_json({"ok": True, "tables": tables, "entries": entries})
        except Exception as e:
            self.send_json({"ok": False, "error": str(e)})

    def _handle_setup_config(self, params):
        tool = params.get("tool", ["claude_code"])[0]
        python = params.get("python", [""])[0] or sys.executable
        mcp_server = params.get("mcp_server", [""])[0] or str(Path(__file__).parent / "mcp_server.py")
        db = params.get("db", [""])[0] or DB_PATH

        config = {
            "command": python,
            "args": [mcp_server],
            "env": {"MEMORY_DB": db},
        }

        if sys.platform == "win32":
            from config import _get_claude_config_dir
            real_path = str(_get_claude_config_dir() / "claude_desktop_config.json")
        else:
            real_path = os.path.expanduser("~/.claude/settings.local.json")

        self.send_json({"config": {"mcpServers": {"memory-engine": config}}, "real_path": real_path, "display_path": real_path})

    def _handle_setup_install(self, post_data):
        try:
            data = json.loads(post_data)
            real_path = data["real_path"]
            config = data["config"]

            existing = {}
            if os.path.exists(real_path):
                with open(real_path, "r") as f:
                    existing = json.load(f)

            if "mcpServers" not in existing:
                existing["mcpServers"] = {}
            existing["mcpServers"].update(config.get("mcpServers", {}))

            os.makedirs(os.path.dirname(real_path), exist_ok=True)
            with open(real_path, "w") as f:
                json.dump(existing, f, indent=2)

            self.send_json({"ok": True, "path": real_path})
        except Exception as e:
            self.send_json({"ok": False, "error": str(e)})

    def _handle_setup_ingest(self):
        try:
            from engine import MemoryEngine
            from config import JSONL_DIR
            eng = MemoryEngine()
            jsonls = sorted(Path(JSONL_DIR).glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True) if JSONL_DIR else []
            done, skipped, total_entries = 0, 0, 0
            for f in jsonls:
                r = eng.ingest_jsonl(str(f), source="claude_code")
                if r["status"] == "already_done":
                    skipped += 1
                else:
                    done += 1
                    total_entries += r.get("entries", 0)
            eng.conn.close()
            self.send_json({"ok": True, "ingested": done, "skipped": skipped, "entries": total_entries})
        except Exception as e:
            self.send_json({"ok": False, "error": str(e)})


def main():
    HOST = os.environ.get("VIEWER_HOST", "127.0.0.1")
    server = HTTPServer((HOST, PORT), APIHandler)
    print(f"[+] Memory Engine API running on http://{HOST}:{PORT}")
    print(f"[i] DB: {DB_PATH}")
    print(f"[i] Dashboard: http://localhost:3000 (start with: cd web && npm run dev)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Shutting down")
        server.server_close()


if __name__ == "__main__":
    main()
