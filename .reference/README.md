# .reference/ — Design Reference Material

This directory is gitignored. It contains screenshots, scraped content,
and design notes used by AI agents across all machines.

## Sync Across Machines

This directory is NOT in the public repo. To sync between machines:

```bash
# From Nitro to Ubuntu (via WireGuard VPN):
rsync -av .reference/ user@your-server:~/FlintTrade/.reference/

# From Nitro to Mac:
scp -r .reference/ user@mac:~/FlintTrade/.reference/
```

## Structure

```
.reference/
  screenshots/          # Broker/platform UI screenshots
    oipulse/            # OiPulse dashboard, option chain, etc.
    1cliq/              # 1Cliq scalper, order panel, etc.
    dhan/               # Dhan Web trading UI
    fyers/              # FYERS Next terminal
    groww/              # Groww 915 trading UI
    indmoney/           # INDmoney trading UI
  scraped/              # HTML/markdown scraped from reference sites
  notes/                # Design decisions, audit findings, comparison tables
```

## Who uses this

Every Claude Code session on any machine can read these for UI design reference.
Never committed to git — stays local, synced manually.
