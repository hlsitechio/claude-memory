#!/usr/bin/env python3
"""
Memory Engine Bridge — CLI wrapper for external integrations.
Takes a command + JSON args, returns JSON to stdout.

Usage: python3 bridge.py <command> '<json_args>'
Example: python3 bridge.py stats '{}'
         python3 bridge.py search '{"query":"auth flow","limit":10}'
"""

import json
import sys
import os
from datetime import datetime

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import MemoryEngine

engine = MemoryEngine()


def cmd_stats(args):
    return engine.stats()


def cmd_search(args):
    results = engine.search(
        args["query"],
        agent=args.get("agent") or None,
        role=args.get("role") or None,
        days=args.get("days") or None,
        limit=args.get("limit", 15),
    )
    return {"results": [dict(r) for r in results], "count": len(results)}


def cmd_search_knowledge(args):
    results = engine.search_knowledge(
        args.get("query", ""),
        agent=args.get("agent") or None,
        status=args.get("status") or None,
        limit=args.get("limit", 20),
    )
    return {"results": [dict(r) for r in results], "count": len(results)}


def cmd_save_knowledge(args):
    result = engine.save_knowledge(
        topic=args["topic"],
        summary=args["summary"],
        details=args.get("details") or None,
        agent=args.get("agent", "bridge"),
        tags=args.get("tags") or None,
        review_trigger=args.get("review_trigger") or None,
    )
    return result


def cmd_agent_knowledge(args):
    results = engine.get_agent_knowledge(
        args["agent"],
        status=args.get("status") or None,
    )
    return {"results": [dict(r) for r in results], "count": len(results)}


def cmd_topics(args):
    topics = engine.topic_list_all(
        min_hits=args.get("min_hits", 10),
        limit=args.get("limit", 60),
    )
    return {"topics": [{"word": w, "count": c} for w, c in topics]}


def cmd_topic(args):
    data = engine.topic_deep_search(args["name"], limit=args.get("limit", 200))
    # Convert Row objects to dicts
    sessions = []
    for s in data.get("sessions", []):
        sessions.append({
            "session_id": s["session_id"],
            "hit_count": s["hit_count"],
            "first_ts": s.get("first_ts"),
            "tools_used": s.get("tools_used", []),
            "user_msgs": s.get("user_msgs", [])[:3],
            "assistant_msgs": s.get("assistant_msgs", [])[:3],
        })
    return {
        "total_hits": data.get("total_hits", 0),
        "sessions_count": data.get("sessions_count", 0),
        "sessions": sessions,
    }


def cmd_session_list(args):
    conn = engine.conn
    limit = min(args.get("limit", 20), 50)
    query = args.get("query", "")

    if query:
        rows = conn.execute("""
            SELECT s.id, s.status, s.last_processed_at,
                   COUNT(e.id) as entries,
                   MIN(e.timestamp) as first_ts,
                   MAX(e.timestamp) as last_ts
            FROM sessions s LEFT JOIN entries e ON e.session_id = s.id
            WHERE EXISTS (SELECT 1 FROM entries e2 WHERE e2.session_id = s.id AND e2.content LIKE ?)
            GROUP BY s.id ORDER BY s.last_processed_at DESC LIMIT ?
        """, (f"%{query}%", limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT s.id, s.status, s.last_processed_at,
                   COUNT(e.id) as entries,
                   MIN(e.timestamp) as first_ts,
                   MAX(e.timestamp) as last_ts
            FROM sessions s LEFT JOIN entries e ON e.session_id = s.id
            GROUP BY s.id ORDER BY s.last_processed_at DESC LIMIT ?
        """, (limit,)).fetchall()

    return {"sessions": [
        {"id": r[0], "status": r[1], "last_processed_at": r[2],
         "entries": r[3], "started_at": r[4], "ended_at": r[5]}
        for r in rows
    ]}


def cmd_session_detail(args):
    conn = engine.conn
    session_id = args["id"]
    page = args.get("page", 1)
    per_page = min(args.get("per_page", 50), 200)
    offset = (page - 1) * per_page

    # Resolve partial IDs
    if len(session_id) < 36:
        row = conn.execute("SELECT id FROM sessions WHERE id LIKE ?", (f"{session_id}%",)).fetchone()
        if row:
            session_id = row[0]
        else:
            return {"error": f"No session matching '{session_id}'"}

    total = conn.execute("SELECT COUNT(*) FROM entries WHERE session_id = ?", (session_id,)).fetchone()[0]
    if total == 0:
        return {"error": f"Session {session_id[:8]} not found or empty"}

    rows = conn.execute("""
        SELECT role, content, timestamp, source_line FROM entries
        WHERE session_id = ? ORDER BY source_line ASC LIMIT ? OFFSET ?
    """, (session_id, per_page, offset)).fetchall()

    total_pages = (total + per_page - 1) // per_page
    return {
        "session_id": session_id,
        "page": page,
        "total_pages": total_pages,
        "total_entries": total,
        "entries": [
            {"role": r[0], "content": r[1][:2000], "timestamp": r[2], "source_line": r[3]}
            for r in rows
        ],
    }


def cmd_timeline(args):
    results = engine.timeline(
        start=args.get("start") or None,
        end=args.get("end") or None,
        limit=args.get("limit", 30),
    )
    return {"entries": [dict(r) for r in results], "count": len(results)}


def cmd_observations(args):
    try:
        from observations import ObservationExtractor
        ext = ObservationExtractor()
        results = ext.get_observations(
            obs_type=args.get("type") or None,
            concept=args.get("concept") or None,
            session_id=args.get("session_id") or None,
            min_confidence=args.get("min_confidence", 0.3),
            limit=args.get("limit", 20),
        )
        ext.close()
        return {"results": [dict(r) for r in results], "count": len(results)}
    except ImportError:
        return {"error": "Observations module not available"}


def cmd_project_list(args):
    projects = engine.list_projects(status=args.get("status") or None)
    return {"projects": [dict(p) for p in projects]}


def cmd_project_create(args):
    result = engine.create_project(
        args["name"],
        args.get("description") or None,
        args.get("tags") or None,
        args.get("color", "#58a6ff"),
    )
    return result


def cmd_project_info(args):
    project = engine._resolve_project(args["name"])
    if not project:
        return {"error": f"Project not found: {args['name']}"}

    pid = project["id"]
    stats = engine.project_stats(pid)
    sessions = engine.get_project_sessions(pid, limit=10)
    observations = engine.project_observations(pid, limit=5)

    return {
        "project": dict(project),
        "stats": stats,
        "sessions": [dict(s) for s in sessions],
        "observations": [dict(o) for o in observations],
    }


def cmd_project_search(args):
    project = engine._resolve_project(args["name"])
    if not project:
        return {"error": f"Project not found: {args['name']}"}

    results = engine.project_search(
        project["id"],
        args["query"],
        role=args.get("role") or None,
        limit=args.get("limit", 15),
    )
    return {"results": [dict(r) for r in results], "count": len(results)}


def cmd_chat_save(args):
    """Save a chat message to the memory engine as a live entry."""
    import hashlib
    conn = engine.conn

    content = args["content"]
    role = args.get("role", "user")
    session_id = args.get("session_id", "bridge-live")
    timestamp = args.get("timestamp") or datetime.now().isoformat()
    source = args.get("source", "chat")  # chat, terminal, system

    # Dedup by content hash
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    existing = conn.execute("SELECT id FROM entries WHERE content_hash = ?", (content_hash,)).fetchone()
    if existing:
        return {"action": "duplicate", "id": existing[0]}

    # Ensure session exists
    conn.execute("""
        INSERT OR IGNORE INTO sessions (id, file_path, status, last_processed_at)
        VALUES (?, ?, 'live', datetime('now'))
    """, (session_id, f"bridge-{source}"))

    # Insert entry
    cursor = conn.execute("""
        INSERT INTO entries (content, role, session_id, timestamp, source_file, content_hash)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (content, role, session_id, timestamp, f"bridge-{source}", content_hash))

    # Update FTS
    conn.execute("""
        INSERT INTO entries_fts(rowid, content, role, session_id)
        VALUES (?, ?, ?, ?)
    """, (cursor.lastrowid, content, role, session_id))

    # Update session timestamp
    conn.execute("""
        UPDATE sessions SET last_processed_at = datetime('now') WHERE id = ?
    """, (session_id,))

    conn.commit()
    return {"action": "saved", "id": cursor.lastrowid, "session_id": session_id}


def cmd_lifecycle(args):
    return engine.run_lifecycle()


def cmd_ingest(args):
    from pathlib import Path
    from glob import glob as globfn
    from config import JSONL_DIR
    source = args.get("source", "latest")

    if source == "latest":
        jsonls = sorted(JSONL_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if jsonls:
            r = engine.ingest_jsonl(jsonls[0])
            return r
        return {"error": "No JSONL files found"}

    elif source == "all":
        jsonls = sorted(JSONL_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        done, skipped, entries_total = 0, 0, 0
        for f in jsonls:
            r = engine.ingest_jsonl(f)
            if r["status"] == "already_done":
                skipped += 1
            else:
                done += 1
                entries_total += r.get("entries", 0)
        return {"done": done, "skipped": skipped, "entries": entries_total, "total_files": len(jsonls)}

    return {"error": f"Unknown source: {source}"}


def cmd_semantic(args):
    try:
        from semantic import SemanticEngine
        sem = SemanticEngine()
        mode = args.get("mode", "hybrid")

        if mode == "hybrid":
            results = sem.hybrid_search(args["query"], n_results=args.get("limit", 15), role=args.get("role") or None)
        else:
            results = sem.search(args["query"], n_results=args.get("limit", 15), role=args.get("role") or None)

        related = sem.extract_related_topics(results, top_n=5)
        sem.close()

        return {
            "results": results,
            "related": [{"word": w, "score": s} for w, s in related],
            "count": len(results),
            "mode": mode,
        }
    except ImportError:
        return {"error": "Semantic engine not available. Install chromadb."}
    except Exception as e:
        return {"error": str(e)}


COMMANDS = {
    "stats": cmd_stats,
    "search": cmd_search,
    "search_knowledge": cmd_search_knowledge,
    "save_knowledge": cmd_save_knowledge,
    "agent_knowledge": cmd_agent_knowledge,
    "topics": cmd_topics,
    "topic": cmd_topic,
    "session_list": cmd_session_list,
    "session_detail": cmd_session_detail,
    "timeline": cmd_timeline,
    "observations": cmd_observations,
    "project_list": cmd_project_list,
    "project_create": cmd_project_create,
    "project_info": cmd_project_info,
    "project_search": cmd_project_search,
    "chat_save": cmd_chat_save,
    "lifecycle": cmd_lifecycle,
    "ingest": cmd_ingest,
    "semantic": cmd_semantic,
}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: bridge.py <command> [json_args]"}))
        sys.exit(1)

    command = sys.argv[1]
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

    if command not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {command}", "available": list(COMMANDS.keys())}))
        sys.exit(1)

    try:
        result = COMMANDS[command](args)
        print(json.dumps(result, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
