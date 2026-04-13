#!/usr/bin/env python3
"""
BATCH EMBEDDER — Memory-safe incremental embedding.
Uses offset-based pagination — never loads full dataset.
Usage: python3 embed-batch.py [batch_size] [max_total]
"""

import sys
import os
import gc
import time
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DB_PATH, CHROMA_PATH, COLLECTION_NAME

BATCH_SIZE = int(sys.argv[1]) if len(sys.argv) > 1 else 100
MAX_TOTAL = int(sys.argv[2]) if len(sys.argv) > 2 else 50000


def main():
    import chromadb

    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    col = client.get_or_create_collection(COLLECTION_NAME)

    initial_count = col.count()
    total_added = 0
    offset = 0
    batch_num = 0

    # Flush output immediately
    print(f"[*] Batch embed: size={BATCH_SIZE}, max={MAX_TOTAL}", flush=True)
    print(f"[i] Chroma starting count: {initial_count}", flush=True)

    while total_added < MAX_TOTAL:
        # Paginated fetch from SQLite
        rows = db.execute("""
            SELECT id, content, role, session_id, timestamp, source_line
            FROM entries
            WHERE role IN ('user', 'assistant')
            AND length(content) > 30
            AND content NOT LIKE '[TOOL:%'
            ORDER BY id ASC
            LIMIT ? OFFSET ?
        """, (BATCH_SIZE, offset)).fetchall()

        if not rows:
            print(f"[+] Reached end of entries at offset {offset}", flush=True)
            break

        offset += len(rows)

        # Check which of these are already in Chroma
        batch_ids = [f"e_{r[0]}" for r in rows]
        try:
            existing = set(col.get(ids=batch_ids, include=[])["ids"])
        except Exception:
            existing = set()

        # Filter to new entries only
        new_rows = [(r, f"e_{r[0]}") for r in rows if f"e_{r[0]}" not in existing]

        if not new_rows:
            continue  # All in this batch already embedded, move to next

        # Prepare and embed
        ids = []
        documents = []
        metadatas = []

        for r, doc_id in new_rows:
            content = r[1]
            if len(content) > 2000:
                content = content[:2000]

            ids.append(doc_id)
            documents.append(content)
            metadatas.append({
                "role": r[2] or "",
                "session_id": r[3] or "",
                "timestamp": r[4] or "",
                "source_line": r[5] or 0,
                "sqlite_id": r[0],
            })

        try:
            col.add(ids=ids, documents=documents, metadatas=metadatas)
            total_added += len(ids)
            batch_num += 1
            print(f"[+] Batch {batch_num}: +{len(ids)} (total new: {total_added:,}, offset: {offset})", flush=True)
        except Exception as e:
            print(f"[-] Error at batch {batch_num}: {e}", flush=True)
            break

        # GC + brief pause
        del new_rows, ids, documents, metadatas, rows
        gc.collect()
        time.sleep(0.3)

    final_count = col.count()
    print(f"\n[+] Done: +{total_added:,} new docs", flush=True)
    print(f"[+] Final Chroma count: {final_count:,}", flush=True)
    db.close()


if __name__ == "__main__":
    main()
