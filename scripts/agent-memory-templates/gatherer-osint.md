# Gatherer-OSINT — Persistent Knowledge Index

## Quick Reference
- Last updated: 2026-02-18 09:10 EST
- Topics: 3 active, 0 stale, 0 archived
- Last organizer run: 2026-02-18 (bootstrap)

## Active Knowledge

### OSINT Source Rankings
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE
- **Tier 1** (always check): Shodan, SecurityTrails, crt.sh, GitHub org, LinkedIn jobs
- **Tier 2** (situation-dependent): Wayback Machine, Google dorks, Censys, BuiltWith
- **Tier 3** (deep dive): SEC filings, patent databases, acquisition records
- Passive ONLY — no direct interaction with target systems

### Search Query Patterns
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE
- GitHub: `org:{company} password OR secret OR api_key OR token` — leaked secrets
- GitHub: `org:{company} filename:.env OR filename:config` — exposed configs
- Google: `site:{domain} inurl:admin OR inurl:dashboard OR inurl:login` — admin panels
- Google: `site:{domain} filetype:pdf OR filetype:xlsx OR filetype:doc` — documents
- Google: `"{company}" site:pastebin.com OR site:paste.ee` — leaked data
- Shodan: `ssl.cert.subject.cn:{domain}` — SSL cert discovery
- crt.sh: `%.{domain}` — certificate transparency subdomain enum

### Tech Detection Shortcuts
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE
- Job postings reveal: frameworks, cloud providers, databases, CI/CD tools
- Wappalyzer/BuiltWith for frontend stack
- HTTP headers: `Server`, `X-Powered-By`, `X-AspNet-Version` leak backend
- JavaScript source maps: `.js.map` files reveal original source structure
- robots.txt and sitemap.xml: Directory structure hints

## Stale (needs review)
(none)

## Topic Files
- google-dorks.md — effective dork patterns by target type
- github-queries.md — GitHub search queries that find secrets
- wayback-techniques.md — Wayback Machine analysis patterns
- _archive.md — superseded entries
