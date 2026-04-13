# BlueTeam-Defensive — Persistent Knowledge Index

## Quick Reference
- Last updated: 2026-02-18 09:10 EST
- Topics: 3 active, 0 stale, 0 archived
- Last organizer run: 2026-02-18 (bootstrap)

## Active Knowledge

### WAF Fingerprint Database
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE
- Cloudflare: Most common. cf-ray header, __cfduid cookie, challenge pages
- AWS WAF: x-amzn-requestid, 403 with XML body
- Akamai: akamai-grn header, reference number in error pages
- Imperva/Incapsula: visid_incap cookie, incap_ses cookie
- ModSecurity: Server header sometimes leaks, 403 with "Mod_Security" string
- See: waf-signatures.md (when detailed signatures accumulate)

### CDN Detection & Origin IP Discovery
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE
- Check historical DNS (SecurityTrails, ViewDNS.info) for pre-CDN IPs
- Check non-proxied subdomains (mail., ftp., direct., cpanel.)
- Check SSL cert Subject Alternative Names for related domains
- Check MX records — mail servers often reveal origin IP
- Check SPF records — ip4: entries may include origin

### Security Header Analysis Guide
- **Created**: 2026-02-18 09:10 EST
- **Status**: ACTIVE
- CSP: Look for `unsafe-inline`, `unsafe-eval`, wildcard sources (weak CSP = XSS possible)
- HSTS: Missing = potential SSL stripping
- X-Frame-Options: Missing = clickjacking possible
- X-Content-Type-Options: Missing = MIME sniffing attacks
- Referrer-Policy: Missing or `no-referrer` = referrer-based attacks possible
- Permissions-Policy: Check for camera, microphone, geolocation permissions

## Stale (needs review)
(none)

## Topic Files
- waf-signatures.md — detailed WAF detection signatures and response patterns
- cloudflare-bypass.md — Cloudflare-specific evasion and origin discovery
- rate-limits.md — rate limit detection and evasion patterns
- _archive.md — superseded entries
