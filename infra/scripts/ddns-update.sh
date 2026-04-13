#!/bin/bash
# DDNS updater for FlintTrade
# Run every 10 seconds via cron or systemd timer
# Reads all config from environment variables — no hardcoded providers or hostnames
set -euo pipefail

HOSTNAME="${DDNS_HOSTNAME:?DDNS_HOSTNAME not set}"
PROVIDER="${DDNS_PROVIDER:?DDNS_PROVIDER not set}"
USERNAME="${DDNS_USERNAME:-}"
PASSWORD="${DDNS_PASSWORD:-}"

CURRENT_IP=$(curl -s https://api.ipify.org)
LAST_IP_FILE="${TMPDIR:-/tmp}/flinttrade_last_ip.txt"
LAST_IP=$(cat "$LAST_IP_FILE" 2>/dev/null || echo "")

if [ "$CURRENT_IP" != "$LAST_IP" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') IP changed: $LAST_IP → $CURRENT_IP"

    case "$PROVIDER" in
        noip)
            curl -s "https://dynupdate.no-ip.com/nic/update?hostname=$HOSTNAME&myip=$CURRENT_IP" \
                --user "$USERNAME:$PASSWORD" \
                --user-agent "FlintTrade/0.6.0 ddns-updater"
            ;;
        duckdns)
            # DuckDNS uses token-based auth, pass token via DDNS_PASSWORD
            curl -s "https://www.duckdns.org/update?domains=$HOSTNAME&token=$PASSWORD&ip=$CURRENT_IP"
            ;;
        cloudflare)
            # Cloudflare requires zone_id and record_id in DDNS_USERNAME (format: zone_id:record_id)
            ZONE_ID="${USERNAME%%:*}"
            RECORD_ID="${USERNAME##*:}"
            curl -s -X PUT "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records/$RECORD_ID" \
                -H "Authorization: Bearer $PASSWORD" \
                -H "Content-Type: application/json" \
                --data "{\"type\":\"A\",\"name\":\"$HOSTNAME\",\"content\":\"$CURRENT_IP\",\"ttl\":120}"
            ;;
        dynu)
            curl -s "https://api.dynu.com/nic/update?hostname=$HOSTNAME&myip=$CURRENT_IP" \
                --user "$USERNAME:$PASSWORD" \
                --user-agent "FlintTrade/0.6.0 ddns-updater"
            ;;
        *)
            echo "ERROR: Unknown DDNS_PROVIDER '$PROVIDER'. Supported: noip, duckdns, cloudflare, dynu"
            exit 1
            ;;
    esac

    echo "$CURRENT_IP" > "$LAST_IP_FILE"
fi
