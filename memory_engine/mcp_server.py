#!/usr/bin/env python3
"""
MEMORY ENGINE MCP SERVER
Exposes the memory database to Claude Code via FastMCP (stdio transport).
"""

import json
import os
import sys
from pathlib import Path
from glob import glob
from datetime import datetime

from fastmcp import FastMCP

# Add parent dir to path for direct script execution
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import MemoryEngine
from config import JSONL_DIR, AGENT_MEMORY_DIR

# Initialize
mcp = FastMCP(
    "memory-engine",
    instructions="""Memory Engine — persistent brain database for Claude Code.
    Search, save, and query knowledge from all conversation history.
    Backed by SQLite with full-text search and optional vector embeddings."""
)

engine = MemoryEngine()


@mcp.tool()
def memory_search(query: str, agent: str = "", role: str = "", days: int = 0, limit: int = 15) -> str:
    """Search all conversation history. Returns matching entries ranked by relevance.

    Args:
        query: What to search for (supports FTS5 syntax: AND, OR, NOT, "phrases")
        agent: Filter to specific agent (e.g. 'research', 'development')
        role: Filter by message role ('user', 'assistant', 'system')
        days: Only search last N days (0 = all time)
        limit: Max results (default 15)
    """
    try:
        results = engine.search(
            query,
            agent=agent or None,
            role=role or None,
            days=days or None,
            limit=limit
        )

        if not results:
            return f"No results found for: {query}"

        output = [f"Found {len(results)} results for: {query}\n"]
        for r in results:
            content = r["content"][:500] + ("..." if len(r["content"]) > 500 else "")
            output.append(f"---\n[{r['role']}] Session: {r['session_id'][:8]}... | {r.get('timestamp', '?')}")
            output.append(content)

        return "\n".join(output)
    except Exception as e:
        return f"Search error: {e}"


@mcp.tool()
def memory_search_knowledge(query: str, agent: str = "", status: str = "ACTIVE", limit: int = 20) -> str:
    """Search the curated knowledge base (classified, tagged entries).

    Args:
        query: What to search for
        agent: Filter to specific agent
        status: Filter by status (ACTIVE, STALE, ARCHIVED, or empty for all)
        limit: Max results
    """
    try:
        results = engine.search_knowledge(
            query,
            agent=agent or None,
            status=status or None,
            limit=limit
        )

        if not results:
            return f"No knowledge found for: {query}"

        output = [f"Found {len(results)} knowledge entries for: {query}\n"]
        for r in results:
            output.append(f"---")
            output.append(f"[{r['status']}] {r['topic']} (agent: {r['agent']})")
            output.append(f"Summary: {r['summary']}")
            if r.get("details"):
                details = r["details"][:300] + ("..." if len(r["details"]) > 300 else "")
                output.append(f"Details: {details}")
            output.append(f"Updated: {r['updated_at']}")
            history = json.loads(r.get("update_history", "[]"))
            if history:
                output.append(f"Updates: {len(history)} changes")

        return "\n".join(output)
    except Exception as e:
        return f"Knowledge search error: {e}"


@mcp.tool()
def memory_save(topic: str, summary: str, agent: str, details: str = "", tags: str = "", review_trigger: str = "") -> str:
    """Save or update a knowledge entry. Auto-deduplicates by topic+agent.

    Args:
        topic: Knowledge topic (e.g. 'Python — async patterns')
        summary: One-line summary
        agent: Which agent this is for (e.g. 'research')
        details: Detailed description
        tags: Comma-separated tags
        review_trigger: When to re-evaluate this knowledge
    """
    try:
        result = engine.save_knowledge(
            topic=topic,
            summary=summary,
            details=details or None,
            agent=agent,
            tags=tags or None,
            review_trigger=review_trigger or None,
        )
        return f"Knowledge {result['action']}: #{result['id']} — {topic} (agent: {agent})"
    except Exception as e:
        return f"Save error: {e}"


@mcp.tool()
def memory_timeline(start: str = "", end: str = "", limit: int = 30) -> str:
    """Show what happened in a time range. Returns entries chronologically.

    Args:
        start: Start datetime (ISO format, e.g. '2026-02-17T21:00:00')
        end: End datetime (ISO format)
        limit: Max entries (default 30)
    """
    try:
        results = engine.timeline(
            start=start or None,
            end=end or None,
            limit=limit
        )

        if not results:
            return "No entries found in that time range."

        output = [f"Timeline: {len(results)} entries\n"]
        for r in results:
            content = r["content"][:300] + ("..." if len(r["content"]) > 300 else "")
            output.append(f"[{r['timestamp']}] [{r['role']}] {content}")
            output.append("")

        return "\n".join(output)
    except Exception as e:
        return f"Timeline error: {e}"


@mcp.tool()
def memory_agent_knowledge(agent: str, status: str = "ACTIVE") -> str:
    """Get all knowledge for a specific agent.

    Args:
        agent: Agent name (e.g. 'research', 'development')
        status: Filter by status (ACTIVE, STALE, ARCHIVED, empty for all)
    """
    try:
        results = engine.get_agent_knowledge(agent, status=status or None)

        if not results:
            return f"No knowledge found for agent: {agent}"

        output = [f"Knowledge for {agent}: {len(results)} entries\n"]
        for r in results:
            output.append(f"[{r['status']}] {r['topic']}")
            output.append(f"  {r['summary']}")
            output.append(f"  Updated: {r['updated_at']}")
            output.append("")

        return "\n".join(output)
    except Exception as e:
        return f"Agent knowledge error: {e}"


@mcp.tool()
def memory_ingest(source: str = "all", session_id: str = "", tool_source: str = "all") -> str:
    """Ingest JSONL conversation history into the database.

    Args:
        source: 'all' to ingest all JSONLs, 'latest' for most recent, 'session' with session_id, or 'prompts' for prompt history
        session_id: Specific session UUID to ingest (when source='session')
        tool_source: Which tool to ingest: 'claude_code', 'copilot', 'codex', 'all' (default all)
    """
    try:
        results = []

        if source == "session" and session_id:
            # Ingest specific session
            pattern = str(JSONL_DIR / f"{session_id}*.jsonl")
            files = glob(pattern)
            if not files:
                # Check archive
                files = glob(str(JSONL_DIR / "archive" / f"{session_id}*.jsonl"))
            if not files:
                return f"Session not found: {session_id}"
            for f in files:
                r = engine.ingest_jsonl(f)
                results.append(r)

        elif source == "latest":
            # Find most recent JSONL
            jsonls = sorted(JSONL_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
            if jsonls:
                r = engine.ingest_jsonl(jsonls[0])
                results.append(r)

        elif source == "all":
            # Ingest all JSONLs (active + archive)
            jsonls = sorted(JSONL_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
            archive_jsonls = sorted(
                (JSONL_DIR / "archive").glob("*.jsonl"),
                key=lambda p: p.stat().st_mtime, reverse=True
            ) if (JSONL_DIR / "archive").exists() else []

            all_files = list(jsonls) + list(archive_jsonls)
            total = len(all_files)
            done = 0
            skipped = 0
            entries_total = 0

            for f in all_files:
                r = engine.ingest_jsonl(f)
                if r["status"] == "already_done":
                    skipped += 1
                else:
                    done += 1
                    entries_total += r.get("entries", 0)
                results.append(r)

            # Also ingest Copilot and Codex if requested
            if tool_source in ("all", "copilot"):
                from config import iter_copilot_files
                for f in iter_copilot_files():
                    r = engine.ingest_copilot_jsonl(str(f))
                    if r["status"] != "already_done":
                        done += 1
                        entries_total += r.get("entries", 0)
                    else:
                        skipped += 1

            if tool_source in ("all", "codex"):
                from config import iter_codex_files
                for f in iter_codex_files():
                    r = engine.ingest_codex_jsonl(str(f))
                    if r["status"] != "already_done":
                        done += 1
                        entries_total += r.get("entries", 0)
                    else:
                        skipped += 1

            return f"Ingested {done} sessions ({skipped} already done). {entries_total} new entries."

        elif source == "prompts":
            # Ingest prompt history (CONFIG/history.jsonl)
            prompt_file = Path.home() / ".claude/history.jsonl"
            if not prompt_file.exists():
                # Try backup location
                prompt_file = Path.home() / ".claude" / "history.jsonl"
            if not prompt_file.exists():
                return "Prompt history file not found."
            r = engine.ingest_prompt_history(str(prompt_file))
            return f"Prompt history: {r['status']} — {r.get('entries', 0)} entries from {r.get('lines', 0)} lines"

        if not results:
            return "No files to ingest."

        output = []
        for r in results:
            output.append(f"Session {r.get('session_id', '?')[:8]}: {r['status']} ({r.get('entries', 0)} entries)")

        return "\n".join(output)
    except Exception as e:
        return f"Ingest error: {e}"


@mcp.tool()
def memory_stats() -> str:
    """Show database statistics — entries, knowledge, sessions, agent breakdown."""
    try:
        stats = engine.stats()
        output = [
            "=== Memory Engine Stats ===",
            f"Entries (raw): {stats['entries']}",
            f"Knowledge (curated): {stats['knowledge']}",
            f"Sessions: {stats['sessions_done']}/{stats['sessions_total']} ingested",
            "",
            "By Agent:",
        ]
        for agent, count in sorted(stats["by_agent"].items()):
            output.append(f"  {agent}: {count}")

        output.append("\nBy Status:")
        for status, count in sorted(stats["by_status"].items()):
            output.append(f"  {status}: {count}")

        return "\n".join(output)
    except Exception as e:
        return f"Stats error: {e}"


@mcp.tool()
def memory_sources() -> str:
    """List detected conversation sources with session/entry counts and file paths."""
    try:
        from config import JSONL_DIR as _jdir, COPILOT_JSONL_DIR as _cdir, CODEX_JSONL_DIR as _xdir
        from config import iter_copilot_files, iter_codex_files

        conn = engine.conn
        output = ["=== Conversation Sources ===\n"]

        # Claude Code
        jcount = len(list(Path(_jdir).glob("*.jsonl"))) if _jdir and Path(_jdir).exists() else 0
        cc_sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE source='claude_code'").fetchone()[0]
        cc_entries = conn.execute("SELECT COUNT(*) FROM entries WHERE source='claude_code'").fetchone()[0]
        output.append(f"Claude Code:")
        output.append(f"  Dir: {_jdir}")
        output.append(f"  Files: {jcount} JSONL | Ingested: {cc_sessions} sessions, {cc_entries:,} entries\n")

        # Copilot
        cp_files = len(iter_copilot_files())
        cp_sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE source='copilot'").fetchone()[0]
        cp_entries = conn.execute("SELECT COUNT(*) FROM entries WHERE source='copilot'").fetchone()[0]
        output.append(f"GitHub Copilot CLI:")
        output.append(f"  Dir: {_cdir or 'not found'}")
        output.append(f"  Files: {cp_files} JSONL | Ingested: {cp_sessions} sessions, {cp_entries:,} entries\n")

        # Codex
        cx_files = len(iter_codex_files())
        cx_sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE source='codex'").fetchone()[0]
        cx_entries = conn.execute("SELECT COUNT(*) FROM entries WHERE source='codex'").fetchone()[0]
        output.append(f"OpenAI Codex CLI:")
        output.append(f"  Dir: {_xdir or 'not found'}")
        output.append(f"  Files: {cx_files} JSONL | Ingested: {cx_sessions} sessions, {cx_entries:,} entries")

        return "\n".join(output)
    except Exception as e:
        return f"Sources error: {e}"


@mcp.tool()
def memory_lifecycle() -> str:
    """Run temporal lifecycle management. ACTIVE→STALE (>24h) → ARCHIVED (>2d) → DELETED (>5d)."""
    try:
        result = engine.run_lifecycle()
        return f"Lifecycle run: {result['stale']} → STALE, {result['archived']} → ARCHIVED, {result['deleted']} deleted"
    except Exception as e:
        return f"Lifecycle error: {e}"


@mcp.tool()
def memory_refresh_agent(agent: str) -> str:
    """Regenerate an agent's MEMORY.md from the database. Keeps within 200-line limit.

    Args:
        agent: Agent name to refresh
    """
    try:
        knowledge = engine.get_agent_knowledge(agent, status=None)
        if not knowledge:
            return f"No knowledge found for {agent}"

        memory_dir = AGENT_MEMORY_DIR / agent
        if not memory_dir.exists():
            return f"Agent memory directory not found: {memory_dir}"

        # Build MEMORY.md content
        active = [k for k in knowledge if k["status"] == "ACTIVE"]
        stale = [k for k in knowledge if k["status"] == "STALE"]

        lines = [
            f"# {agent} — Persistent Knowledge Index",
            "",
            "## Quick Reference",
            f"- Last updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            f"- Topics: {len(active)} active, {len(stale)} stale",
            f"- Generated from: memory-engine DB",
            "",
            "## Active Knowledge",
            "",
        ]

        for k in active[:30]:  # Cap at 30 entries to stay under 200 lines
            lines.append(f"### {k['topic']}")
            lines.append(f"- **Summary**: {k['summary']}")
            lines.append(f"- **Status**: ACTIVE | Updated: {k['updated_at']}")
            if k.get("tags"):
                lines.append(f"- **Tags**: {k['tags']}")
            lines.append("")

        if stale:
            lines.append("## Stale (needs review)")
            lines.append("")
            for k in stale[:10]:
                lines.append(f"- {k['topic']} — last updated {k['updated_at']}")
            lines.append("")

        # Write MEMORY.md
        content = "\n".join(lines[:200])  # Hard cap at 200 lines
        memory_file = memory_dir / "MEMORY.md"
        memory_file.write_text(content)

        return f"Refreshed {agent}/MEMORY.md: {len(active)} active, {len(stale)} stale, {min(len(lines), 200)} lines"
    except Exception as e:
        return f"Refresh error: {e}"


@mcp.tool()
def memory_topic(topic: str, mode: str = "narrative") -> str:
    """Deep-dive into a topic across ALL sessions. Builds a structured narrative.

    This is the go-to tool when someone asks "what do we know about X?"
    It searches all entries, groups by session, and returns a readable summary.

    Args:
        topic: What to search for (e.g. 'project setup', 'authentication', 'database migration', 'API design')
        mode: 'narrative' for readable summary, 'raw' for session-level data
    """
    try:
        if mode == "raw":
            data = engine.topic_deep_search(topic, limit=200)
            if not data["sessions"]:
                return f"No data found for: {topic}"

            output = [f"Topic: {topic} — {data['total_hits']} hits across {data['sessions_count']} sessions\n"]
            for s in data["sessions"]:
                date = s["first_ts"][:10] if s["first_ts"] else "?"
                sid = s["session_id"][:8]
                tools = ", ".join(s["tools_used"][:5]) if s["tools_used"] else "none"
                output.append(f"[{date}] {sid}… | {s['hit_count']} hits | tools: {tools}")
                for msg in s["user_msgs"][:2]:
                    output.append(f"  USER: {msg[:150]}")
                for msg in s["assistant_msgs"][:2]:
                    output.append(f"  ASST: {msg[:150]}")
                output.append("")
            return "\n".join(output)
        else:
            return engine.topic_extract_narrative(topic)
    except Exception as e:
        return f"Topic search error: {e}"


@mcp.tool()
def memory_topics(min_hits: int = 10) -> str:
    """Discover what topics have been discussed most across all sessions.
    Returns frequently mentioned terms ranked by occurrence.

    Args:
        min_hits: Minimum number of mentions to include (default 10)
    """
    try:
        topics = engine.topic_list_all(min_hits=min_hits, limit=60)
        if not topics:
            return "No significant topics found."

        output = [f"Top topics (min {min_hits} mentions):\n"]
        for i, (word, count) in enumerate(topics, 1):
            bar = "█" * min(int(count / 5), 30)
            output.append(f"  {i:>3}. {word:<25} {count:>4} mentions {bar}")

        return "\n".join(output)
    except Exception as e:
        return f"Topics error: {e}"


@mcp.tool()
def memory_semantic(query: str, n_results: int = 15, role: str = "", mode: str = "hybrid") -> str:
    """Semantic search — find entries by MEANING, not just keywords.
    Hybrid mode combines vector similarity + keyword matching for best results.

    Use this when keyword search fails or when the query is conceptual:
    - "that database migration issue we discussed" (even if entry says "schema change on users table")
    - "how did we fix the auth flow" (finds auth-related entries by context)
    - "deployment steps for the API" (finds all deployment-related work)

    Args:
        query: Natural language query — describe what you're looking for
        n_results: Number of results (default 15)
        role: Filter by role ('user' or 'assistant', empty for both)
        mode: 'hybrid' (semantic+keyword), 'semantic' (vector only), 'keyword' (FTS only)
    """
    try:
        from semantic import SemanticEngine
        sem = SemanticEngine()

        if mode == "hybrid":
            results = sem.hybrid_search(query, n_results=n_results, role=role or None)
        else:
            results = sem.search(query, n_results=n_results, role=role or None)

        related = sem.extract_related_topics(results, top_n=5)
        sem.close()

        if not results:
            return f"No matches for: {query}\n[i] Try different wording or mode."

        output = [f"[{mode}] '{query}' — {len(results)} results\n"]

        if related:
            output.append(f"Related: {', '.join(w for w, _ in related)}\n")

        for r in results:
            score = r.get("hybrid_score", r.get("similarity", 0))
            sim = r.get("sem_score", r.get("similarity", 0))
            fts = r.get("fts_score", 0)
            role_tag = r.get("role", "?")
            ts = r.get("timestamp", "?")[:19]
            sid = r.get("session_id", "?")[:8]
            content = r["content"][:400].replace("\n", " ")
            score_detail = f"score:{score:.2f}"
            if mode == "hybrid" and fts > 0:
                score_detail += f" (sem:{sim:.2f}+kw:{fts:.2f})"
            output.append(f"[{score_detail}] [{role_tag}] {ts} | session:{sid}")
            output.append(f"  {content}")
            output.append("")

        return "\n".join(output)
    except ImportError:
        return "Semantic engine not available. Install chromadb: pip3 install chromadb"
    except Exception as e:
        return f"Semantic search error: {e}"


@mcp.tool()
def memory_similar(entry_id: int, n_results: int = 10) -> str:
    """Find entries similar to a given entry by its SQLite ID.
    Use this after finding an interesting entry to explore related content.

    Args:
        entry_id: SQLite entry ID (from search results)
        n_results: Number of similar entries to return
    """
    try:
        from semantic import SemanticEngine
        sem = SemanticEngine()
        results = sem.find_similar(entry_id, n_results=n_results)
        sem.close()

        if not results:
            return f"No similar entries found for ID {entry_id}"

        output = [f"Entries similar to #{entry_id} — {len(results)} results\n"]
        for r in results:
            sim = r.get("similarity", 0)
            role_tag = r.get("role", "?")
            ts = r.get("timestamp", "?")[:19]
            content = r["content"][:300].replace("\n", " ")
            output.append(f"[{sim:.2f}] [{role_tag}] {ts}")
            output.append(f"  {content}")
            output.append("")

        return "\n".join(output)
    except Exception as e:
        return f"Similar search error: {e}"


@mcp.tool()
def memory_context(entry_id: int, window: int = 5) -> str:
    """Get the conversation context around a specific entry.
    Shows entries before and after the target for full conversation flow.

    Args:
        entry_id: SQLite entry ID
        window: Number of entries before/after to show (default 5)
    """
    try:
        from semantic import SemanticEngine
        sem = SemanticEngine()
        context = sem.get_context_window(entry_id, window=window)
        sem.close()

        if not context:
            return f"Entry #{entry_id} not found"

        output = [f"Context around entry #{entry_id} ({len(context)} entries)\n"]
        for r in context:
            marker = " ◀ TARGET" if r["id"] == entry_id else ""
            role = r["role"]
            ts = r["timestamp"][:19] if r.get("timestamp") else "?"
            content = r["content"][:400].replace("\n", " ")
            output.append(f"[{role}] L{r['source_line']} {ts}{marker}")
            output.append(f"  {content}")
            output.append("")

        return "\n".join(output)
    except Exception as e:
        return f"Context error: {e}"


@mcp.tool()
def memory_semantic_embed(limit: int = 5000) -> str:
    """Embed new entries into the vector database for semantic search.

    Run this periodically or after ingesting new sessions.
    Only embeds entries not already in Chroma (incremental).

    Args:
        limit: Max entries to embed per call (default 5000)
    """
    try:
        from semantic import SemanticEngine
        sem = SemanticEngine()
        result = sem.embed_new(limit=limit)
        stats = sem.stats()
        sem.close()

        return (
            f"Embedding: {result['new']} new docs added\n"
            f"Total in Chroma: {stats['chroma_docs']}\n"
            f"SQLite eligible: {stats['sqlite_eligible']}\n"
            f"Coverage: {stats['coverage']}"
        )
    except Exception as e:
        return f"Embed error: {e}"


@mcp.tool()
def memory_observations(obs_type: str = "", concept: str = "", session_id: str = "",
                        min_confidence: float = 0.3, limit: int = 20) -> str:
    """Query extracted observations — structured knowledge from conversations.

    Observations are auto-extracted from entries using pattern matching.
    Types: decision, bugfix, feature, discovery, pattern, change
    Concepts: how-it-works, why-it-exists, what-changed, problem-solution, gotcha, pattern, trade-off

    Args:
        obs_type: Filter by type (e.g. 'bugfix', 'discovery')
        concept: Filter by concept (e.g. 'problem-solution', 'gotcha')
        session_id: Filter to specific session
        min_confidence: Minimum confidence threshold (0-1, default 0.3)
        limit: Max results
    """
    try:
        from observations import ObservationExtractor
        ext = ObservationExtractor()
        results = ext.get_observations(
            obs_type=obs_type or None,
            concept=concept or None,
            session_id=session_id or None,
            min_confidence=min_confidence,
            limit=limit
        )
        ext.close()

        if not results:
            return "No observations found matching filters."

        output = [f"Found {len(results)} observations\n"]
        for r in results:
            concept_tag = f" [{r['concept']}]" if r.get("concept") else ""
            content = r["content"][:400].replace("\n", " ")
            output.append(f"[{r['type']}]{concept_tag} conf:{r['confidence']} | session:{(r.get('session_id') or '?')[:8]}")
            output.append(f"  {content}")
            output.append("")

        return "\n".join(output)
    except Exception as e:
        return f"Observations error: {e}"


@mcp.tool()
def memory_extract_observations(session_id: str = "", force: bool = False) -> str:
    """Extract observations from conversation entries using pattern matching.

    Run after ingesting new sessions to populate the observations table.
    Extracts: decisions, bugfixes, features, discoveries, patterns, changes.

    Args:
        session_id: Specific session to extract from (empty = all sessions)
        force: Re-extract even if already done
    """
    try:
        from observations import ObservationExtractor
        ext = ObservationExtractor()

        if session_id:
            result = ext.extract_session(session_id, force=force)
            ext.close()
            if result["status"] == "already_done":
                return f"Session {session_id[:8]} already extracted ({result['existing']} observations)"
            return f"Extracted {result.get('observations', 0)} observations from session {session_id[:8]} ({result.get('entries_scanned', 0)} entries scanned)"
        else:
            result = ext.extract_all(force=force)
            ext.close()
            return f"Extracted {result['total_obs']} observations from {result['processed']} sessions ({result['skipped']} already done)"
    except Exception as e:
        return f"Extract error: {e}"


@mcp.tool()
def memory_session_summary(session_id: str = "", limit: int = 10) -> str:
    """Get or generate session summaries — structured: request, investigated, learned, completed, next_steps.

    Args:
        session_id: Specific session ID (empty = recent summaries)
        limit: Number of recent summaries when no session_id
    """
    try:
        from observations import ObservationExtractor
        ext = ObservationExtractor()

        if session_id:
            # Generate if missing
            summary = ext.get_session_summary(session_id)
            if not summary:
                result = ext.summarize_session(session_id)
                if result["status"] == "done":
                    summary = ext.get_session_summary(session_id)
                else:
                    ext.close()
                    return f"Could not summarize session {session_id[:8]}: {result['status']}"

            ext.close()

            output = [
                f"=== Session Summary: {session_id[:8]} ===",
                f"Entries: {summary.get('entry_count', '?')} | Duration: {summary.get('duration_minutes', '?')} min",
                f"Tools: {summary.get('tools_used', '[]')}",
                "",
                f"REQUEST:\n{summary.get('request', 'N/A')}",
                "",
                f"INVESTIGATED:\n{summary.get('investigated', 'N/A')}",
                "",
                f"LEARNED:\n{summary.get('learned', 'N/A')}",
                "",
                f"COMPLETED:\n{summary.get('completed', 'N/A')}",
                "",
                f"NEXT STEPS:\n{summary.get('next_steps', 'N/A')}",
            ]
            return "\n".join(output)
        else:
            summaries = ext.get_recent_summaries(limit=limit)
            ext.close()

            if not summaries:
                return "No session summaries found. Run memory_extract_observations first."

            output = [f"Recent {len(summaries)} session summaries:\n"]
            for s in summaries:
                sid = s["session_id"][:8]
                req = (s.get("request") or "?")[:100].replace("\n", " ")
                dur = s.get("duration_minutes", "?")
                entries = s.get("entry_count", "?")
                output.append(f"[{sid}] {entries} entries | {dur} min")
                output.append(f"  Request: {req}")
                completed = (s.get("completed") or "?")[:150].replace("\n", " ")
                output.append(f"  Completed: {completed}")
                output.append("")

            return "\n".join(output)
    except Exception as e:
        return f"Summary error: {e}"


@mcp.tool()
def memory_context_inject(max_observations: int = 20) -> str:
    """Generate context injection block for session start.

    Returns XML-structured block with recent observations and session summaries.
    Designed to be injected at SessionStart for continuity.

    Args:
        max_observations: Max observations to include
    """
    try:
        from observations import ObservationExtractor
        ext = ObservationExtractor()
        context = ext.get_context_injection(max_observations=max_observations)
        stats = ext.observation_stats()
        ext.close()

        header = (
            f"[i] Context injection: {stats['total_observations']} observations, "
            f"{stats['session_summaries']} summaries\n\n"
        )
        return header + context
    except Exception as e:
        return f"Context inject error: {e}"


# ── Project Tools ────────────────────────────────────────────────────

@mcp.tool()
def project_create(name: str, description: str = "", tags: str = "", color: str = "#58a6ff") -> str:
    """Create a new project for organizing sessions by bounty program, target, or research area.

    Args:
        name: Project name (e.g. 'Frontend Redesign', 'API v2', 'Performance Research')
        description: What this project is about
        tags: Comma-separated tags (e.g. 'react,typescript,frontend')
        color: Hex color for UI (default #58a6ff)
    """
    try:
        result = engine.create_project(name, description or None, tags or None, color)
        if result["action"] == "exists":
            return f"Project '{name}' already exists."
        return f"[+] Project created: #{result['id']} — {name}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def project_list(status: str = "active") -> str:
    """List all projects with session counts.

    Args:
        status: Filter by status ('active', 'archived', '' for all)
    """
    try:
        projects = engine.list_projects(status=status or None)
        if not projects:
            return "No projects found. Create one with project_create."

        output = [f"Projects ({len(projects)}):\n"]
        for p in projects:
            tags = f" [{p['tags']}]" if p.get("tags") else ""
            output.append(f"  #{p['id']} {p['name']}{tags} — {p['session_count']} sessions ({p['status']})")
        return "\n".join(output)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def project_assign(project_name: str, session_id: str = "", auto: bool = False) -> str:
    """Assign sessions to a project.

    Args:
        project_name: Project name or ID
        session_id: Session UUID to assign (or prefix)
        auto: If true, auto-detect and assign sessions matching project name/tags
    """
    try:
        project = engine._resolve_project(project_name)
        if not project:
            return f"Project not found: {project_name}"

        pid = project["id"]

        if auto:
            suggestions = engine.suggest_project_sessions(pid, limit=30)
            if not suggestions:
                return f"No matching sessions found for '{project['name']}'"
            sids = [s["session_id"] for s in suggestions]
            result = engine.bulk_assign_sessions(pid, sids)
            return f"[+] Auto-assigned {result['assigned']} sessions to '{project['name']}' ({result['already_assigned']} already assigned)"

        if not session_id:
            return "Provide session_id or use auto=True"

        # Support partial UUIDs
        if len(session_id) < 36:
            matches = engine.conn.execute(
                "SELECT DISTINCT session_id FROM entries WHERE session_id LIKE ? LIMIT 5",
                (session_id + "%",)
            ).fetchall()
            if len(matches) == 1:
                session_id = matches[0]["session_id"]
            elif len(matches) > 1:
                return f"Ambiguous prefix '{session_id}', matches: {', '.join(r['session_id'][:12] for r in matches)}"
            else:
                return f"No session found matching: {session_id}"

        result = engine.assign_session(pid, session_id)
        return f"[+] {result['action'].title()}: session {session_id[:12]}… → '{project['name']}'"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def project_search(project_name: str, query: str, role: str = "", limit: int = 15) -> str:
    """Search within a specific project's sessions only.

    Args:
        project_name: Project name or ID
        query: FTS5 search query
        role: Filter by role ('user', 'assistant')
        limit: Max results
    """
    try:
        project = engine._resolve_project(project_name)
        if not project:
            return f"Project not found: {project_name}"

        results = engine.project_search(project["id"], query, role=role or None, limit=limit)
        if not results:
            return f"No results in '{project['name']}' for: {query}"

        output = [f"[{project['name']}] {len(results)} results for: {query}\n"]
        for r in results:
            content = r["content"][:500] + ("..." if len(r["content"]) > 500 else "")
            output.append(f"---\n[{r['role']}] Session: {r['session_id'][:8]}… | {r.get('timestamp', '?')}")
            output.append(content)

        return "\n".join(output)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def project_info(project_name: str) -> str:
    """Get detailed information about a project — stats, sessions, observations.

    Args:
        project_name: Project name or ID
    """
    try:
        project = engine._resolve_project(project_name)
        if not project:
            return f"Project not found: {project_name}"

        pid = project["id"]
        stats = engine.project_stats(pid)
        sessions = engine.get_project_sessions(pid, limit=10)
        observations = engine.project_observations(pid, limit=5)

        output = [
            f"=== Project: {project['name']} ===",
            f"Description: {project.get('description') or 'N/A'}",
            f"Tags: {project.get('tags') or 'none'}",
            f"Status: {project['status']} | Color: {project.get('color', '?')}",
            f"Created: {project['created_at']}",
            "",
            f"Sessions: {stats['sessions']}",
            f"Entries: {stats['entries']}",
            f"Observations: {stats['observations']}",
            f"Date range: {(stats.get('first_ts') or '?')[:10]} → {(stats.get('last_ts') or '?')[:10]}",
            "",
        ]

        if sessions:
            output.append("Recent sessions:")
            for s in sessions[:10]:
                sid = s["session_id"][:12]
                entries = s.get("entry_count", "?")
                ts = (s.get("first_ts") or "?")[:10]
                output.append(f"  {sid}… | {entries} entries | {ts}")

        if observations:
            output.append("\nTop observations:")
            for o in observations[:5]:
                content = o["content"][:150].replace("\n", " ")
                output.append(f"  [{o['type']}] conf:{o['confidence']} — {content}")

        return "\n".join(output)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def project_update(project_name: str, description: str = "", tags: str = "", status: str = "", color: str = "") -> str:
    """Update a project's metadata.

    Args:
        project_name: Project name or ID
        description: New description (empty = no change)
        tags: New tags (empty = no change)
        status: New status ('active' or 'archived', empty = no change)
        color: New hex color (empty = no change)
    """
    try:
        project = engine._resolve_project(project_name)
        if not project:
            return f"Project not found: {project_name}"

        kwargs = {}
        if description:
            kwargs["description"] = description
        if tags:
            kwargs["tags"] = tags
        if status:
            kwargs["status"] = status
        if color:
            kwargs["color"] = color

        if not kwargs:
            return "No changes specified."

        result = engine.update_project(project["id"], **kwargs)
        return f"[+] Project '{project['name']}' updated: {', '.join(kwargs.keys())}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def memory_session_detail(session_id: str, page: int = 1, per_page: int = 50) -> str:
    """Fetch full session conversation from the memory database — all entries with role, content, timestamp.

    Args:
        session_id: Full or partial session UUID
        page: Page number (1-indexed)
        per_page: Entries per page (max 200)
    """
    try:
        per_page = min(per_page, 200)
        offset = (page - 1) * per_page

        conn = engine.conn
        # Resolve partial IDs
        if len(session_id) < 36:
            row = conn.execute("SELECT id FROM sessions WHERE id LIKE ?", (f"{session_id}%",)).fetchone()
            if row:
                session_id = row[0]
            else:
                return f"[-] No session matching '{session_id}'"

        total = conn.execute("SELECT COUNT(*) FROM entries WHERE session_id = ?", (session_id,)).fetchone()[0]
        if total == 0:
            return f"[-] Session {session_id[:8]} not found or empty"

        rows = conn.execute("""
            SELECT role, content, timestamp, source_line FROM entries
            WHERE session_id = ? ORDER BY source_line ASC LIMIT ? OFFSET ?
        """, (session_id, per_page, offset)).fetchall()

        total_pages = (total + per_page - 1) // per_page
        output = [f"=== Session {session_id[:8]} | Page {page}/{total_pages} | {total} entries ===\n"]

        for r in rows:
            role = r[0].upper()
            content = r[1][:1500]  # cap content
            ts = (r[2] or "?")[:19]
            output.append(f"[{role}] @ {ts} (line {r[3]})")
            output.append(content)
            output.append("---")

        if page < total_pages:
            output.append(f"\n[>] More: memory_session_detail('{session_id[:8]}', page={page+1})")

        return "\n".join(output)
    except Exception as e:
        return f"Error fetching session: {e}"


@mcp.tool()
def memory_session_list(limit: int = 20, query: str = "") -> str:
    """List recent sessions from the memory database.

    Args:
        limit: Max sessions to return (max 50)
        query: Optional search text to filter sessions
    """
    try:
        limit = min(limit, 50)
        conn = engine.conn

        if query:
            rows = conn.execute("""
                SELECT s.id, s.status, s.started_at, s.ended_at, COUNT(e.id) as entries
                FROM sessions s LEFT JOIN entries e ON e.session_id = s.id
                WHERE EXISTS (
                    SELECT 1 FROM entries e2 WHERE e2.session_id = s.id AND e2.content LIKE ?
                )
                GROUP BY s.id ORDER BY s.started_at DESC LIMIT ?
            """, (f"%{query}%", limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT s.id, s.status, s.started_at, s.ended_at, COUNT(e.id) as entries
                FROM sessions s LEFT JOIN entries e ON e.session_id = s.id
                GROUP BY s.id ORDER BY s.started_at DESC LIMIT ?
            """, (limit,)).fetchall()

        if not rows:
            return "No sessions found."

        output = [f"=== {len(rows)} Sessions ===\n"]
        for r in rows:
            sid = r[0][:8]
            started = (r[2] or "?")[:16]
            entries = r[4]
            status = r[1] or "?"
            output.append(f"[{sid}] {started} | {entries} entries | {status}")

        return "\n".join(output)
    except Exception as e:
        return f"Error: {e}"


# ── Data Management Tools ─────────────────────────────────────────

@mcp.tool()
def memory_delete(entry_id: int = 0, knowledge_id: int = 0) -> str:
    """Delete a specific entry or knowledge item by ID.

    Args:
        entry_id: SQLite entry ID to delete (0 = skip)
        knowledge_id: Knowledge item ID to delete (0 = skip)
    """
    try:
        conn = engine.conn
        deleted = []

        if entry_id > 0:
            conn.execute("DELETE FROM entries_fts WHERE rowid = ?", (entry_id,))
            conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
            deleted.append(f"entry #{entry_id}")

        if knowledge_id > 0:
            conn.execute("DELETE FROM knowledge_fts WHERE rowid = ?", (knowledge_id,))
            conn.execute("DELETE FROM knowledge WHERE id = ?", (knowledge_id,))
            deleted.append(f"knowledge #{knowledge_id}")

        if not deleted:
            return "Provide entry_id or knowledge_id to delete."

        conn.commit()
        return f"[+] Deleted: {', '.join(deleted)}"
    except Exception as e:
        return f"Delete error: {e}"


@mcp.tool()
def memory_forget(session_id: str = "", before_date: str = "", pattern: str = "") -> str:
    """Bulk delete entries by session, date, or content pattern. Use for privacy/cleanup.

    Args:
        session_id: Delete all entries for this session (partial UUID OK)
        before_date: Delete all entries before this date (ISO format, e.g. '2025-01-01')
        pattern: Delete entries matching this text pattern
    """
    try:
        conn = engine.conn
        total = 0

        if session_id:
            if len(session_id) < 36:
                session_id = session_id + "%"
                rows = conn.execute("SELECT id FROM entries WHERE session_id LIKE ?", (session_id,)).fetchall()
            else:
                rows = conn.execute("SELECT id FROM entries WHERE session_id = ?", (session_id,)).fetchall()
            ids = [r[0] for r in rows]
            for eid in ids:
                conn.execute("DELETE FROM entries_fts WHERE rowid = ?", (eid,))
            conn.execute("DELETE FROM entries WHERE id IN ({})".format(",".join("?" * len(ids))), ids) if ids else None
            total += len(ids)

        if before_date:
            rows = conn.execute("SELECT id FROM entries WHERE timestamp < ?", (before_date,)).fetchall()
            ids = [r[0] for r in rows]
            for eid in ids:
                conn.execute("DELETE FROM entries_fts WHERE rowid = ?", (eid,))
            conn.execute("DELETE FROM entries WHERE id IN ({})".format(",".join("?" * len(ids))), ids) if ids else None
            total += len(ids)

        if pattern:
            rows = conn.execute("SELECT id FROM entries WHERE content LIKE ?", (f"%{pattern}%",)).fetchall()
            ids = [r[0] for r in rows]
            for eid in ids:
                conn.execute("DELETE FROM entries_fts WHERE rowid = ?", (eid,))
            conn.execute("DELETE FROM entries WHERE id IN ({})".format(",".join("?" * len(ids))), ids) if ids else None
            total += len(ids)

        if total == 0:
            return "No matching entries found to delete."

        conn.commit()
        return f"[+] Deleted {total} entries"
    except Exception as e:
        return f"Forget error: {e}"


@mcp.tool()
def memory_export(format: str = "json", limit: int = 1000, session_id: str = "") -> str:
    """Export entries as JSON or CSV text.

    Args:
        format: 'json' or 'csv'
        limit: Max entries to export (default 1000)
        session_id: Filter to specific session (optional)
    """
    try:
        conn = engine.conn
        limit = min(limit, 5000)

        if session_id:
            rows = conn.execute(
                "SELECT id, content, role, session_id, timestamp FROM entries WHERE session_id LIKE ? ORDER BY id LIMIT ?",
                (session_id + "%", limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, content, role, session_id, timestamp FROM entries ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()

        if not rows:
            return "No entries to export."

        if format == "csv":
            lines = ["id,role,session_id,timestamp,content_preview"]
            for r in rows:
                preview = r["content"][:100].replace(",", ";").replace("\n", " ")
                lines.append(f'{r["id"]},{r["role"]},{r["session_id"][:8]},{r["timestamp"] or ""},"{preview}"')
            return "\n".join(lines)
        else:
            data = [{"id": r["id"], "role": r["role"], "session_id": r["session_id"],
                     "timestamp": r["timestamp"], "content": r["content"][:500]} for r in rows]
            return json.dumps(data, indent=2, default=str)
    except Exception as e:
        return f"Export error: {e}"


@mcp.tool()
def memory_health() -> str:
    """Check database health — integrity, FTS sync, disk size, table counts."""
    try:
        conn = engine.conn
        import os as _os

        # Integrity check
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]

        # Table counts
        entries = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        knowledge = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        fts_count = conn.execute("SELECT COUNT(*) FROM entries_fts").fetchone()[0]

        # DB size
        db_path = engine.db_path
        db_size = _os.path.getsize(db_path) if _os.path.exists(db_path) else 0
        size_mb = db_size / (1024 * 1024)

        # FTS sync check
        fts_sync = "OK" if fts_count == entries else f"MISMATCH (entries={entries}, fts={fts_count})"

        output = [
            "=== Memory Engine Health ===",
            f"Integrity: {integrity}",
            f"DB size: {size_mb:.1f} MB",
            f"Entries: {entries}",
            f"Knowledge: {knowledge}",
            f"Sessions: {sessions}",
            f"FTS sync: {fts_sync}",
            f"DB path: {db_path}",
        ]
        return "\n".join(output)
    except Exception as e:
        return f"Health check error: {e}"


@mcp.tool()
def memory_config() -> str:
    """Show current configuration — resolved paths, ports, directories."""
    try:
        from config import (DB_PATH as _db, CHROMA_PATH as _chroma, JSONL_DIR as _jsonl,
                           VIEWER_PORT as _port, AGENT_MEMORY_DIR as _agent,
                           IMAGES_DIR as _images, LOG_FILE as _log)
        import sys as _sys
        output = [
            "=== Memory Engine Config ===",
            f"Platform: {_sys.platform}",
            f"DB: {_db}",
            f"Chroma: {_chroma}",
            f"JSONL dir: {_jsonl}",
            f"Images: {_images}",
            f"Agent memory: {_agent}",
            f"Viewer port: {_port}",
            f"Log file: {_log}",
        ]
        return "\n".join(output)
    except Exception as e:
        return f"Config error: {e}"


@mcp.tool()
def project_delete(project_name: str) -> str:
    """Delete a project and all its session assignments.

    Args:
        project_name: Project name or ID to delete
    """
    try:
        project = engine._resolve_project(project_name)
        if not project:
            return f"Project not found: {project_name}"

        pid = project["id"]
        name = project["name"]

        conn = engine.conn
        conn.execute("DELETE FROM project_sessions WHERE project_id = ?", (pid,))
        conn.execute("DELETE FROM projects WHERE id = ?", (pid,))
        conn.commit()

        return f"[+] Deleted project '{name}' (#{pid}) and all session assignments"
    except Exception as e:
        return f"Delete error: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
