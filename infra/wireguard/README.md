# infra/wireguard

WireGuard VPN tunnel configuration for secure dev-to-server communication.

## Purpose

Development machines connect to the Ubuntu deployment server via a WireGuard tunnel. This directory holds the config templates and key management notes.

## What goes here

- **wg0.conf** templates for server and client peers
- **Key generation** instructions (never commit actual private keys)
- **Peer configs** for each development machine

## Network (example — set your own values in a private `.env`)

- Server (Ubuntu): `<VPN_SERVER_IP>/24`
- Client (dev): `<VPN_CLIENT_IP>/24`
- Endpoint: `<YOUR_DDNS_HOSTNAME>:51820`

## References

- Architecture overview: `docs/ARCHITECTURE.md`
- Security hardening: `infra/security/`
- Machine setup: `docs/machine-setup/QUICKSTART.md`
