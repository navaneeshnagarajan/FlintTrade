# FlintTrade on macOS

## Option A — Docker (Recommended)
1. Install Docker Desktop: https://docs.docker.com/desktop/install/mac-install/
2. Open Terminal:
   ```bash
   git clone https://github.com/navaneeshnagarajan/FlintTrade.git
   cd FlintTrade
   cp .env.example .env
   open .env   # Optional: add FLINTTRADE_API_KEY and OpenAlgo bridge settings
   docker compose up
   ```
3. Open http://localhost:5173

## Option B — Native macOS
Requires: Python 3.12 (`brew install python`), Node.js 22 (`brew install node`)
1. `git clone https://github.com/navaneeshnagarajan/FlintTrade.git`
2. `cd FlintTrade`
3. `cp .env.example .env`
4. `pip3 install -r requirements.txt`
5. `python3 packages/core/core/src/app.py`

Note: For background-service supervision on macOS, write a launchd plist that runs `make start` from your repo root. A sample plist may be added to `infra/launchd/` in a future release; until then, the systemd unit at `infra/systemd/openalgo.service` is the closest reference.
