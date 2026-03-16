# FlintTrade systemd Services

## Install

Before installing, edit `flinttrade.service` and replace the placeholder values:
- `REPLACE_WITH_YOUR_USERNAME` → your Linux username
- `REPLACE_WITH_INSTALL_DIR` → path to your FlintTrade clone (e.g. `/home/youruser/FlintTrade`)

```bash
sudo cp flinttrade.service /etc/systemd/system/
sudo cp openalgo.service /etc/systemd/system/
sudo systemctl daemon-reload
```

## Enable (auto-start on boot)

```bash
sudo systemctl enable openalgo
sudo systemctl enable flinttrade
```

## Start / Stop

```bash
sudo systemctl start flinttrade    # starts after openalgo
sudo systemctl stop flinttrade
sudo systemctl restart flinttrade
```

## Logs

```bash
journalctl -u flinttrade -f         # live tail
journalctl -u flinttrade --since today
journalctl -u openalgo -f           # OpenAlgo logs
```

## Deploy Freeze

**NEVER restart flinttrade or openalgo between 9:15 AM - 3:30 PM IST** when
equity/F&O positions are open. MCX extends to 11:55 PM. Crypto (DELTA) is 24/7.

If a bug is found during market hours:
1. Use OpenAlgo Action Center to disable the strategy
2. Or send `/kill` via Telegram bot
3. Fix the code after market close (3:30 PM for equity)
4. Then `sudo systemctl restart flinttrade`

## Service Order

1. `openalgo.service` starts first (port 5000)
2. `flinttrade.service` starts after (reads from OpenAlgo API)
3. If OpenAlgo is slow to start, FlintTrade warns but does not crash
