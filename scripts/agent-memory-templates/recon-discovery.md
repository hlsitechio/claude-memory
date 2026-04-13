# Recon-Discovery — Persistent Knowledge Index

## Quick Reference
- Last updated: 2026-02-18 09:10 EST
- Topics: 3 active, 0 stale, 0 archived
- Last organizer run: 2026-02-18 (bootstrap)

## Active Knowledge

### Recon Phase Methodology
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE
- Phase 1 (Passive): subfinder → gau → waybackurls → cert transparency
- Phase 2 (Active): httpx probe → nmap targeted → katana crawl
- Always passive first, active only after OPSEC GREEN

### Tool Configuration Notes
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE
- nmap: `-sC -sV` for service detection, avoid `-A` on first pass (too noisy)
- subfinder: Use with `-silent` flag for clean output
- httpx: `-status-code -title -tech-detect` for quick triage
- gobuster: Use `dir` mode with SecLists wordlists
- See: tool-patterns.md (when created)

### False Positive Signatures
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE
- Wildcard DNS: Check if random subdomain resolves (if yes, subtract from results)
- CDN catch-alls: Cloudflare/Akamai default pages are NOT real targets
- Parked domains: GoDaddy/Sedo parking pages — skip

## Stale (needs review)
(none)

## Topic Files
- tool-patterns.md — detailed tool configs and flags (created as needed)
- subdomain-techniques.md — enumeration patterns per target type
- cloud-recon.md — AWS/GCP/Azure specific recon notes
- _archive.md — superseded entries
