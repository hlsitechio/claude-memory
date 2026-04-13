# RedTeam-Offensive — Persistent Knowledge Index

## Quick Reference
- Last updated: 2026-02-18 09:10 EST
- Topics: 3 active, 0 stale, 0 archived
- Last organizer run: 2026-02-18 (bootstrap)

## Active Knowledge

### PoC Development Patterns
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE
- Minimal PoC principle: prove impact without damage
- RCE: `id` or `whoami`, NOT reverse shell
- SQLi: `version()`, NOT dump database
- SSRF: localhost access proof, NOT internal network scan
- LFI: `/etc/passwd`, NOT sensitive configs
- IDOR: Show access to another resource, NOT mass enumeration

### Impact Demonstration Strategies
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE
- Always show BUSINESS impact, not just technical
- "I can read any user's private messages" > "Broken access control on /api/messages"
- Chain vulns when possible: IDOR + info disclosure = account takeover story
- Screenshots/video > text descriptions
- Request/response pairs are mandatory evidence

### CVSS Scoring Heuristics
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE
- Critical (9.0-10.0): RCE, auth bypass, mass data exposure
- High (7.0-8.9): SQLi with data access, stored XSS on sensitive pages, privilege escalation
- Medium (4.0-6.9): Reflected XSS, CSRF on non-critical actions, info disclosure
- Low (0.1-3.9): Self-XSS, minor info leaks, best practice violations
- Use CVSS 3.1 calculator, always include vector string in reports

## Stale (needs review)
(none)

## Topic Files
- poc-templates.md — PoC scripts and patterns by vuln type
- exploitation-by-type.md — exploitation techniques organized by vulnerability class
- impact-demos.md — effective impact demonstration examples
- _archive.md — superseded entries
