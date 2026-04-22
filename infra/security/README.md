# infra/security

Server hardening configurations for the Ubuntu deployment target.

## Purpose

This directory holds production security configs that are applied on the Ubuntu deployment server to protect the FlintTrade + OpenAlgo stack.

## What goes here

- **fail2ban** — jail configs for SSH, Flask (OpenAlgo port 5000), and WebSocket (port 8765)
- **UFW** — firewall rules allowing only required ports (22, 5000, 5173, 8765, 9090, 51820)
- **sshd_config** — hardened SSH settings (key-only auth, no root login)
- **rate limiting** — nginx or iptables rate-limit rules for API endpoints

## References

- Architecture overview: `docs/ARCHITECTURE.md`
- Deployment guide: `docs/machine-setup/QUICKSTART.md`
- WireGuard tunnel config: `infra/wireguard/`
