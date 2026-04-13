# Memory-Organizer — Persistent Knowledge Index

## Quick Reference
- Last updated: 2026-02-18 09:10 EST
- Topics: 2 active, 0 stale, 0 archived
- Last organizer run: 2026-02-18 (bootstrap — first run)

## Processing State
- Last processed: BOOTSTRAP (no prior runs)
- Last session processed: none yet
- Total items distributed: 0 (bootstrap seeds don't count)

## Active Knowledge

### Agent Memory Directory Map
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE
- All dirs at: `~/.claude/agent-memory/<name>/`
- 10 agents total: recon-discovery, webhunter-appsec, redteam-offensive, blueteam-defensive, gatherer-osint, security-opsec, reporter-documentation, whitehat-compliance, exploit-blackops, memory-organizer
- Each has: MEMORY.md (200-line index) + topic files (unlimited)
- MEMORY.md is auto-injected at agent boot (first 200 lines)

### Data Source Locations
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE
- Session JSONLs: `~/.claude/projects/<project-dir>/*.jsonl`
- MCI markers: `$MEMORY_BASE/memory_sessions/*/session-*/facts.md` (and context.md, intent.md, memory.md)
- Compact summaries: `$MEMORY_BASE/memory_sessions/*/session-*/compact-*.md`
- Memory Engine DB: `$MEMORY_ENGINE_DIR/memory.db`
- Subagent transcripts: `~/.claude/projects/<project-dir>/*/subagents/`

## Processing Log
(Append every run here)
- 2026-02-18 09:10: BOOTSTRAP — initial templates created for all 10 agents

## Stale (needs review)
(none)

## Topic Files
- processing-history.md — detailed log of every organizer run
- distribution-log.md — what knowledge went to which agent, when
- archive-log.md — what was archived/deleted and why
- _archive.md — superseded entries
