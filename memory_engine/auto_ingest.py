#!/usr/bin/env python3
"""
AUTO-INGEST — Feeds JSONL conversation data into memory-engine.
Called from Claude Code hooks (Stop, PreCompact) or systemd timer.

Modes:
  latest   — Ingest the most recently modified JSONL (default)
  all      — Ingest all new/changed JSONLs
  recent   — Re-ingest N most recent JSONLs
  watch    — Continuous watcher (for background daemon)
  embed    — Only run embedding (no ingest)

Safety: Uses a lockfile to prevent concurrent runs (fork bomb prevention).
"""

import sys
import os
import time
import json
from pathlib import Path
from datetime import datetime

# Cross-platform file locking
if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

# Add engine to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import MemoryEngine
from config import JSONL_DIR, LOG_FILE, LOCK_FILE


def acquire_lock():
    """Try to acquire exclusive lock. Returns lock fd or None. Cross-platform."""
    try:
        fd = open(LOCK_FILE, "w")
        if sys.platform == "win32":
            msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd.write(str(os.getpid()))
        fd.flush()
        return fd
    except (IOError, OSError):
        return None


def release_lock(fd):
    """Release the lock. Cross-platform."""
    if fd:
        try:
            if sys.platform == "win32":
                try:
                    msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()
            LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def ingest_latest(engine):
    """Ingest the most recently modified JSONL file."""
    jsonls = sorted(JSONL_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not jsonls:
        log("No JSONL files found")
        return

    latest = jsonls[0]
    result = engine.ingest_jsonl(str(latest))
    log(f"Latest: {latest.stem[:8]}... → {result['status']} ({result.get('entries', 0)} entries)")
    return result


def ingest_all(engine):
    """Ingest all JSONL files (skips already-done)."""
    jsonls = sorted(JSONL_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    archive_dir = JSONL_DIR / "archive"
    if archive_dir.exists():
        jsonls.extend(sorted(archive_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True))

    total = len(jsonls)
    done = 0
    skipped = 0
    entries_total = 0

    for f in jsonls:
        result = engine.ingest_jsonl(str(f))
        if result["status"] == "already_done":
            skipped += 1
        else:
            done += 1
            entries_total += result.get("entries", 0)

    log(f"All: {done} new sessions, {skipped} skipped, {entries_total} entries from {total} files")
    return {"done": done, "skipped": skipped, "entries": entries_total}


def ingest_recent(engine, count=5):
    """Ingest the N most recently modified JSONLs (re-processes even if done)."""
    jsonls = sorted(JSONL_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:count]
    entries_total = 0

    for f in jsonls:
        # Force re-ingest by resetting session status
        session_id = f.stem
        engine.conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        engine.conn.commit()

        result = engine.ingest_jsonl(str(f))
        entries_total += result.get("entries", 0)
        log(f"  {session_id[:8]}... → {result.get('entries', 0)} entries")

    log(f"Recent: {len(jsonls)} sessions, {entries_total} total entries")
    return {"sessions": len(jsonls), "entries": entries_total}


def watch_mode(engine, interval=60):
    """Continuous watcher — checks for new data every N seconds."""
    log(f"Watch mode started (interval: {interval}s)")
    seen_mtimes = {}

    while True:
        try:
            jsonls = list(JSONL_DIR.glob("*.jsonl"))
            for f in jsonls:
                mtime = f.stat().st_mtime
                if f.name not in seen_mtimes or seen_mtimes[f.name] < mtime:
                    result = engine.ingest_jsonl(str(f))
                    if result["status"] != "already_done":
                        log(f"Watch: {f.stem[:8]}... → {result.get('entries', 0)} new entries")
                    seen_mtimes[f.name] = mtime
        except Exception as e:
            log(f"Watch error: {e}")

        time.sleep(interval)


def embed_new(limit=2000):
    """Embed new entries into Chroma after ingestion."""
    try:
        from semantic import SemanticEngine
        sem = SemanticEngine()
        result = sem.embed_new(limit=limit)
        if result["new"] > 0:
            log(f"Embedded: {result['new']} new docs (total: {result.get('total', '?')})")
        sem.close()
    except ImportError:
        pass  # chromadb not installed
    except Exception as e:
        log(f"Embed error: {e}")


def extract_observations():
    """Extract observations and generate session summaries after ingestion."""
    try:
        from observations import ObservationExtractor
        ext = ObservationExtractor()
        r1 = ext.extract_all()
        r2 = ext.summarize_all()
        if r1["total_obs"] > 0 or r2["processed"] > 0:
            log(f"Observations: {r1['total_obs']} new, Summaries: {r2['processed']} new")
        ext.close()
    except ImportError:
        pass
    except Exception as e:
        log(f"Observation extract error: {e}")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "latest"

    # Lockfile — prevent concurrent runs (fork bomb prevention)
    # Watch mode manages its own loop, skip lock for it
    lock_fd = None
    if mode != "watch":
        lock_fd = acquire_lock()
        if lock_fd is None:
            # Another instance is already running — exit silently
            sys.exit(0)

    try:
        engine = MemoryEngine()

        if mode == "latest":
            ingest_latest(engine)
        elif mode == "all":
            ingest_all(engine)
        elif mode == "recent":
            count = int(sys.argv[2]) if len(sys.argv) > 2 else 5
            ingest_recent(engine, count)
        elif mode == "watch":
            interval = int(sys.argv[2]) if len(sys.argv) > 2 else 60
            watch_mode(engine, interval)
        elif mode == "embed":
            pass  # Just embed, no ingest
        else:
            print(f"Usage: {sys.argv[0]} [latest|all|recent N|watch N|embed]")
            sys.exit(1)

        engine.close()

        # Auto-embed after ingestion (lightweight, max 500 per run)
        if mode in ("latest", "all", "recent", "embed"):
            embed_new(limit=500)

        # Auto-extract observations after ingestion
        if mode in ("latest", "all", "recent"):
            extract_observations()

    finally:
        release_lock(lock_fd)


if __name__ == "__main__":
    main()
