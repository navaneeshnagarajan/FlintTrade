# FlintTrade on macOS

## Option A — Docker (Recommended)
1. Install Docker Desktop: https://docs.docker.com/desktop/install/mac-install/
2. Open Terminal:
   ```bash
   git clone https://github.com/navaneeshnagarajan/FlintTrade.git
   cd FlintTrade
   cp .env.example .env
   open .env   # Add your broker credentials
   docker compose up
   ```
3. Open http://localhost:3000

## Option B — Native macOS
Requires: Python 3.12 (`brew install python`), Node.js 22 (`brew install node`)
1. `git clone https://github.com/navaneeshnagarajan/FlintTrade.git`
2. `cd FlintTrade`
3. `cp .env.example .env`
4. `pip3 install -r requirements.txt`
5. `python3 packages/core/src/app.py`

Note: launchd plist available at `infra/launchd/flinttrade.plist`
