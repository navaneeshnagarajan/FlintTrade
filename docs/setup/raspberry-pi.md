# FlintTrade on Raspberry Pi

Raspberry Pi is an advanced server-style deployment target. For ordinary
use on Linux, macOS, or Windows, prefer the one-line web install:

```bash
# macOS / Linux
curl -fsSL https://flinttrade.vercel.app/web-install.sh | bash
```

```powershell
# Windows 10/11
# Run in a normal (non-Administrator) PowerShell window
irm https://flinttrade.vercel.app/web-install.ps1 | iex
```

If the site is unreachable those URLs answer `503` rather than the script, so
fetch it straight from GitHub instead:

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/navaneeshnagarajan/FlintTrade/main/scripts/install/flinttrade-web-install.sh | bash
```

## Requirements
- Raspberry Pi 4 or 5 (4GB RAM minimum, 8GB recommended)
- 64-bit OS whose **system** Python is `>=3.12` if you install from source
  (Ubuntu 24.04 LTS on ARM, or Raspberry Pi OS Trixie). Raspberry Pi OS
  Bookworm ships Python 3.11 and cannot meet the source-install floor.
- 32GB+ SD card or USB SSD

The one-line installer above is the supported path on a Pi: it provisions
its own Python 3.12 under `~/.flinttrade/tools` and does not use the
system interpreter. `infra/install/install-native.sh` is the other supported
Pi path when you want a bare-metal Ubuntu/Debian install with its own
Python 3.12.

## Setup (ARM64 server — advanced)

`setup-production.sh` is an Ubuntu 24.04 / Python >= 3.12 host provisioner
only. It is not the Bookworm path. It provisions `/opt/flinttrade` to match
`infra/systemd/flinttrade.service`, creates a repo-local `.venv`, and chowns
only runtime workspace/data/log paths to `www-data`. The checkout stays
root-owned. See
[the systemd notes](../../infra/systemd/README.md).

```bash
sudo bash infra/scripts/setup-production.sh
sudoedit /opt/flinttrade/.env
sudo systemctl start flinttrade
```

Broker/OpenAlgo configuration belongs in Setup or Settings. Use `sudoedit`
on `/opt/flinttrade/.env` only for server-only fallback values that cannot be
supplied through the UI.

Note: Backtest and AI packages may be slow on Pi 4. Prefer disabling optional
modules from the workspace settings for lightweight installations.
