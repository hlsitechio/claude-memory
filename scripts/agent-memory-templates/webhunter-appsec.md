# WebHunter-AppSec — Persistent Knowledge Index

## Quick Reference
- Last updated: 2026-02-18 09:10 EST
- Topics: 3 active, 0 stale, 0 archived
- Last organizer run: 2026-02-18 (bootstrap)

## Active Knowledge

### OWASP Testing Methodology
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE
- Phase 1 (Automated): nuclei → nikto → arjun (parameter discovery)
- Phase 2 (Injection): sqlmap on params → dalfox on inputs → ffuf/wfuzz on endpoints
- Phase 3 (Manual): playwright verification → evidence capture → reproduction steps
- Always capture request/response pairs for evidence

### Dark Web OPSEC Checklist
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE
- Step 1: Verify VPN ON (`~/.local/bin/vpn-connect status`)
- Step 2: Verify TOR active (`systemctl is-active tor`)
- Step 3: Verify TOR routing (`~/.local/bin/torwrap curl -s https://check.torproject.org/api/ip`)
- Step 4: Only THEN access .onion sites
- NEVER access dark web without VPN + TOR double protection
- Use `~/.local/bin/torwrap` for all .onion requests
- Dark web search engines: ahmia, torch, haystak, duckduckgo, excavator

### Tool Effectiveness Notes
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE
- nuclei: Great for known CVE patterns, template-based. Update templates regularly
- dalfox: Good XSS scanner, catches reflected/stored. Use with `-b` for blind XSS callback
- sqlmap: Use `--risk=2 --level=3` for thorough testing, `--random-agent` to avoid detection
- arjun: Hidden parameter discovery — run BEFORE injection testing
- See: tool-patterns.md (when detailed notes accumulate)

## Stale (needs review)
(none)

## Topic Files
- xss-payloads.md — successful XSS payloads + WAFs they bypassed
- sqli-techniques.md — injection patterns by database type
- waf-bypasses.md — WAF-specific evasion techniques
- nuclei-templates.md — template effectiveness tracking
- _archive.md — superseded entries
