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
- Raspberry Pi OS 64-bit (Bookworm)
- 32GB+ SD card or USB SSD

## Setup (ARM64 Server)
1. `git clone https://github.com/navaneeshnagarajan/FlintTrade.git`
2. `cd FlintTrade`
3. `bash infra/scripts/setup-production.sh`
4. `sudo systemctl start flinttrade`
5. Open the terminal URL and complete Setup in the app UI.

Broker/OpenAlgo configuration belongs in Setup or Settings. `.env` is only for
server-only fallback values that cannot be supplied through the UI.

Note: Backtest and AI packages may be slow on Pi 4. Prefer disabling optional
modules from the workspace settings for lightweight installations.
