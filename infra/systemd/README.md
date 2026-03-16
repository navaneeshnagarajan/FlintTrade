# FlintTrade systemd Services

## Quick Install

```bash
# 1. Edit the service file — replace placeholders
sed -i "s|REPLACE_USER|$(whoami)|g; s|REPLACE_DIR|$(pwd)|g" infra/systemd/flinttrade.service

# 2. Copy to systemd
sudo cp infra/systemd/flinttrade.service /etc/systemd/system/

# 3. Reload and enable
sudo systemctl daemon-reload
sudo systemctl enable flinttrade
```

## Usage

```bash
sudo systemctl start flinttrade     # Start (OpenAlgo on port 5000)
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

## Deploy Freeze

**NEVER restart during market hours with open positions.**

| Market | Hours (IST) |
|--------|-------------|
| NSE/BSE/NFO/BFO | 9:15 AM – 3:30 PM |
| CDS/BCD | 9:00 AM – 5:00 PM |
| MCX | 9:00 AM – 11:55 PM |
| DELTA (crypto) | 24/7 — check positions first |

If a bug is found during market hours:
1. Send `/kill` via Telegram bot
2. Or use OpenAlgo Action Center to disable the strategy
3. Fix and deploy after your market closes

## Service Order

1. `flinttrade.service` starts OpenAlgo (port 5000) via gunicorn
2. FlintTrade packages connect to OpenAlgo's REST API
3. If OpenAlgo fails, the service auto-restarts after 5 seconds
