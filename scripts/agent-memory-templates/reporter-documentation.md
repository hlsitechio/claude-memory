# Reporter-Documentation — Persistent Knowledge Index

## Quick Reference
- Last updated: 2026-02-18 09:10 EST
- Topics: 4 active, 0 stale, 0 archived
- Last organizer run: 2026-02-18 (bootstrap)

## Active Knowledge

### CRITICAL: Anti-AI-Slop Doctrine
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE (permanent — never archive)
- The AI slop crisis (2025-2026) changed everything. 50-70% of submissions rejected industry-wide.
- Reports MUST be the opposite of slop: working PoC, reproducible steps, attacker narrative
- No walls of technical background. No scanner output dumps. No "this COULD potentially lead to..."
- The PoC IS the report. Not the words around it.
- Write human — short, direct, YOUR voice. Not AI template, not ChatGPT grammar.
- No perfect grammar / formal tone (it screams AI)

### The Three Triager Questions
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE (permanent)
- **Q1: Is it real?** → Working PoC, not theory
- **Q2: Can I reproduce it?** → Steps a monkey could follow in 5 minutes
- **Q3: So what?** → "Attacker can do X to your users RIGHT NOW"
- Everything else is noise. If your report doesn't answer all three → don't submit.

### Platform Format Differences
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE
- **HackerOne**: Markdown format. Severity + CVSS required. Supports attachments inline. Template at `/path/to/hackerone/templates/`
- **Intigriti**: Similar to H1 but European programs. Template at `/path/to/intigriti/templates/`
- **Bugcrowd**: VDP + paid. Different submission flow.
- **Immunefi**: Web3/blockchain focus. Smart contract PoCs. High payouts.
- See: platform-templates.md (when detailed notes accumulate)

### Report Quality Checklist (pre-submit)
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE
- [ ] Verified it's real — not a scanner false positive, not an AI hallucination
- [ ] Verified it's exploitable — working PoC or it doesn't exist
- [ ] Verified it's not a dupe — check disclosed reports on the platform
- [ ] Written human — short, direct, YOUR voice
- [ ] Shows impact from attacker perspective — "I can do THIS to you"
- [ ] Includes visual proof — screenshot, video, request/response
- [ ] Title is clear: `[SEVERITY] Vuln Type in Component`

## Stale (needs review)
(none)

## Topic Files
- hackerone-templates.md — H1 report templates and formatting tips
- rejection-analysis.md — why reports got rejected + lessons
- report-history.md — submitted reports, outcomes, status
- triager-preferences.md — what triagers like/hate per platform
- _archive.md — superseded entries
