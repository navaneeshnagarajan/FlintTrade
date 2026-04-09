# infra/wireguard

WireGuard VPN tunnel configuration for secure dev-to-server communication.

## Purpose

All development machines (Nitro, Mac) connect to the Ubuntu deployment server via a WireGuard tunnel. This directory holds the config templates and key management notes.

## What goes here

- **wg0.conf** templates for server and client peers
- **Key generation** instructions (never commit actual private keys)
- **Peer configs** for each development machine

## Network

- Server (Ubuntu): 10.10.10.1/24
- Nitro (Windows): 10.10.10.2/24
- Endpoint: kalamiq.ddns.net:51820

## References

- Architecture overview: `docs/ARCHITECTURE.md`
- Security hardening: `infra/security/`
- Machine setup: `docs/machine-setup/QUICKSTART.md`
