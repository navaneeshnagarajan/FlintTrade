# FlintTrade on Linux (Ubuntu/Debian)

## Option A — Docker (Recommended)
1. Install Docker: `curl -fsSL https://get.docker.com | sh`
2. ```bash
   git clone https://github.com/navaneeshnagarajan/FlintTrade.git
   cd FlintTrade && cp .env.example .env
   docker compose up
   ```
3. Open http://localhost:5173

## Option B — Native (Production, recommended for 24/7 servers)
1. `git clone https://github.com/navaneeshnagarajan/FlintTrade.git`
2. `cd FlintTrade`
3. `bash infra/scripts/setup-production.sh`
4. `nano .env`   # Add credentials
5. `sudo systemctl start flinttrade`
