# Backup and Restore

FlintTrade can create local `.tar.gz` backups of the `~/.flinttrade` workspace.
This is a beta-stage safety feature; test restore on a temporary directory
before trusting a backup.

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

Restore into a temporary directory first:

```bash
python -m scripts.backup restore --input ~/flint-backups/flinttrade.tar.gz --target /tmp/flinttrade-restore-check
```

Use `--force` only when you intentionally want to overwrite existing files.

## Operational Notes

- Keep at least one recent restore-tested backup before changing brokers,
  auth settings, or workspace layout.
- Store archives outside the repository.
- Treat archives that include credentials as secrets.
- `make backup` and `make restore` call the operational backup scripts under
  `infra/backup/`; the Python CLI above is the portable local fallback.
