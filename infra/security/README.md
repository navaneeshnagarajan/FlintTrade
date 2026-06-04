# infra/security

Server-hardening configurations — an **optional** building block for one
self-hosted deployment example.

## Purpose

If you choose to self-host FlintTrade (with optional OpenAlgo-compatible
integrations) on a server you control, this directory holds example hardening
configs you can adapt. They are illustrative, not prescriptive: harden the box
to suit your own environment.

This is **one option among several** — running everything on `localhost`, in
Docker, or on a managed cloud host are all equally valid. There is no single
canonical deployment target. Bring your own server, your own addresses, and
your own hostnames.

## What goes here

- **fail2ban** — example jail configs for SSH and the exposed HTTP / WebSocket
  ports
- **firewall** — example rules (UFW, nftables, or your platform's equivalent)
  allowing only the ports you actually expose
- **sshd_config** — hardened SSH settings (key-only auth, no root login)
- **rate limiting** — example reverse-proxy or firewall rate-limit rules for API
  endpoints

Treat every value as a placeholder. Never commit real IP addresses, hostnames,
or secrets.

## References

- Architecture overview: `docs/ARCHITECTURE.md`
- Setup guides: `docs/setup/QUICKSTART.md`
- WireGuard tunnel config (optional): `infra/wireguard/`
