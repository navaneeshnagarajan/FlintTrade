# Server Machine (Ubuntu)

## Role

Pull code, verify it works, run OpenAlgo, execute trades.
This machine does NOT write new features.

## Setup (first time)

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
bash infra/scripts/setup.sh
# Configure .env with OPENALGO_API_KEY
# Configure infra/openalgo/.env with broker credentials
```

## Daily Workflow

```bash
cd ~/FlintTrade
git pull origin main
make test                      # Verify code works
make start                     # Start OpenAlgo
make status                    # Check services
```

## Commands

| Command | What |
|---|---|
| `make start` | Start OpenAlgo on port 5000 |
| `make stop` | Stop OpenAlgo gracefully |
| `make restart` | Stop then start |
| `make status` | Check OpenAlgo + disk + ports |
| `make test` | Run all tests |
| `make health` | Health check (exit 0/1) |
| `make update` | Update submodules + deps |

## Deploy Safety

- **NSE/BSE/NFO/BFO:** No deploys 9:15 AM - 3:30 PM IST
- **MCX:** No deploys 9:00 AM - 11:55 PM IST
- **DELTA (crypto):** Check open positions before any restart
- If bug found during market hours: disable strategy via OpenAlgo Action Center, fix after close

## Does NOT

- Write new features (that's the dev machine's job)
- Push commits (unless fixing a server-specific bug)
- Modify package source code
