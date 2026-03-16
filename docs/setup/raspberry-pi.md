# FlintTrade on Raspberry Pi

## Requirements
- Raspberry Pi 4 or 5 (4GB RAM minimum, 8GB recommended)
- Raspberry Pi OS 64-bit (Bookworm)
- 32GB+ SD card or USB SSD

## Setup (ARM64)
1. `git clone https://github.com/navaneeshnagarajan/FlintTrade.git`
2. `cd FlintTrade`
3. `bash infra/scripts/setup-production.sh`
4. `nano .env`
5. `sudo systemctl start flinttrade`

Note: Backtest and AI packages may be slow on Pi 4.
Disable them in .env: `ENABLE_BACKTEST=false ENABLE_AI=false`
