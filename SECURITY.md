# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x-alpha | :white_check_mark: Current development |

## Reporting a Vulnerability

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please report them responsibly:

1. **Email:** navaneeshnagarajan@gmail.com
2. **Subject:** `[SECURITY] FlintTrade — <brief description>`
3. **Include:**
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

You will receive an acknowledgment within 48 hours and a detailed response
within 7 days.

## Security Considerations

FlintTrade is a trading platform that connects to broker APIs. Security is critical:

### What we protect
- **API keys** — never committed to git, stored in `.env` (gitignored)
- **Broker credentials** — managed by OpenAlgo, never in FlintTrade
- **Trade data** — SEBI-compliant 5-year audit trail
- **User preferences** — stored locally in `~/.flinttrade/workspace.json`

### What we enforce
- `.env.example` has ALL values blank (open-source rule)
- No personal hostnames, IPs, or provider names in committed code
- CI/CD secrets check scans for leaked credentials
- Rate limiting on all API calls (SEBI compliance)
- WebSocket connections only via WireGuard VPN in production

### Known attack surfaces
- OpenAlgo REST API (mitigated: rate limiting, API key auth)
- WebSocket market data (mitigated: VPN-only in production)
- Local storage (mitigated: no credentials stored client-side)

## Disclosure Policy

We follow responsible disclosure. We will:
1. Acknowledge your report within 48 hours
2. Provide a timeline for the fix
3. Credit you in the fix commit (unless you prefer anonymity)
4. Not take legal action against good-faith security researchers
