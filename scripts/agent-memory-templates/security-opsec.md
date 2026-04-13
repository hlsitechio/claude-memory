# Security-OPSEC — Persistent Knowledge Index

## Quick Reference
- Last updated: (auto-populated)
- Topics: 0 active, 0 stale, 0 archived
- Last organizer run: (bootstrap)

## Active Knowledge

### VPN Verification Protocol
- **Status**: ACTIVE (permanent — never archive)
- ALWAYS verify VPN status independently before any outbound request
- Never trust hook-reported status alone — verify with your VPN client CLI
- If VPN is down → STOP. Connect. Then proceed. No shortcuts.

### VPN ASN Detection
- **Status**: ACTIVE
- Check your ASN against known VPN provider ranges
- If ASN matches residential ISP + target is third-party → STOP, do NOT proceed
- Maintain a list of your VPN provider's known ASNs

### Your Own Assets (VPN not required)
- **Status**: ACTIVE
- localhost/127.0.0.1 — local services
- Your own domains and repositories
- Cloud-hosted MCP tools (they use cloud IPs, not yours)

### VPN Status
- **Status**: ACTIVE
- **Current**: Check with your VPN client
- **Review trigger**: When subscription status changes

## OPSEC Failure Log
(Log ALL failures here immediately — this section is append-only)

## Stale (needs review)
(none)

## Topic Files
- vpn-incidents.md — detailed incident reports
- ip-audit-log.md — all IP checks with timestamps
- asn-database.md — known VPN/residential ASNs
- _archive.md — superseded entries
