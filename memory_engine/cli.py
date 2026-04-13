#!/usr/bin/env python3
"""
memory-engine CLI — setup, ingest, viewer, status, config.

Usage:
    python -m memory_engine.cli setup          # Open onboarding wizard
    python -m memory_engine.cli ingest         # Ingest all sources
    python -m memory_engine.cli ingest copilot # Ingest only Copilot CLI
    python -m memory_engine.cli viewer         # Start web dashboard
    python -m memory_engine.cli status         # Show source stats
    python -m memory_engine.cli config         # Show resolved config
"""

import argparse
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def cmd_setup(args):
    """Run onboarding wizard (opens web browser)."""
    from viewer import main as viewer_main
    import webbrowser
    import threading
    from config import VIEWER_PORT

    url = f"http://127.0.0.1:{VIEWER_PORT}/setup"
    print(f"[+] Opening setup wizard at {url}")
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    viewer_main()


def cmd_ingest(args):
    """Ingest conversation history from detected sources."""
    from engine import MemoryEngine
    from config import JSONL_DIR, COPILOT_JSONL_DIR, CODEX_JSONL_DIR
    from config import iter_copilot_files, iter_codex_files
    from pathlib import Path

    eng = MemoryEngine()
    source = args.source
    total_done = 0
    total_skipped = 0
    total_entries = 0

    # Claude Code
    if source in ("all", "claude_code"):
        jdir = Path(JSONL_DIR)
        if jdir.exists():
            jsonls = sorted(jdir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
            print(f"[*] Claude Code: {len(jsonls)} files in {jdir}")
            for f in jsonls:
                r = eng.ingest_jsonl(str(f), source="claude_code")
                if r["status"] == "already_done":
                    total_skipped += 1
                else:
                    total_done += 1
                    total_entries += r.get("entries", 0)
            print(f"[+] Claude Code: {total_done} new, {total_skipped} skipped")
        else:
            print(f"[-] Claude Code: directory not found ({jdir})")

    # Copilot CLI
    if source in ("all", "copilot"):
        files = iter_copilot_files()
        if files:
            print(f"[*] Copilot CLI: {len(files)} files in {COPILOT_JSONL_DIR}")
            done, skip = 0, 0
            for f in files:
                r = eng.ingest_copilot_jsonl(str(f))
                if r["status"] == "already_done":
                    skip += 1
                else:
                    done += 1
                    total_entries += r.get("entries", 0)
            total_done += done
            total_skipped += skip
            print(f"[+] Copilot CLI: {done} new, {skip} skipped")
        else:
            print(f"[-] Copilot CLI: not found ({COPILOT_JSONL_DIR or 'not installed'})")

    # Codex CLI
    if source in ("all", "codex"):
        files = iter_codex_files()
        if files:
            print(f"[*] Codex CLI: {len(files)} files in {CODEX_JSONL_DIR}")
            done, skip = 0, 0
            for f in files:
                r = eng.ingest_codex_jsonl(str(f))
                if r["status"] == "already_done":
                    skip += 1
                else:
                    done += 1
                    total_entries += r.get("entries", 0)
            total_done += done
            total_skipped += skip
            print(f"[+] Codex CLI: {done} new, {skip} skipped")
        else:
            print(f"[-] Codex CLI: not found ({CODEX_JSONL_DIR or 'not installed'})")

    eng.conn.close()
    print(f"\n[+] Total: {total_done} sessions ingested, {total_skipped} skipped, {total_entries:,} entries indexed")


def cmd_viewer(args):
    """Start web dashboard."""
    from viewer import main as viewer_main
    viewer_main()


def cmd_status(args):
    """Show source stats."""
    from engine import MemoryEngine
    from config import JSONL_DIR, COPILOT_JSONL_DIR, CODEX_JSONL_DIR
    from config import iter_copilot_files, iter_codex_files
    from pathlib import Path

    eng = MemoryEngine()
    conn = eng.conn

    print("=== Memory Engine Status ===\n")

    sources = [
        ("Claude Code", "claude_code", JSONL_DIR, len(list(Path(JSONL_DIR).glob("*.jsonl"))) if JSONL_DIR and Path(JSONL_DIR).exists() else 0),
        ("Copilot CLI", "copilot", COPILOT_JSONL_DIR, len(iter_copilot_files())),
        ("Codex CLI", "codex", CODEX_JSONL_DIR, len(iter_codex_files())),
    ]

    for label, key, directory, file_count in sources:
        sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE source=?", (key,)).fetchone()[0]
        entries = conn.execute("SELECT COUNT(*) FROM entries WHERE source=?", (key,)).fetchone()[0]
        status = "active" if directory and Path(str(directory)).exists() else "not found"
        print(f"  {label}:")
        print(f"    Dir: {directory or 'N/A'} ({status})")
        print(f"    Files: {file_count} | Sessions: {sessions} | Entries: {entries:,}")
        print()

    # Totals
    total_entries = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    total_sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE status='done'").fetchone()[0]
    db_size = os.path.getsize(eng.db_path) if os.path.exists(eng.db_path) else 0

    print(f"  Totals: {total_entries:,} entries | {total_sessions} sessions | {db_size / 1024 / 1024:.1f} MB")
    eng.conn.close()


def cmd_export(args):
    """Export a session (or all sessions) to JSON files."""
    from engine import MemoryEngine
    from pathlib import Path
    import json as _json

    eng = MemoryEngine()
    conn = eng.conn
    export_dir = Path(args.dir) if args.dir else Path(__file__).parent.parent / "export"

    if args.session_id == "all":
        sessions = conn.execute("SELECT id FROM sessions WHERE status='done'").fetchall()
        ids = [r["id"] for r in sessions]
        print(f"[*] Exporting {len(ids)} sessions to {export_dir}")
    else:
        ids = [args.session_id]

    exported = 0
    for sid in ids:
        rows = conn.execute("""
            SELECT id, content, role, session_id, timestamp, source_file,
                   source_line, content_hash, created_at
            FROM entries WHERE session_id = ? ORDER BY source_line ASC
        """, (sid,)).fetchall()
        meta = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
        if not meta:
            print(f"[-] Session {sid} not found, skipping")
            continue

        entries = [dict(r) for r in rows]
        first_ts = entries[0]["timestamp"] if entries else None
        date_str = first_ts[:10] if first_ts else datetime.now().strftime("%Y-%m-%d")

        out_dir = export_dir / date_str
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{sid}.json"

        export_data = {
            "session_id": sid,
            "exported_at": datetime.now().isoformat(),
            "date": date_str,
            "meta": {k: meta[k] for k in meta.keys()},
            "total_entries": len(entries),
            "entries": entries,
        }
        with open(out_path, "w", encoding="utf-8") as f:
            _json.dump(export_data, f, indent=2, ensure_ascii=False, default=str)
        exported += 1
        print(f"[+] {sid[:8]}... → {out_path}")

    conn.close()
    print(f"\n[+] Exported {exported} session(s)")


def cmd_config(args):
    """Show resolved config."""
    from config import print_config
    print_config()


def main():
    parser = argparse.ArgumentParser(
        prog="memory-engine",
        description="Memory Engine — persistent brain database for AI coding tools"
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("setup", help="Run onboarding wizard")

    p_ingest = sub.add_parser("ingest", help="Ingest conversation history")
    p_ingest.add_argument("source", nargs="?", default="all",
                          choices=["all", "claude_code", "copilot", "codex"],
                          help="Source to ingest (default: all)")

    sub.add_parser("viewer", help="Start web dashboard")

    p_export = sub.add_parser("export", help="Export session(s) to JSON")
    p_export.add_argument("session_id", help="Session ID to export, or 'all'")
    p_export.add_argument("--dir", help="Custom export directory (default: ./export/)")

    sub.add_parser("status", help="Show source stats")
    sub.add_parser("config", help="Show resolved configuration")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "setup": cmd_setup,
        "ingest": cmd_ingest,
        "viewer": cmd_viewer,
        "export": cmd_export,
        "status": cmd_status,
        "config": cmd_config,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
