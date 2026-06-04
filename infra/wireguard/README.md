# infra/wireguard

WireGuard VPN tunnel configuration — an **optional** building block for one
self-hosted deployment example.

## Purpose

FlintTrade runs fine on a single machine with no VPN at all. If you choose to
self-host the backend on a separate box and reach it from your own devices over
an encrypted tunnel, WireGuard is one way to do that. This directory holds the
config templates and key-management notes for that optional setup.

This is **one option among several** — Docker on `localhost`, a cloud host, or a
self-hosted server are all equally valid. Nothing here is a canonical or
required deployment target; bring your own server, your own addresses, and your
own hostnames.

## What goes here

- **wg0.conf** templates for server and client peers
- **Key generation** instructions (never commit actual private keys)
- **Peer configs** for each device you connect

## Network (example — set your own values in a private, uncommitted file)

These are placeholders. Choose your own private subnet and endpoint; never
commit real addresses, hostnames, or keys.

- Server peer: `<YOUR_SERVER_VPN_IP>/24`
- Client peer: `<YOUR_CLIENT_VPN_IP>/24`
- Endpoint: `<YOUR_HOSTNAME_OR_DDNS>:51820`

## References

- Architecture overview: `docs/ARCHITECTURE.md`
- Security hardening: `infra/security/`
- Setup guides: `docs/setup/QUICKSTART.md`
