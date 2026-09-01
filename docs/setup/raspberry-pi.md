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
system interpreter.

## Setup (ARM64 server — advanced)

`infra/scripts/setup-production.sh` is an **Ubuntu 24.04** host provisioner.
It clones to `$HOME/FlintTrade` by default (override `FLINTTRADE_DIR`) and
copies `infra/systemd/flinttrade.service` unchanged. That unit is written for
a tree at `/opt/flinttrade` running as `www-data` behind Gunicorn on
`127.0.0.1:5100`. `sudo systemctl start flinttrade` will not find a
`$HOME/FlintTrade` checkout unless you either install the tree at
`/opt/flinttrade` (and create the `www-data` writable paths the unit lists)
or edit `User`, `WorkingDirectory`, `EnvironmentFile`, `ExecStart`, and
`ReadWritePaths` before enabling it. Relocating the tree is still not
enough: the script uses system `pip` and does not create `.venv`, while
`ExecStart` requires `/opt/flinttrade/.venv/bin/gunicorn`. `gunicorn` is
not in `requirements.lock`. Provision that venv (or point `ExecStart` at a
real gunicorn) before starting the service. See
[the systemd notes](../../infra/systemd/README.md).

Broker/OpenAlgo configuration belongs in Setup or Settings. `.env` is only for
server-only fallback values that cannot be supplied through the UI.

Note: Backtest and AI packages may be slow on Pi 4. Prefer disabling optional
modules from the workspace settings for lightweight installations.
