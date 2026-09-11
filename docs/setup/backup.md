# Backup and Restore

Ordinary backups are **bhavcopy CSV archives**, not full workspace or
credential snapshots.

The remaining portable path is the Python CLI. It creates a local `.tar.gz`
of the composition-registered bhavcopy family under the workspace
(`data/bhavcopy/{equity,fo,index,full}/*.csv`). It does **not** archive
workspace settings, broker credentials, installation security material, live
databases, tick stores, or service-connection state.

The CLI resolves the workspace directory for you — you never pass it
explicitly:

| Platform | Workspace directory |
|---|---|
| Linux | `~/.flinttrade/` |
| macOS | `~/Library/Application Support/flinttrade/` |
| Windows | `%APPDATA%\flinttrade\` |
| Override | `FLINTTRADE_WORKSPACE_DIR`, then `FLINTTRADE_HOME` (in that precedence order) |

Every command below runs the same way on Windows, macOS and Linux: `~` in the
paths is expanded by Python, not by your shell.

Authority-bearing archives and restores into the live workspace are unavailable
until a coordinated restore transaction exists. Those operations fail with
`coordinated_restore_unavailable`.

## Create an ordinary backup

```bash
python -m scripts.backup create --output ~/flint-backups/flinttrade.tar.gz
```

The archive is written outside the workspace. A destination inside the live
workspace or installation-security tree is refused.

`--include-credentials` is a reserved compatibility flag. It fails immediately
with `coordinated_restore_unavailable` and does not collect credential stores.

`--include-ticks` does not add live tick stores. Unclassified live stores
remain unavailable and fail closed with the same code.

Secret seed files such as `master_password`, `api_key_pepper`, `jwt_secret`,
`totp_install_key`, and `safety_gate_secret` are never archived.
`workspace.json`, `auth.db`, `credentials.db`, and the other registered
authority namespaces are excluded.

Each archive embeds a `manifest.json` at the root so `list` can read metadata
without extracting the payload.

## Restore (disjoint target only)

Restore into a directory that is **not** the active workspace and is not
nested under it. A restore whose destination is the live authority tree fails
with `coordinated_restore_unavailable`.

The CLI default (no `--target`) resolves to the live workspace and therefore
fails closed. Always pass `--target`:

```bash
# macOS / Linux
python -m scripts.backup restore --input ~/flint-backups/flinttrade.tar.gz --target /tmp/flinttrade-restore-check
```

```powershell
# Windows 10/11
python -m scripts.backup restore --input ~/flint-backups/flinttrade.tar.gz --target "$env:TEMP\flinttrade-restore-check"
```

`--force` only overwrites admitted non-authority files in that disjoint tree.
It never permits a live-workspace or credential restore.

## List archives

```bash
python -m scripts.backup list --dir ~/flint-backups/
```

## What this path is not

- It is not a full workspace backup.
- It is not a credential or installation-security backup.
- It is not the former restic authority snapshot.

`make backup` and `make restore` call `infra/backup/backup.sh` and
`infra/backup/restore.sh`. Those scripts are the coordinated/authority path
and currently fail closed with `coordinated_restore_unavailable` (`backup.sh`
always; `restore.sh` before any write). They need make and bash, so they are
POSIX-only; they are not a working substitute for the Python CLI.

The HTTP admin routes under `/v1/admin/backup/*` use the same
`WorkspaceBackup` rules: ordinary bhavcopy archives only, credential opt-in
unavailable, and no restore into the live workspace.
