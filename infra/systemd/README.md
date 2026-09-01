# FlintTrade systemd Services

The shipped unit is `infra/systemd/flinttrade.service`. It is a **server**
template, not a drop-in for a developer checkout.

## What the unit actually assumes

Read the file before copying it. The checked-in unit is hardcoded to:

| Field | Value |
|---|---|
| `User` / `Group` | `www-data` |
| `WorkingDirectory` | `/opt/flinttrade` |
| `EnvironmentFile` | `/opt/flinttrade/.env` |
| `ExecStart` | `/opt/flinttrade/.venv/bin/gunicorn … 'flinttrade_core.app:app'` |
| Bind | `127.0.0.1:5100` (Nginx is expected to reverse-proxy `/ft-api/`) |
| `ReadWritePaths` | `/opt/flinttrade/data` and `/opt/flinttrade/.flinttrade` |
| Port env | `FLINTTRADE_PORT=5100` — the backend reads `FLINTTRADE_BACKEND_PORT`. Docker still accepts `FLINTTRADE_PORT` as a legacy fallback; this unit does not. Set `FLINTTRADE_BACKEND_PORT` in the unit or `.env` if you change the port. |

There are no `REPLACE_USER` / `REPLACE_DIR` placeholders. A `sed` replace
against those strings does nothing.

`infra/scripts/setup-production.sh` (Ubuntu 24.04) clones to
`$HOME/FlintTrade` by default and copies this unit unchanged. Relocating
the tree to `/opt/flinttrade` is not enough. The script installs Python
packages with system `pip` (`--break-system-packages --require-hashes -r
requirements.lock`). It does not create `.venv`, does not install `uv`,
and `gunicorn` is not in `requirements.lock`. The unit's `ExecStart`
still expects `/opt/flinttrade/.venv/bin/gunicorn`.

Before `systemctl start flinttrade` can succeed you must either:

1. Provision that interpreter — for example `python3 -m venv /opt/flinttrade/.venv`,
   install the lockfile into it, then install `gunicorn` into the same venv
   (it is not a locked runtime dependency); or
2. Edit `ExecStart` (and the other hardcoded paths) to the gunicorn you
   actually installed.

The pair also does not boot until the tree lives at `/opt/flinttrade` as
`www-data`, or you edit the unit to match the checkout you actually
installed.

## Install (after the unit matches the tree)

```bash
sudo cp infra/systemd/flinttrade.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable flinttrade
sudo systemctl start flinttrade
```

For ordinary use, prefer the one-line web installer in
[docs/setup/QUICKSTART.md](../../docs/setup/QUICKSTART.md) instead of
systemd.

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
2. OpenAlgo is optional; install and start it separately only when using
   the OpenAlgo integration path.
3. If FlintTrade fails, the unit restarts after 5 seconds (`RestartSec=5`).
