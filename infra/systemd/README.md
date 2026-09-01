# FlintTrade systemd Services

The shipped unit is `infra/systemd/flinttrade.service`. It is a **server**
template for the production prefix, not a drop-in for a developer checkout.

`infra/scripts/setup-production.sh` is the first-time Ubuntu 24.04 installer
(Python >= 3.12): it provisions `/opt/flinttrade`, creates that tree's
`.venv`, installs the hashed `requirements.lock` into it, chowns only the
runtime workspace/data/log paths to `www-data`, and copies this unit
unchanged. Operator walkthroughs are [docs/setup/linux.md](../../docs/setup/linux.md)
and [docs/setup/raspberry-pi.md](../../docs/setup/raspberry-pi.md).

For ordinary desktop use, prefer the one-line web installer in
[docs/setup/QUICKSTART.md](../../docs/setup/QUICKSTART.md) instead of systemd.
Raspberry Pi OS Bookworm (system Python 3.11) should use that one-line
installer or `infra/install/install-native.sh`, not `setup-production.sh`.

## What the unit actually assumes

Read the file before copying it. The checked-in unit is hardcoded to:

| Field | Value |
|---|---|
| `User` / `Group` | `www-data` |
| `WorkingDirectory` | `/opt/flinttrade` |
| `FLINTTRADE_HOME` | `/opt/flinttrade` |
| `FLINTTRADE_WORKSPACE_DIR` | `/opt/flinttrade/.flinttrade` (inside `ReadWritePaths`) |
| `EnvironmentFile` | `/opt/flinttrade/.env` |
| `ExecStart` | `/opt/flinttrade/.venv/bin/python -m flinttrade_core.app` |
| Bind | `127.0.0.1:5100` (Nginx is expected to reverse-proxy `/ft-api/`) |
| `ReadWritePaths` | `/opt/flinttrade/data` and `/opt/flinttrade/.flinttrade` |
| Port env | `FLINTTRADE_BACKEND_PORT=5100` — the name `flinttrade_core.app` reads. `FLINTTRADE_PORT` is a legacy alias only Docker's start helper honours. |

There are no `REPLACE_USER` / `REPLACE_DIR` placeholders. `ProtectHome=true`
means a home-directory prefix cannot start. `FLINTTRADE_DIR` is not
supported: the unit cannot be relocated without rewriting every hardcoded
path.

The git checkout and `.venv` stay root-owned and read-only to the `www-data`
group. `www-data` owns only the runtime workspace, data and log directories.
The optional `.env` is `root:www-data` mode `0640`: systemd injects it and
python-dotenv can read the same fallback after the process drops privileges.

## Install

A checkout of this repository is only the script source. The installer
provisions `/opt/flinttrade` itself.

```bash
sudo bash infra/scripts/setup-production.sh
sudoedit /opt/flinttrade/.env
sudo systemctl start flinttrade
```

Use `sudoedit` on `/opt/flinttrade/.env` only for server-only fallback values
that cannot be supplied through the app UI. Then complete Setup in the app.

`infra/scripts/deploy.sh` is the later deploy entry point. It updates the
same `/opt/flinttrade` prefix with `sudo git`, installs the hashed lock into
the unit `.venv` without taking ownership, refreshes and reloads the installed
unit on every deploy, and refuses to run during NSE cash-session hours
(9:15 AM – 3:30 PM IST).

## Usage

```bash
sudo systemctl start flinttrade     # Start FlintTrade backend on port 5100
sudo systemctl stop flinttrade      # Stop
sudo systemctl restart flinttrade   # Restart
sudo systemctl status flinttrade    # Check status
```

## Logs

```bash
journalctl -u flinttrade -f              # Live tail
journalctl -u flinttrade --since today   # Today's logs
journalctl -u flinttrade -n 50           # Last 50 lines
```

## Deploy freeze

Do not restart during market hours with open positions.

| Market | Hours (IST) |
|--------|-------------|
| NSE/BSE/NFO/BFO | 9:15 AM – 3:30 PM |
| CDS/BCD | 9:00 AM – 5:00 PM |
| MCX | 9:00 AM – 11:55 PM |
| DELTA (crypto) | 24/7 — check positions first |

If something goes wrong during market hours:

1. Hit the Kill Switch in the `/trade` workspace or `/automate` → Settings,
   or send `/kill` via the Telegram bot if you enabled it.
2. Fix and restart only after your market closes.

## Service order

1. `flinttrade.service` starts the FlintTrade backend on port 5100.
2. OpenAlgo is optional; install and start `openalgo.service` separately only
   when using the OpenAlgo integration path. That unit is a template — edit
   its paths to your OpenAlgo install before enabling it.
3. If FlintTrade fails, the unit restarts after 5 seconds (`RestartSec=5`).
