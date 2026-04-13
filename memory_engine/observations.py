#!/usr/bin/env python3
"""
OBSERVATION EXTRACTOR — Heuristic-based knowledge extraction from conversation entries.

Inspired by claude-mem's AI observation extraction but uses pattern matching instead
of API calls (free, fast, deterministic).

Observation Types:
  decision    — Choices made ("let's use X", "going with Y")
  bugfix      — Bugs found/fixed ("fixed", "root cause was")
  feature     — New things built ("added", "implemented", "created")
  discovery   — Things found ("found", "discovered", "[!]")
  pattern     — Recurring patterns ("always", "pattern:", "whenever")
  change      — Modifications ("updated", "changed", "refactored")
  reference   — URLs, repos, tools, packages, services mentioned (auto-bookmarked)

Observation Concepts:
  how-it-works      — Explanations of mechanisms
  why-it-exists     — Rationale and reasoning
  what-changed      — Diffs and modifications
  problem-solution  — Issue → fix pairs
  gotcha            — Pitfalls and warnings
  pattern           — Reusable patterns/approaches
  trade-off         — Pros/cons of decisions
"""

import re
import sys
import sqlite3
import os
import json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DB_PATH

# ── Pattern Definitions ────────────────────────────────────────────────

OBSERVATION_PATTERNS = {
    "decision": {
        "patterns": [
            r"(?:let'?s|we(?:'ll| will| should)?|i(?:'ll| will)?|going to) (?:use|go with|choose|pick|try|stick with|switch to|implement)\b",
            r"(?:decided|decision|choosing|picked|selected|opted) (?:to|for|on)\b",
            r"the (?:best|right|correct|better) (?:approach|choice|option|way|solution) (?:is|would be|seems)\b",
            r"(?:instead of|rather than|over) .{5,50}(?:because|since|as)\b",
        ],
        "weight": 1.5,
        "min_length": 40,
    },
    "bugfix": {
        "patterns": [
            r"\[!\].*(?:fix|bug|vuln|broken|crash|error|issue)",
            r"(?:root cause|the (?:bug|issue|problem|error) (?:was|is)|fixed (?:by|the|it))",
            r"(?:segfault|oom|memory leak|race condition|deadlock|fork bomb|corruption)",
            r"(?:was (?:broken|failing|crashing|segfaulting)|didn'?t work|wasn'?t working)",
            r"(?:the fix|patched|resolved|workaround|hotfix)",
        ],
        "weight": 2.0,
        "min_length": 30,
    },
    "feature": {
        "patterns": [
            r"(?:added|created|built|implemented|wrote|introduced|shipped) (?:a |an |the |new )?(?:\w+ ){0,3}(?:feature|function|method|class|endpoint|route|page|tool|table|view|handler|script)",
            r"(?:new|added) (?:mcp )?tool[:\s]",
            r"(?:schema|table|column|index|trigger) (?:added|created|updated)",
            r"(?:viewer|dashboard|ui|page) (?:now (?:has|shows|supports|includes))",
        ],
        "weight": 1.5,
        "min_length": 30,
    },
    "discovery": {
        "patterns": [
            r"\[\+\].*(?:found|discovered|detected|spotted|identified)",
            r"\[!\].*(?:vuln|critical|xss|sqli|ssrf|idor|rce|lfi|xxe)",
            r"(?:interesting|notable|significant|important)(?:ly)?[:\s—]",
            r"(?:turns out|it appears|apparently|surprisingly|unexpectedly)",
            r"(?:found|discovered|noticed|spotted|detected) (?:a |an |that |the )?(?:\w+ ){0,3}(?:vuln|bug|issue|endpoint|parameter|header|token|secret|key|leak)",
        ],
        "weight": 2.0,
        "min_length": 25,
    },
    "pattern": {
        "patterns": [
            r"(?:pattern|approach|strategy|technique|method|workflow|process)[:\s—]",
            r"(?:always|never|whenever|every time|consistently|typically) (?:you |we |it )?(?:should|must|need to|have to|can|will)",
            r"(?:rule of thumb|best practice|standard|convention|guideline)[:\s—]",
            r"(?:the (?:trick|key|secret|way) (?:is|to))",
        ],
        "weight": 1.0,
        "min_length": 40,
    },
    "change": {
        "patterns": [
            r"(?:updated|changed|modified|refactored|rewrote|replaced|migrated|upgraded)",
            r"(?:renamed|moved|restructured|reorganized|consolidated|merged)",
            r"(?:before|previously|used to|was originally)[:\s].{10,}(?:now|changed to|updated to|replaced (?:with|by))",
        ],
        "weight": 1.0,
        "min_length": 30,
    },
    "reference": {
        "patterns": [
            # GitHub repos
            r"https?://github\.com/[\w\-]+/[\w\-\.]+",
            # npm packages
            r"https?://(?:www\.)?npmjs\.com/package/[\w\-@/]+",
            # PyPI packages
            r"https?://pypi\.org/project/[\w\-]+",
            # Documentation sites
            r"https?://docs\.[\w\-]+\.(?:com|io|dev|org)/[\w\-/]*",
            # General meaningful URLs (not localhost, not tool results)
            r"https?://(?!127\.|localhost|0\.0\.0\.0)[\w\-]+\.(?:com|io|dev|org|net|co|app|ai|cloud|sh)/[\w\-\./?&#=%]+",
            # Package references: npm install / pip install
            r"(?:npm install|pip install|cargo add|brew install|apt install|go get)\s+[\w\-@/]+",
            # Docker images
            r"(?:docker (?:pull|run)|ghcr\.io|docker\.io)/[\w\-/:.]+",
            # MCP server references
            r"(?:mcp server|mcp tool|mcpServers)[:\s]+[\w\-]+",
        ],
        "weight": 1.5,
        "min_length": 15,
    },
}

CONCEPT_PATTERNS = {
    "how-it-works": [
        r"(?:how (?:it|this|the) works|the way (?:it|this) works|mechanism|under the hood)",
        r"(?:the flow is|the process is|what happens is|it works by|the pipeline)",
        r"(?:architecture|design|structure)[:\s—].{20,}",
    ],
    "why-it-exists": [
        r"(?:the reason|because|rationale|motivation|purpose|why (?:we|I|it))",
        r"(?:to (?:prevent|avoid|solve|handle|support|enable))\b",
        r"(?:needed|required|necessary|essential) (?:for|to|because)",
    ],
    "what-changed": [
        r"(?:changed|updated|modified) (?:from|the).{5,}(?:to|→|->)",
        r"(?:before|previously|old|was)[:\s].{5,}(?:after|now|new|is)[:\s]",
        r"(?:diff|delta|migration|upgrade|breaking change)",
    ],
    "problem-solution": [
        r"(?:problem|issue|bug)[:\s—].{10,}(?:fix|solution|resolved|workaround)[:\s—]",
        r"(?:the fix (?:was|is)|solved by|resolution|workaround)[:\s—]",
        r"(?:caused by|root cause|triggered by).{10,}(?:fixed|resolved|patched)",
    ],
    "gotcha": [
        r"(?:gotcha|pitfall|caveat|warning|careful|watch out|beware|trap|footgun)",
        r"(?:don'?t|never|avoid|be careful).{5,}(?:because|or (?:it|you|the))",
        r"(?:common mistake|easy to miss|subtle|tricky|counterintuitive)",
    ],
    "pattern": [
        r"(?:pattern|idiom|convention|best practice|anti-pattern|recipe)",
        r"(?:template|boilerplate|scaffold|blueprint|skeleton)",
        r"(?:standard (?:way|approach|pattern|practice) (?:for|to|of))",
    ],
    "trade-off": [
        r"(?:trade-?off|pro(?:s)?(?:/| and )con(?:s)?|advantage(?:s)?(?:/| and | vs )disadvantage)",
        r"(?:on one hand|on the other hand|however|but the downside|the cost is)",
        r"(?:faster but|simpler but|easier but|safer but|more .{3,20} but (?:less|more|slower))",
    ],
}


class ObservationExtractor:
    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        """Create observations and session_summaries tables if needed."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER NOT NULL,
                session_id TEXT,
                type TEXT NOT NULL,         -- decision/bugfix/feature/discovery/pattern/change/reference
                concept TEXT,               -- how-it-works/why-it-exists/github-repo/npm-package/etc
                content TEXT NOT NULL,       -- The observation text (extracted snippet or URL)
                context TEXT,               -- Surrounding conversation context
                confidence REAL DEFAULT 0,  -- Pattern match confidence (0-1)
                tags TEXT,                  -- Comma-separated tags
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (entry_id) REFERENCES entries(id),
                UNIQUE(entry_id, type, content)  -- One observation per type+content per entry
            );

            CREATE TABLE IF NOT EXISTS session_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                request TEXT,               -- What the user asked for
                investigated TEXT,          -- What was explored/searched
                learned TEXT,               -- Key findings/insights
                completed TEXT,             -- What was accomplished
                next_steps TEXT,            -- What remains / suggested next
                tools_used TEXT,            -- JSON list of tools
                entry_count INTEGER DEFAULT 0,
                duration_minutes INTEGER,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_obs_session ON observations(session_id);
            CREATE INDEX IF NOT EXISTS idx_obs_type ON observations(type);
            CREATE INDEX IF NOT EXISTS idx_obs_concept ON observations(concept);
            CREATE INDEX IF NOT EXISTS idx_obs_confidence ON observations(confidence);
            CREATE INDEX IF NOT EXISTS idx_summ_session ON session_summaries(session_id);
        """)
        self.conn.commit()

        # Migration: widen UNIQUE constraint to (entry_id, type, content) for multi-ref per entry
        try:
            # Check if old constraint exists by trying an insert that would fail under old schema
            # If observations table has old UNIQUE(entry_id, type), recreate it
            info = self.conn.execute("SELECT sql FROM sqlite_master WHERE name='observations'").fetchone()
            if info and "UNIQUE(entry_id, type)" in (info["sql"] or "") and "UNIQUE(entry_id, type, content)" not in (info["sql"] or ""):
                self.conn.executescript("""
                    ALTER TABLE observations RENAME TO observations_old;
                    CREATE TABLE observations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        entry_id INTEGER NOT NULL,
                        session_id TEXT,
                        type TEXT NOT NULL,
                        concept TEXT,
                        content TEXT NOT NULL,
                        context TEXT,
                        confidence REAL DEFAULT 0,
                        tags TEXT,
                        created_at TEXT DEFAULT (datetime('now')),
                        FOREIGN KEY (entry_id) REFERENCES entries(id),
                        UNIQUE(entry_id, type, content)
                    );
                    INSERT OR IGNORE INTO observations SELECT * FROM observations_old;
                    DROP TABLE observations_old;
                    CREATE INDEX IF NOT EXISTS idx_obs_session ON observations(session_id);
                    CREATE INDEX IF NOT EXISTS idx_obs_type ON observations(type);
                    CREATE INDEX IF NOT EXISTS idx_obs_concept ON observations(concept);
                    CREATE INDEX IF NOT EXISTS idx_obs_confidence ON observations(confidence);
                """)
                self.conn.commit()
        except Exception:
            pass  # Table is new or already migrated

    # ── Observation Extraction ──────────────────────────────────────────

    # URLs to ignore (noise from tool results, internal, or boilerplate)
    _IGNORE_URL_PATTERNS = [
        r"registry\.npmjs\.org",
        r"objects\.githubusercontent\.com",
        r"avatars\.githubusercontent\.com",
        r"camo\.githubusercontent\.com",
        r"fonts\.googleapis\.com",
        r"cdn\.jsdelivr\.net",
        r"unpkg\.com",
        r"localhost",
        r"127\.0\.0\.",
        r"0\.0\.0\.0",
        r"schemas?\.org",
        r"w3\.org",
        r"json-schema\.org",
        r"opencollective\.com",
        r"buymeacoffee",
        r"shields\.io",
        r"badge",
        r"api\.github\.com/repos/.*/tarball",  # tarball download URLs
        r"^https?://url$",  # placeholder "https://url"
        r"^https?://[\w\-]+\.[\w]+/?$",  # bare domains with no path
    ]

    def extract_from_entry(self, entry_id, content, role, session_id=None):
        """Extract observations from a single entry using pattern matching.
        Returns list of extracted observations."""
        if not content or len(content) < 25:
            return []

        # Only extract from assistant messages (they contain the decisions/findings)
        if role not in ("assistant", "user"):
            return []

        observations = []
        content_lower = content.lower()

        for obs_type, config in OBSERVATION_PATTERNS.items():
            if len(content) < config["min_length"]:
                continue

            # Use dedicated reference extractor for reference type
            if obs_type == "reference":
                refs = self._extract_references(content, entry_id, session_id)
                observations.extend(refs)
                continue

            total_score = 0
            matched_patterns = []

            for pattern in config["patterns"]:
                matches = re.findall(pattern, content_lower, re.IGNORECASE)
                if matches:
                    total_score += len(matches) * config["weight"]
                    matched_patterns.extend(matches)

            if total_score > 0:
                # Normalize confidence to 0-1 range
                confidence = min(total_score / 5.0, 1.0)

                # Only keep high-confidence observations
                if confidence >= 0.3:
                    # Detect concept
                    concept = self._detect_concept(content_lower)

                    # Extract the most relevant snippet (around the match)
                    snippet = self._extract_snippet(content, matched_patterns[0] if matched_patterns else "")

                    observations.append({
                        "entry_id": entry_id,
                        "session_id": session_id,
                        "type": obs_type,
                        "concept": concept,
                        "content": snippet,
                        "confidence": round(confidence, 3),
                    })

        return observations

    def _extract_references(self, content, entry_id, session_id):
        """Extract URLs, repos, packages, and tools as structured reference observations."""
        refs = []
        seen_urls = set()

        # ── Extract URLs ──
        url_pattern = r'https?://[^\s<>")\]\},\'`]+[^\s<>")\]\},\'`.\)]'
        urls = re.findall(url_pattern, content)

        for url in urls:
            # Clean trailing punctuation
            url = url.rstrip(".,;:!?)'\"")

            # Skip noise URLs
            if any(re.search(p, url, re.IGNORECASE) for p in self._IGNORE_URL_PATTERNS):
                continue

            # Deduplicate within this entry
            url_key = url.lower().rstrip("/")
            if url_key in seen_urls:
                continue
            seen_urls.add(url_key)

            # Classify the URL
            concept = self._classify_url(url)

            # Get surrounding context (the line containing the URL)
            ctx = self._get_url_context(content, url)

            # Higher confidence for GitHub repos, docs, and known package registries
            confidence = 0.6
            if "github.com" in url and url.count("/") >= 4:
                confidence = 0.9  # GitHub repo
            elif any(d in url for d in ["docs.", "documentation", "npmjs.com/package", "pypi.org/project"]):
                confidence = 0.85
            elif url.count("/") <= 3:
                confidence = 0.4  # Root domain, less specific

            refs.append({
                "entry_id": entry_id,
                "session_id": session_id,
                "type": "reference",
                "concept": concept,
                "content": f"{url}\n{ctx}" if ctx else url,
                "confidence": round(confidence, 3),
            })

        # ── Extract package install commands ──
        pkg_pattern = r'(?:npm install|pip install|cargo add|brew install|go get)\s+([\w\-@/.]+)'
        for match in re.finditer(pkg_pattern, content, re.IGNORECASE):
            pkg = match.group(1).strip()
            if len(pkg) > 2:
                refs.append({
                    "entry_id": entry_id,
                    "session_id": session_id,
                    "type": "reference",
                    "concept": "package",
                    "content": f"{match.group(0).strip()}\n{self._get_url_context(content, match.group(0))}",
                    "confidence": 0.8,
                })

        return refs

    def _classify_url(self, url):
        """Classify a URL into a reference concept."""
        url_lower = url.lower()
        if "github.com" in url_lower:
            return "github-repo"
        elif "npmjs.com" in url_lower:
            return "npm-package"
        elif "pypi.org" in url_lower:
            return "pypi-package"
        elif "docs." in url_lower or "documentation" in url_lower:
            return "documentation"
        elif any(d in url_lower for d in ["hub.docker.com", "ghcr.io", "docker.io"]):
            return "docker-image"
        elif any(d in url_lower for d in [".dev", "developer.", "api."]):
            return "api-or-tool"
        else:
            return "web-resource"

    def _get_url_context(self, content, target, max_ctx=150):
        """Get the line of text surrounding a URL or match for context."""
        pos = content.find(target)
        if pos == -1:
            return ""
        # Find the line containing this URL
        line_start = content.rfind("\n", 0, pos)
        line_start = line_start + 1 if line_start >= 0 else 0
        line_end = content.find("\n", pos)
        line_end = line_end if line_end >= 0 else len(content)
        line = content[line_start:line_end].strip()
        # Remove the URL itself from context to avoid duplication
        ctx = line.replace(target, "").strip(" -—:·|,")
        return ctx[:max_ctx] if ctx and len(ctx) > 5 else ""

    def _detect_concept(self, content_lower):
        """Detect the observation concept from content."""
        best_concept = None
        best_score = 0

        for concept, patterns in CONCEPT_PATTERNS.items():
            score = 0
            for pattern in patterns:
                matches = re.findall(pattern, content_lower, re.IGNORECASE)
                score += len(matches)

            if score > best_score:
                best_score = score
                best_concept = concept

        return best_concept

    def _extract_snippet(self, content, match_text, max_len=500):
        """Extract a relevant snippet around the matched text."""
        if not match_text:
            return content[:max_len]

        # Find position of match in content
        pos = content.lower().find(match_text.lower() if isinstance(match_text, str) else str(match_text))
        if pos == -1:
            return content[:max_len]

        # Get surrounding context (100 chars before, rest after)
        start = max(0, pos - 100)
        end = min(len(content), pos + max_len - 100)

        snippet = content[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."

        return snippet

    def extract_session(self, session_id, force=False):
        """Extract observations from all entries in a session."""
        # Check if already processed
        if not force:
            existing = self.conn.execute(
                "SELECT COUNT(*) FROM observations WHERE session_id = ?", (session_id,)
            ).fetchone()[0]
            if existing > 0:
                return {"status": "already_done", "session_id": session_id, "existing": existing}

        # Get all entries for this session
        entries = self.conn.execute("""
            SELECT id, content, role, session_id, timestamp
            FROM entries
            WHERE session_id = ?
            AND role IN ('user', 'assistant')
            AND length(content) > 30
            AND content NOT LIKE '[TOOL:%'
            ORDER BY source_line ASC
        """, (session_id,)).fetchall()

        if not entries:
            return {"status": "no_entries", "session_id": session_id}

        total_obs = 0
        for entry in entries:
            observations = self.extract_from_entry(
                entry["id"], entry["content"], entry["role"], session_id
            )

            for obs in observations:
                try:
                    self.conn.execute("""
                        INSERT OR IGNORE INTO observations
                        (entry_id, session_id, type, concept, content, confidence)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        obs["entry_id"], obs["session_id"], obs["type"],
                        obs["concept"], obs["content"], obs["confidence"]
                    ))
                    total_obs += 1
                except Exception:
                    pass

        self.conn.commit()
        return {"status": "done", "session_id": session_id, "observations": total_obs, "entries_scanned": len(entries)}

    def extract_all(self, force=False, limit=None):
        """Extract observations from ALL sessions."""
        sessions = self.conn.execute(
            "SELECT DISTINCT session_id FROM entries WHERE session_id IS NOT NULL ORDER BY session_id"
        ).fetchall()

        results = {"processed": 0, "skipped": 0, "total_obs": 0}
        for row in sessions:
            sid = row["session_id"]
            r = self.extract_session(sid, force=force)

            if r["status"] == "already_done":
                results["skipped"] += 1
            elif r["status"] == "done":
                results["processed"] += 1
                results["total_obs"] += r.get("observations", 0)

            if limit and results["processed"] >= limit:
                break

        return results

    # ── Session Summaries ───────────────────────────────────────────────

    def summarize_session(self, session_id, force=False):
        """Generate a structured session summary from entries."""
        # Check if already exists
        if not force:
            existing = self.conn.execute(
                "SELECT * FROM session_summaries WHERE session_id = ?", (session_id,)
            ).fetchone()
            if existing:
                return {"status": "already_done", "session_id": session_id}

        # Get entries
        entries = self.conn.execute("""
            SELECT id, content, role, timestamp, source_line
            FROM entries
            WHERE session_id = ?
            ORDER BY source_line ASC
        """, (session_id,)).fetchall()

        if not entries:
            return {"status": "no_entries", "session_id": session_id}

        # Extract structured summary
        user_msgs = []
        assistant_msgs = []
        tools_used = set()

        for e in entries:
            content = e["content"]
            if e["role"] == "user" and not content.startswith("[TOOL:") and not content.startswith("<"):
                clean = content.strip()
                if len(clean) > 15:
                    user_msgs.append(clean)
            elif e["role"] == "assistant":
                if content.startswith("[TOOL:"):
                    tool = content.split("]")[0].replace("[TOOL:", "").strip()
                    tools_used.add(tool)
                else:
                    clean = content.strip()
                    if len(clean) > 20:
                        assistant_msgs.append(clean)

        # REQUEST: first meaningful user message
        request = user_msgs[0][:500] if user_msgs else "No user request captured"

        # INVESTIGATED: tools used + key topics from user messages
        investigated_parts = []
        if tools_used:
            investigated_parts.append(f"Tools: {', '.join(sorted(tools_used)[:15])}")
        # Extract key topics from user messages
        for msg in user_msgs[1:5]:  # Skip first (that's the request)
            short = msg[:150].replace("\n", " ")
            if len(short) > 20:
                investigated_parts.append(short)
        investigated = "\n".join(investigated_parts[:8]) if investigated_parts else "No investigation recorded"

        # LEARNED: assistant findings with [!] or [+] markers, or discovery observations
        learned_parts = []
        for msg in assistant_msgs:
            # Look for finding markers
            lines = msg.split("\n")
            for line in lines:
                stripped = line.strip()
                if stripped.startswith(("[!", "[+]", "Finding", "Discovery", "Vuln")):
                    if len(stripped) > 20:
                        learned_parts.append(stripped[:200])
        learned = "\n".join(learned_parts[:10]) if learned_parts else "No explicit findings recorded"

        # COMPLETED: look for success markers in assistant messages
        completed_parts = []
        for msg in assistant_msgs[-10:]:  # Last 10 assistant messages
            lines = msg.split("\n")
            for line in lines:
                stripped = line.strip()
                if any(kw in stripped.lower() for kw in ["completed", "done", "fixed", "deployed", "created", "built", "shipped"]):
                    if len(stripped) > 15 and len(stripped) < 300:
                        completed_parts.append(stripped[:200])
                elif stripped.startswith("- [x]"):
                    completed_parts.append(stripped[:200])
        completed = "\n".join(completed_parts[:10]) if completed_parts else "No completion markers found"

        # NEXT_STEPS: look for [>] markers or "next" in last messages
        next_parts = []
        for msg in assistant_msgs[-5:]:
            lines = msg.split("\n")
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("[>]") or "next step" in stripped.lower() or stripped.startswith("- [ ]"):
                    if len(stripped) > 10:
                        next_parts.append(stripped[:200])
        next_steps = "\n".join(next_parts[:5]) if next_parts else "No next steps recorded"

        # Calculate duration
        duration = None
        timestamps = [e["timestamp"] for e in entries if e["timestamp"]]
        if len(timestamps) >= 2:
            try:
                first = datetime.fromisoformat(timestamps[0].rstrip("Z"))
                last = datetime.fromisoformat(timestamps[-1].rstrip("Z"))
                duration = int((last - first).total_seconds() / 60)
            except Exception:
                pass

        # Save
        try:
            self.conn.execute("""
                INSERT OR REPLACE INTO session_summaries
                (session_id, request, investigated, learned, completed, next_steps,
                 tools_used, entry_count, duration_minutes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                session_id, request, investigated, learned, completed, next_steps,
                json.dumps(sorted(tools_used)), len(entries), duration
            ))
            self.conn.commit()
        except Exception as e:
            return {"status": "error", "session_id": session_id, "error": str(e)}

        return {
            "status": "done",
            "session_id": session_id,
            "entries": len(entries),
            "tools": len(tools_used),
            "duration_min": duration,
        }

    def summarize_all(self, force=False, limit=None):
        """Generate summaries for all sessions."""
        sessions = self.conn.execute(
            "SELECT DISTINCT session_id FROM entries WHERE session_id IS NOT NULL ORDER BY session_id"
        ).fetchall()

        results = {"processed": 0, "skipped": 0}
        for row in sessions:
            sid = row["session_id"]
            r = self.summarize_session(sid, force=force)

            if r["status"] == "already_done":
                results["skipped"] += 1
            elif r["status"] == "done":
                results["processed"] += 1

            if limit and results["processed"] >= limit:
                break

        return results

    # ── Query Methods ───────────────────────────────────────────────────

    def get_observations(self, obs_type=None, concept=None, session_id=None,
                         min_confidence=0.3, limit=50):
        """Query observations with filters."""
        sql = "SELECT * FROM observations WHERE confidence >= ?"
        params = [min_confidence]

        if obs_type:
            sql += " AND type = ?"
            params.append(obs_type)
        if concept:
            sql += " AND concept = ?"
            params.append(concept)
        if session_id:
            sql += " AND session_id = ?"
            params.append(session_id)

        sql += " ORDER BY confidence DESC, created_at DESC LIMIT ?"
        params.append(limit)

        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def get_session_summary(self, session_id):
        """Get a session summary."""
        row = self.conn.execute(
            "SELECT * FROM session_summaries WHERE session_id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_recent_summaries(self, limit=10):
        """Get the most recent session summaries."""
        rows = self.conn.execute("""
            SELECT * FROM session_summaries
            ORDER BY updated_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def observation_stats(self):
        """Get observation statistics."""
        total = self.conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

        by_type = {}
        for row in self.conn.execute(
            "SELECT type, COUNT(*) as cnt FROM observations GROUP BY type ORDER BY cnt DESC"
        ).fetchall():
            by_type[row["type"]] = row["cnt"]

        by_concept = {}
        for row in self.conn.execute(
            "SELECT concept, COUNT(*) as cnt FROM observations WHERE concept IS NOT NULL GROUP BY concept ORDER BY cnt DESC"
        ).fetchall():
            by_concept[row["concept"]] = row["cnt"]

        summaries = self.conn.execute("SELECT COUNT(*) FROM session_summaries").fetchone()[0]
        sessions = self.conn.execute("SELECT COUNT(DISTINCT session_id) FROM entries").fetchone()[0]

        avg_confidence = self.conn.execute(
            "SELECT AVG(confidence) FROM observations"
        ).fetchone()[0] or 0

        return {
            "total_observations": total,
            "by_type": by_type,
            "by_concept": by_concept,
            "session_summaries": summaries,
            "total_sessions": sessions,
            "summary_coverage": f"{summaries}/{sessions}" if sessions else "0/0",
            "avg_confidence": round(avg_confidence, 3),
        }

    # ── Context Injection ───────────────────────────────────────────────

    def get_context_injection(self, max_observations=20, max_tokens=2000):
        """Generate context injection block for session start.
        Returns structured XML-like block with recent observations and summaries."""
        # Get recent high-confidence observations
        obs = self.conn.execute("""
            SELECT o.*, e.timestamp
            FROM observations o
            JOIN entries e ON e.id = o.entry_id
            WHERE o.confidence >= 0.5
            ORDER BY e.timestamp DESC
            LIMIT ?
        """, (max_observations,)).fetchall()

        # Get last 3 session summaries
        summaries = self.conn.execute("""
            SELECT * FROM session_summaries
            ORDER BY updated_at DESC
            LIMIT 3
        """).fetchall()

        lines = ["<memory-context>"]

        if summaries:
            lines.append("  <recent-sessions>")
            for s in summaries:
                sid = s["session_id"][:8]
                lines.append(f"    <session id=\"{sid}\">")
                lines.append(f"      <request>{(s['request'] or '')[:200]}</request>")
                lines.append(f"      <completed>{(s['completed'] or '')[:200]}</completed>")
                if s["next_steps"] and s["next_steps"] != "No next steps recorded":
                    lines.append(f"      <next>{(s['next_steps'] or '')[:150]}</next>")
                lines.append(f"    </session>")
            lines.append("  </recent-sessions>")

        if obs:
            lines.append("  <observations>")
            for o in obs:
                ts = o["timestamp"][:10] if o["timestamp"] else "?"
                concept_attr = f' concept="{o["concept"]}"' if o["concept"] else ""
                content = o["content"][:150].replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")
                lines.append(f'    <obs type="{o["type"]}"{concept_attr} date="{ts}" conf="{o["confidence"]}">{content}</obs>')
            lines.append("  </observations>")

        lines.append("</memory-context>")

        result = "\n".join(lines)

        # Rough token estimate (4 chars per token)
        if len(result) > max_tokens * 4:
            # Truncate observations
            result = result[:max_tokens * 4]
            result = result[:result.rfind("</obs>") + 6] + "\n  </observations>\n</memory-context>"

        return result

    def close(self):
        self.conn.close()


# ── CLI ─────────────────────────────────────────────────────────────────

def main():
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "stats"

    extractor = ObservationExtractor()

    if mode == "extract":
        # Extract observations from all sessions
        force = "--force" in sys.argv
        limit = None
        for arg in sys.argv[2:]:
            if arg.isdigit():
                limit = int(arg)
        result = extractor.extract_all(force=force, limit=limit)
        print(f"[+] Extracted: {result['total_obs']} observations from {result['processed']} sessions ({result['skipped']} skipped)")

    elif mode == "summarize":
        # Generate session summaries
        force = "--force" in sys.argv
        result = extractor.summarize_all(force=force)
        print(f"[+] Summarized: {result['processed']} sessions ({result['skipped']} skipped)")

    elif mode == "context":
        # Generate context injection block
        context = extractor.get_context_injection()
        print(context)

    elif mode == "stats":
        stats = extractor.observation_stats()
        print(f"Observations: {stats['total_observations']}")
        print(f"Session summaries: {stats['summary_coverage']}")
        print(f"Avg confidence: {stats['avg_confidence']}")
        print(f"\nBy type:")
        for t, c in stats["by_type"].items():
            print(f"  {t}: {c}")
        print(f"\nBy concept:")
        for t, c in stats["by_concept"].items():
            print(f"  {t}: {c}")

    elif mode == "query":
        obs_type = sys.argv[2] if len(sys.argv) > 2 else None
        results = extractor.get_observations(obs_type=obs_type, limit=20)
        for r in results:
            concept = f" [{r['concept']}]" if r.get("concept") else ""
            print(f"[{r['type']}]{concept} conf:{r['confidence']} | {r['content'][:200]}")
            print()

    elif mode == "inject":
        # Full pipeline: extract + summarize + inject
        print("[*] Running full observation pipeline...")
        r1 = extractor.extract_all()
        print(f"  Observations: {r1['total_obs']} extracted, {r1['skipped']} skipped")
        r2 = extractor.summarize_all()
        print(f"  Summaries: {r2['processed']} generated, {r2['skipped']} skipped")
        ctx = extractor.get_context_injection()
        print(f"\n{ctx}")

    extractor.close()


if __name__ == "__main__":
    main()
