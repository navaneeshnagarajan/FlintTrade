# FlintTrade on Windows

## Option A — Docker (Recommended, easiest)
1. Install Docker Desktop: https://docs.docker.com/desktop/install/windows-install/
2. Open PowerShell:
   ```powershell
   git clone https://github.com/navaneeshnagarajan/FlintTrade.git
   cd FlintTrade
   copy .env.example .env
   notepad .env   # Add your broker credentials
   docker compose up
   ```
3. Open http://localhost:3000

## Option B — WSL2 (Native performance)
1. Install WSL2: `wsl --install`
2. Open Ubuntu terminal in WSL2
3. Follow Linux setup instructions ([docs/setup/linux.md](linux.md))

## Option C — Native Windows (Advanced)
Requires: Python 3.12, Node.js 22, Git
1. `git clone https://github.com/navaneeshnagarajan/FlintTrade.git`
2. `cd FlintTrade`
3. `copy .env.example .env`
4. `pip install -r requirements.txt`
5. `python packages/core/src/app.py`

Note: systemd not available on Windows.
Use Task Scheduler or NSSM to run as a Windows service.
