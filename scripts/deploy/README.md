# FlintTrade — Bare-Metal Deployment

Scripts for deploying FlintTrade to Ubuntu/Debian without Docker.

## Prerequisites

- Ubuntu 22.04+ or Debian 12+
- `sudo` access
- `git`, `curl`, `make` installed
- Port 80 (Nginx), 5100 (backend), 5173 (terminal) open in firewall

## Install

```bash
# Download and run
curl -fsSL https://raw.githubusercontent.com/navaneeshnagarajan/FlintTrade/main/scripts/deploy/install.sh | bash

# Or clone the repo first, then run
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
bash FlintTrade/scripts/deploy/install.sh
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `INSTALL_DIR` | Installation path | `/opt/flinttrade` |
| `BACKEND_PORT` | Python backend port | `5100` |
| `TERMINAL_PORT` | React terminal port | `5173` |
| `BRANCH` | Git branch to install | `main` |

### Dry-run Preview

```bash
bash install.sh --dry-run
```

## Update

```bash
bash /opt/flinttrade/scripts/deploy/update.sh
```

Updates git, Python deps, rebuilds terminal, restarts services, runs smoke test.

## Uninstall

```bash
bash /opt/flinttrade/scripts/deploy/uninstall.sh
```

Removes services, Nginx config, and install directory. Prompts before removing
`~/.flinttrade` (user data). Use `--keep-data` to skip this prompt.

## Services

Both services are managed by systemd:

```bash
# Status
systemctl status flinttrade
systemctl status flinttrade-terminal

# Logs
journalctl -u flinttrade -f
journalctl -u flinttrade-terminal -f

# Restart
systemctl restart flinttrade
systemctl restart flinttrade-terminal
```

## Nginx

The install script configures Nginx as a reverse proxy automatically if
`nginx` is installed. The template at `nginx.conf.template` sets up:

- `/` → Terminal (React SPA with fallback)
- `/ft-api/` → FlintTrade backend
- `/api/` → OpenAlgo (if on same machine)
- `/ws` → WebSocket bridge

For HTTPS, use Certbot:

```bash
certbot --nginx -d yourdomain.com
```

## Testing Deploy Scripts

```bash
bash scripts/deploy/test_deploy_scripts.sh
```

Validates syntax, `--help`, `--dry-run`, template placeholders, and
idempotency markers. No root access required.
