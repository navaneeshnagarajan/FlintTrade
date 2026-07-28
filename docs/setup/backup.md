# Backup and Restore

FlintTrade can create local `.tar.gz` backups of your workspace directory,
whichever one your OS uses:

| Platform | Workspace directory |
|---|---|
| Linux | `~/.flinttrade/` |
| macOS | `~/Library/Application Support/flinttrade/` |
| Windows | `%APPDATA%\flinttrade\` |
| Override | `FLINTTRADE_WORKSPACE_DIR`, then `FLINTTRADE_HOME` (in that precedence order) |

The CLI resolves the right directory for you — you never pass it explicitly.
This is a beta-stage safety feature; test restore on a temporary directory
before trusting a backup.

Every command below runs the same way on Windows, macOS and Linux: `~` in the
paths is expanded by Python, not by your shell.

## Create a Backup

```bash
python -m scripts.backup create --output ~/flint-backups/flinttrade.tar.gz
```

Tick data is excluded by default because it can be large:

```bash
python -m scripts.backup create --output ~/flint-backups/flinttrade.tar.gz --include-ticks
```

Credential database files are excluded by default. Include them only when the
archive will be stored in an encrypted location:

```bash
python -m scripts.backup create --output ~/flint-backups/flinttrade.tar.gz --include-credentials
```

Plain-text secret seed files such as `master_password`, `api_key_pepper`,
`jwt_secret`, and `totp_install_key` are never archived.

## Restore

Restore into a temporary directory first. Pick a temporary path your OS
actually has:

```bash
# macOS / Linux
python -m scripts.backup restore --input ~/flint-backups/flinttrade.tar.gz --target /tmp/flinttrade-restore-check
```

```powershell
# Windows 10/11
python -m scripts.backup restore --input ~/flint-backups/flinttrade.tar.gz --target "$env:TEMP\flinttrade-restore-check"
```

Use `--force` only when you intentionally want to overwrite existing files.

## Operational Notes

- Keep at least one recent restore-tested backup before changing brokers,
  auth settings, or workspace layout.
- Store archives outside the repository.
- Treat archives that include credentials as secrets.
- `make backup` and `make restore` call the operational backup scripts under
  `infra/backup/`. They need make and bash, so they are POSIX-only; the Python
  CLI above is the portable path and is the only one that works on Windows.
