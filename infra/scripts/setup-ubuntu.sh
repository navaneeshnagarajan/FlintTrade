#!/bin/bash
set -euo pipefail
echo "=== FlintTrade Ubuntu Setup ==="
sudo apt update && sudo apt install -y python3 python3-pip python3-venv nginx git curl jq fail2ban ufw
command -v node || (curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs)
sudo mkdir -p /data/flinttrade/{historical,ticks,audit,backups} /var/log/flinttrade
sudo chown -R $USER:$USER /data/flinttrade /var/log/flinttrade
make setup
echo "✅ Run: make start, then complete Setup/Settings in the app UI"
