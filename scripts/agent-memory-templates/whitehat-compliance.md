# WhiteHat-Compliance — Persistent Knowledge Index

## Quick Reference
- Last updated: 2026-02-18 09:10 EST
- Topics: 3 active, 0 stale, 0 archived
- Last organizer run: 2026-02-18 (bootstrap)

## Active Knowledge

### Common Program Exclusions
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE
- Almost always excluded: Social engineering, DoS/DDoS, physical attacks, spam
- Usually excluded: Self-XSS, logout CSRF, rate limiting bypass, missing headers without impact
- Sometimes excluded: Subdomain takeover (varies), open redirect without chain, clickjacking on non-sensitive pages
- Always check: Program-specific exclusions vary wildly — READ THE SCOPE

### Platform Policy Quirks
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE
- **HackerOne**: Safe harbor if in scope. Duplicate = closed. Informative = not a vuln. 90-day disclosure after fix.
- **Intigriti**: European programs. GDPR considerations. Different triage style.
- **Bugcrowd**: VDP vs paid programs — different rules. P1-P5 severity scale (not CVSS).
- **Immunefi**: Web3 focus. Smart contract bugs. Often higher payouts. Proof of exploit usually required.
- See: platform-policies.md (when detailed notes accumulate)

### Ethics Red Lines (NEVER cross)
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE (permanent — never archive)
- NEVER access real user data beyond proof of access
- NEVER cause service disruption or availability impact
- NEVER test systems outside explicit scope
- NEVER use findings for blackmail, extortion, or unauthorized disclosure
- NEVER plant persistent backdoors
- NEVER exfiltrate sensitive data
- When in doubt: STOP and ask. Better to miss a finding than cross a line.

## Stale (needs review)
(none)

## Topic Files
- scope-precedents.md — scope edge cases and how they were resolved
- platform-policies.md — detailed platform rules and differences
- exclusion-patterns.md — common exclusion patterns across programs
- _archive.md — superseded entries
