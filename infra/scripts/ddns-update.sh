#!/bin/bash
# DDNS updater for flinttrade
# Run every 10 seconds via cron or systemd timer
# Original KalamIQ DDNS: kalamiq.ddns.net (retired)
# Current: update via No-IP API

HOSTNAME="flinttrade.ddns.net"  # Update this to your actual No-IP hostname
USERNAME="${NOIP_USERNAME}"
PASSWORD="${NOIP_PASSWORD}"

CURRENT_IP=$(curl -s https://api.ipify.org)
LAST_IP_FILE="/tmp/flinttrade_last_ip.txt"
LAST_IP=$(cat "$LAST_IP_FILE" 2>/dev/null || echo "")

if [ "$CURRENT_IP" != "$LAST_IP" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') IP changed: $LAST_IP → $CURRENT_IP"
    curl -s "https://dynupdate.no-ip.com/nic/update?hostname=$HOSTNAME&myip=$CURRENT_IP" \
        --user "$USERNAME:$PASSWORD" \
        --user-agent "FlintTrade/0.6.0 navaneeshnagarajan@gmail.com"
    echo "$CURRENT_IP" > "$LAST_IP_FILE"
fi
