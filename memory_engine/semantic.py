#!/usr/bin/env python3
"""
SEMANTIC ENGINE — Vector embeddings for memory-engine.
Bridges SQLite (raw entries) → Chroma (vector search).
Uses Chroma's default embedding model (all-MiniLM-L6-v2).

Modes:
  embed     — Embed all un-embedded entries from SQLite into Chroma
  search    — Semantic search (returns similar entries by meaning)
  stats     — Show embedding stats
"""

import sys
import os
import json
import sqlite3
from datetime import datetime
from pathlib import Path

# Lazy import — chromadb is optional
try:
    import chromadb
except ImportError:
    chromadb = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DB_PATH, CHROMA_PATH, COLLECTION_NAME
BATCH_SIZE = 100  # Chroma recommends batches


class SemanticEngine:
    def __init__(self):
        if chromadb is None:
            raise ImportError("chromadb is required for semantic search. Install with: pip install chromadb")
        self.chroma = chromadb.PersistentClient(path=CHROMA_PATH)
        self.collection = self.chroma.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"description": "Memory engine conversation embeddings"}
        )
        self.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.db.row_factory = sqlite3.Row

    def embed_new(self, limit=5000):
        """Embed entries from SQLite that aren't in Chroma yet."""
        # Get IDs already in Chroma
        existing_count = self.collection.count()

        # Get entries not yet embedded — use source_line + session_id as ID
        rows = self.db.execute("""
            SELECT id, content, role, session_id, timestamp, source_line
            FROM entries
            WHERE role IN ('user', 'assistant')
            AND length(content) > 30
            AND content NOT LIKE '[TOOL:%'
            ORDER BY id ASC
        """).fetchall()

        # Filter to entries not yet in Chroma
        all_ids = [f"e_{r['id']}" for r in rows]

        # Check which exist in batches
        existing_ids = set()
        for i in range(0, len(all_ids), 500):
            batch_ids = all_ids[i:i+500]
            try:
                result = self.collection.get(ids=batch_ids, include=[])
                existing_ids.update(result["ids"])
            except Exception:
                pass

        # Filter to new entries
        new_rows = [r for r in rows if f"e_{r['id']}" not in existing_ids]

        if not new_rows:
            return {"status": "up_to_date", "existing": existing_count, "new": 0}

        # Limit batch size
        new_rows = new_rows[:limit]

        # Prepare batches
        added = 0
        for i in range(0, len(new_rows), BATCH_SIZE):
            batch = new_rows[i:i + BATCH_SIZE]

            ids = []
            documents = []
            metadatas = []

            for r in batch:
                content = r["content"]
                # Truncate for embedding (model has token limit)
                if len(content) > 2000:
                    content = content[:2000]

                doc_id = f"e_{r['id']}"
                ids.append(doc_id)
                documents.append(content)
                metadatas.append({
                    "role": r["role"],
                    "session_id": r["session_id"] or "",
                    "timestamp": r["timestamp"] or "",
                    "source_line": r["source_line"] or 0,
                    "sqlite_id": r["id"],
                })

            try:
                self.collection.add(
                    ids=ids,
                    documents=documents,
                    metadatas=metadatas,
                )
                added += len(batch)
            except Exception as e:
                print(f"Batch error at {i}: {e}")
                continue

        return {
            "status": "done",
            "existing": existing_count,
            "new": added,
            "total": existing_count + added,
        }

    def search(self, query, n_results=15, role=None, session_id=None):
        """Semantic search — find entries by meaning, not keywords."""
        where = {}
        if role:
            where["role"] = role
        if session_id:
            where["session_id"] = session_id

        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where if where else None,
            include=["documents", "metadatas", "distances"],
        )

        entries = []
        if results and results["ids"]:
            for i, doc_id in enumerate(results["ids"][0]):
                entry = {
                    "id": doc_id,
                    "content": results["documents"][0][i],
                    "distance": results["distances"][0][i],
                    "similarity": round(1 - results["distances"][0][i], 3),
                }
                if results["metadatas"]:
                    entry.update(results["metadatas"][0][i])
                entries.append(entry)

        return entries

    def hybrid_search(self, query, n_results=20, role=None, days=None):
        """Hybrid search — combines FTS keyword matches + semantic similarity.
        Returns results ranked by combined score."""
        # 1. Semantic results (vector similarity)
        sem_results = self.search(query, n_results=n_results * 2, role=role)

        # 2. FTS keyword results from SQLite
        fts_results = []
        try:
            sql = """
                SELECT e.id, e.content, e.role, e.session_id, e.timestamp, e.source_line
                FROM entries_fts fts
                JOIN entries e ON e.id = fts.rowid
                WHERE entries_fts MATCH ?
            """
            params = [query]
            if role:
                sql += " AND e.role = ?"
                params.append(role)
            if days:
                from datetime import timedelta
                cutoff = (datetime.now() - timedelta(days=days)).isoformat()
                sql += " AND e.timestamp >= ?"
                params.append(cutoff)
            sql += " ORDER BY rank LIMIT ?"
            params.append(n_results * 2)

            rows = self.db.execute(sql, params).fetchall()
            for r in rows:
                fts_results.append({
                    "id": f"e_{r['id']}",
                    "content": r["content"],
                    "role": r["role"],
                    "session_id": r["session_id"] or "",
                    "timestamp": r["timestamp"] or "",
                    "source_line": r["source_line"] or 0,
                    "sqlite_id": r["id"],
                })
        except Exception:
            pass  # FTS might fail on complex queries

        # 3. Merge and score
        scored = {}

        # Semantic: score based on similarity (0-1)
        for i, r in enumerate(sem_results):
            key = r.get("sqlite_id") or r["id"]
            sim = r.get("similarity", 0)
            scored[key] = {
                **r,
                "sem_score": sim,
                "fts_score": 0,
                "sem_rank": i + 1,
                "fts_rank": 0,
            }

        # FTS: score based on rank position
        for i, r in enumerate(fts_results):
            key = r.get("sqlite_id") or r["id"]
            fts_score = 1.0 - (i / max(len(fts_results), 1))
            if key in scored:
                scored[key]["fts_score"] = fts_score
                scored[key]["fts_rank"] = i + 1
            else:
                scored[key] = {
                    **r,
                    "sem_score": 0,
                    "fts_score": fts_score,
                    "sem_rank": 0,
                    "fts_rank": i + 1,
                    "similarity": 0,
                    "distance": 1.0,
                }

        # Combined score: weighted blend (semantic 60%, FTS 40%)
        for key in scored:
            s = scored[key]
            s["hybrid_score"] = round(s["sem_score"] * 0.6 + s["fts_score"] * 0.4, 3)

        # Sort by hybrid score
        results = sorted(scored.values(), key=lambda x: -x["hybrid_score"])
        return results[:n_results]

    def find_similar(self, entry_id, n_results=10):
        """Find entries similar to a given entry by its SQLite ID."""
        # Get the entry content
        row = self.db.execute(
            "SELECT content FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if not row:
            return []

        content = row["content"]
        if len(content) > 2000:
            content = content[:2000]

        # Search using the content as query
        results = self.search(content, n_results=n_results + 1)

        # Filter out the source entry itself
        return [r for r in results if r.get("sqlite_id") != entry_id][:n_results]

    def get_context_window(self, entry_id, window=3):
        """Get surrounding entries (before/after) for conversation context."""
        row = self.db.execute(
            "SELECT session_id, source_line FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if not row:
            return []

        rows = self.db.execute("""
            SELECT id, content, role, session_id, timestamp, source_line
            FROM entries
            WHERE session_id = ? AND source_line BETWEEN ? AND ?
            ORDER BY source_line ASC
        """, (row["session_id"], row["source_line"] - window, row["source_line"] + window)).fetchall()

        return [dict(r) for r in rows]

    def extract_related_topics(self, results, top_n=8):
        """Extract frequently mentioned words from search results as related topics."""
        from collections import Counter
        stop_words = {
            'the', 'and', 'for', 'that', 'this', 'with', 'you', 'are', 'was',
            'have', 'has', 'had', 'not', 'but', 'from', 'they', 'will', 'can',
            'all', 'been', 'would', 'there', 'their', 'what', 'when', 'who',
            'how', 'its', 'just', 'into', 'than', 'then', 'also', 'your',
            'use', 'used', 'using', 'some', 'could', 'them', 'more', 'about',
            'which', 'other', 'each', 'make', 'like', 'does', 'should', 'very',
            'true', 'false', 'none', 'null', 'let', 'here', 'where',
        }

        words = Counter()
        for r in results:
            content = r.get("content", "").lower()
            for word in content.split():
                # Clean word
                word = word.strip('.,;:!?()[]{}"\'-/\\')
                if len(word) > 3 and word not in stop_words and word.isalpha():
                    words[word] += 1

        return words.most_common(top_n)

    def stats(self):
        """Get embedding stats."""
        total_chroma = self.collection.count()
        total_sqlite = self.db.execute("""
            SELECT COUNT(*) FROM entries
            WHERE role IN ('user', 'assistant')
            AND length(content) > 30
            AND content NOT LIKE '[TOOL:%'
        """).fetchone()[0]

        return {
            "chroma_docs": total_chroma,
            "sqlite_eligible": total_sqlite,
            "coverage": f"{total_chroma / total_sqlite * 100:.1f}%" if total_sqlite > 0 else "0%",
            "collection": COLLECTION_NAME,
            "chroma_path": CHROMA_PATH,
        }

    def close(self):
        self.db.close()


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "stats"

    engine = SemanticEngine()

    if mode == "embed":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
        result = engine.embed_new(limit=limit)
        print(f"Embed: {result['new']} new docs added (total: {result.get('total', '?')})")

    elif mode == "search":
        query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "example query"
        results = engine.search(query, n_results=10)
        print(f"Semantic search: '{query}'\n")
        for r in results:
            sim = r.get("similarity", 0)
            role = r.get("role", "?")
            ts = r.get("timestamp", "?")[:19]
            content = r["content"][:200].replace("\n", " ")
            print(f"  [{sim:.3f}] [{role}] {ts}")
            print(f"    {content}")
            print()

    elif mode == "stats":
        stats = engine.stats()
        print(f"Chroma docs: {stats['chroma_docs']}")
        print(f"SQLite eligible: {stats['sqlite_eligible']}")
        print(f"Coverage: {stats['coverage']}")

    engine.close()


if __name__ == "__main__":
    main()
