"""FlintTrade workspace CLI.

Usage:
    python -m flinttrade_core.cli init      # Initialise ~/.flinttrade/
    python -m flinttrade_core.cli status    # Show workspace info
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import os
import re
import secrets
import sys
import traceback
from collections.abc import Iterator

from filelock import Timeout

from .owner_file_lock import OwnerSafeFileLock
from .secure_file import (
    InsecureFilePermissionsError,
    read_hardened_owner_owned_text,
    read_owner_owned_text,
    write_secret_text,
)
from .workspace import Workspace

_MASTER_PASSWORD_MAX_BYTES = 4 * 1024

# The advisory lock file that serialises provisioning, and how long a second
# process waits for it. Neither holds - nor is derived from - the master
# password; they are named for what they are so that a reader (and a scanner)
# is not told otherwise by the identifier.
_VAULT_PROVISION_LOCK_NAME = ".vault-provision.lock"
_VAULT_PROVISION_LOCK_TIMEOUT_SECONDS = 30

_PROVISION_STAGE_NOTE_PREFIX = "flinttrade-provision-stage:"
_VERBOSE_ERRORS_ENV = "FLINTTRADE_VERBOSE_ERRORS"
_SECRET_LIKE_PATTERN = re.compile(r"[0-9a-fA-F]{32,}")
_CAUSE_CHAIN_DEPTH = 3

EXIT_PROVISION_DEGRADED = 3
"""Provisioning failed, but a usable credential-vault secret is already in place.

Callers may carry on: the backend needs the secret to exist and be readable, and
that has been re-proven under the full hardening policy. It is a distinct code
from ``1`` so a launcher can warn rather than refuse to start.
"""


def _existing_secret_is_usable(ws: Workspace) -> bool:
    """Report whether the vault secret survives the full at-rest policy.

    Called only after provisioning has already failed, to decide between a hard
    failure and a degraded start. The check is deliberately the *strict* one -
    owner-owned, hardened, single-link, non-reparse, bounded - so a symlinked,
    foreign-owned or loosely permissioned file is never mistaken for a usable
    vault. It needs no lock because it neither writes nor repairs.

    Args:
        ws: The workspace being provisioned.

    Returns:
        ``True`` when the existing secret is present, hardened and non-empty.
    """
    try:
        secret = read_hardened_owner_owned_text(
            ws.workspace_dir / "master_password",
            max_bytes=_MASTER_PASSWORD_MAX_BYTES,
        )
    except Exception:
        return False
    return bool(secret.strip())


@contextlib.contextmanager
def _provision_stage(label: str) -> Iterator[None]:
    """Tag any exception escaping the block with the provisioning stage.

    The label rides on :meth:`BaseException.add_note`, so the exception's type
    and ``str()`` stay byte-identical. Callers that match on the message - and
    the tests that pin those messages - keep working unchanged.

    Args:
        label: The short stage name reported to the operator.

    Yields:
        None.
    """
    try:
        yield
    except BaseException as exc:
        exc.add_note(f"{_PROVISION_STAGE_NOTE_PREFIX}{label}")
        raise


def _provision_stage_of(exc: BaseException) -> str | None:
    """Return the innermost stage label recorded on *exc*, when there is one.

    Notes are appended as the exception unwinds, so the first match is the
    innermost - and most specific - stage.

    Args:
        exc: The exception that escaped provisioning.

    Returns:
        The stage label, or ``None`` when the exception carries no stage.
    """
    for note in getattr(exc, "__notes__", ()):
        if note.startswith(_PROVISION_STAGE_NOTE_PREFIX):
            return note[len(_PROVISION_STAGE_NOTE_PREFIX) :]
    return None


def _redact(text: str, ws: Workspace) -> str:
    """Strip workspace paths and secret-shaped runs out of a diagnostic string.

    Follows the precedent set by :func:`flinttrade_core.secure_file.harden`,
    which already rewrites the parent directory and the full path out of the
    messages it raises.

    Args:
        text: The raw message.
        ws: The workspace whose paths should be rewritten.

    Returns:
        The message with paths shortened and secret-shaped runs masked.
    """
    password_file = str(ws.workspace_dir / "master_password")
    redacted = text.replace(password_file, "master_password")
    redacted = redacted.replace(str(ws.workspace_dir), "<workspace>")
    return _SECRET_LIKE_PATTERN.sub("<redacted>", redacted)


def _describe_cause(exc: BaseException, ws: Workspace) -> list[str]:
    """Render the exception chain as redacted, operator-readable stderr lines.

    ``str(exc)`` is used rather than ``repr(exc)`` on purpose: the ``repr`` of a
    :class:`UnicodeDecodeError` embeds the offending bytes, which for this
    command are the master password itself.

    Args:
        exc: The exception that escaped provisioning.
        ws: The workspace used to redact paths.

    Returns:
        The formatted lines, outermost cause first.
    """
    lines: list[str] = []
    current: BaseException | None = exc
    depth = 0
    while current is not None and depth < _CAUSE_CHAIN_DEPTH:
        detail = _redact(str(current), ws) or "(no message)"
        suffix = ""
        errno_value = getattr(current, "errno", None)
        if isinstance(errno_value, int):
            suffix += f" [errno {errno_value} {errno.errorcode.get(errno_value, 'UNKNOWN')}]"
        winerror = getattr(current, "winerror", None)
        if isinstance(winerror, int) and winerror:
            suffix += f" [WinError {winerror}]"
        label = "  Cause:" if depth == 0 else "    from:"
        lines.append(f"{label} {type(current).__name__}: {detail}{suffix}")
        current = current.__cause__ or current.__context__
        depth += 1
    return lines


def _report_provision_failure(ws: Workspace, exc: BaseException, *, verbose: bool) -> None:
    """Print a diagnosable, leak-free account of a provisioning failure.

    At least nine distinct fault classes reach this point - lock contention, an
    unsafe lock path, insecure permissions, a foreign owner, a mid-read change,
    and this module's own postcondition checks among them. Naming which one
    fired is the difference between a fixable report and a dead end.

    Args:
        ws: The workspace that was being provisioned.
        exc: The exception that escaped provisioning.
        verbose: Whether to append the full traceback.
    """
    print("Master password provisioning failed.", file=sys.stderr)
    print(f"  Workspace: {ws.workspace_dir}", file=sys.stderr)
    stage = _provision_stage_of(exc)
    if stage is not None:
        print(f"  Stage: {stage}", file=sys.stderr)
    if isinstance(exc, Timeout):
        print(
            "  Cause: Timeout: another FlintTrade process holds "
            f"{_VAULT_PROVISION_LOCK_NAME}; waited "
            f"{_VAULT_PROVISION_LOCK_TIMEOUT_SECONDS} s. Stop the other "
            "FlintTrade process and retry.",
            file=sys.stderr,
        )
    else:
        for line in _describe_cause(exc, ws):
            print(line, file=sys.stderr)
    if verbose:
        # Rendered and redacted rather than printed directly, so that EVERY byte
        # this command writes leaves through one redactor.
        #
        # Defence in depth, stated honestly: no leak was demonstrated here.
        # traceback.print_exception renders str(exc), not repr(exc), and the
        # UnicodeDecodeError this path can raise names a byte offset without the
        # content. But it was the only branch bypassing _redact, and "the summary
        # is redacted, the traceback is not" is a distinction no future caller
        # should have to know about.
        print(_redact("".join(traceback.format_exception(exc)), ws), file=sys.stderr, end="")
    else:
        print(
            f"  Re-run with --verbose (or {_VERBOSE_ERRORS_ENV}=1) for the full traceback.",
            file=sys.stderr,
        )


def _provision_master_password(ws: Workspace) -> bool:
    """Ensure the credential-vault master password exists for source/dev runs.

    The backend deliberately refuses to auto-generate this secret. Installers,
    the Electron shell, and this explicit CLI command are allowed provisioning
    points because they write the supported hardened at-rest file before the
    backend starts.

    This secret is the machine-generated key-encryption key for the broker
    credential vault. It is not the operator account password collected by the
    in-app setup route, and it is never shown to or chosen by the operator.
    """
    password_file = ws.workspace_dir / "master_password"
    provision_lock = OwnerSafeFileLock(
        ws.workspace_dir / _VAULT_PROVISION_LOCK_NAME,
        timeout=_VAULT_PROVISION_LOCK_TIMEOUT_SECONDS,
        mode=0o600,
    )
    with _provision_stage("acquire-provision-lock"):
        provision_lock.acquire()
    try:
        with _provision_stage("read-existing-secret"):
            try:
                existing_secret = read_owner_owned_text(
                    password_file,
                    max_bytes=_MASTER_PASSWORD_MAX_BYTES,
                )
            except FileNotFoundError:
                existing_secret = None

        if existing_secret is not None and existing_secret.strip():
            with _provision_stage("verify-existing-secret"):
                try:
                    verified_secret = read_hardened_owner_owned_text(
                        password_file,
                        max_bytes=_MASTER_PASSWORD_MAX_BYTES,
                    )
                except InsecureFilePermissionsError:
                    with _provision_stage("harden-existing-secret"):
                        write_secret_text(password_file, existing_secret)
                        verified_secret = read_hardened_owner_owned_text(
                            password_file,
                            max_bytes=_MASTER_PASSWORD_MAX_BYTES,
                        )
                if not secrets.compare_digest(existing_secret, verified_secret):
                    raise OSError("master password changed during provisioning")
            return False

        with _provision_stage("write-new-secret"):
            generated_secret = secrets.token_hex(32)
            write_secret_text(password_file, generated_secret)
        with _provision_stage("verify-new-secret"):
            verified_secret = read_hardened_owner_owned_text(
                password_file,
                max_bytes=_MASTER_PASSWORD_MAX_BYTES,
            )
            if not secrets.compare_digest(generated_secret, verified_secret):
                raise OSError("master password postcondition failed")
        return True
    finally:
        provision_lock.release()


def cmd_init(args: argparse.Namespace) -> None:
    """Initialise the workspace with default config."""
    ws = Workspace()
    created_workspace = not ws.is_initialized
    if created_workspace:
        ws.initialise()
        print(f"Workspace initialised: {ws.workspace_dir}")
        print(f"  Config:  {ws.config_path}")
        print(f"  Data:    {ws.fast_data_dir}")
        print(f"  Archive: {ws.archive_dir}")
        print(f"  Logs:    {ws.log_dir}")
    else:
        print(f"Workspace already initialised: {ws.workspace_dir}")

    if args.provision_master_password:
        verbose = bool(getattr(args, "verbose", False)) or os.environ.get(_VERBOSE_ERRORS_ENV) == "1"
        try:
            created_secret = _provision_master_password(ws)
        except Exception as exc:
            _report_provision_failure(ws, exc, verbose=verbose)
            if _existing_secret_is_usable(ws):
                print(
                    "  The existing master password is present and hardened, so the "
                    "credential vault remains usable.",
                    file=sys.stderr,
                )
                raise SystemExit(EXIT_PROVISION_DEGRADED) from None
            raise SystemExit(1) from None
        action = "generated" if created_secret else "already present"
        print(f"  Master password: {action} at {ws.workspace_dir / 'master_password'}")


def cmd_status(args: argparse.Namespace) -> None:
    """Show current workspace info."""
    ws = Workspace()
    print(f"Workspace: {ws.workspace_dir}")
    print(f"Initialised: {ws.is_initialized}")
    if ws.is_initialized:
        print(f"Config:  {ws.config_path}")
        print(f"Data:    {ws.fast_data_dir}")
        print(f"Archive: {ws.archive_dir}")
        print(f"Logs:    {ws.log_dir}")
        modules = ws.get("modules", {})
        enabled = [k for k, v in modules.items() if v]
        disabled = [k for k, v in modules.items() if not v]
        print(f"Enabled:  {', '.join(enabled) if enabled else 'none'}")
        print(f"Disabled: {', '.join(disabled) if disabled else 'none'}")
        print(f"Version: {ws.get('version', 'unknown')}")
    else:
        print("Run: python -m flinttrade_core.cli init")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="flinttrade",
        description="FlintTrade workspace management",
    )
    sub = parser.add_subparsers(dest="command")

    init_parser = sub.add_parser("init", help="Initialise workspace with defaults")
    init_parser.add_argument(
        "--provision-master-password",
        action="store_true",
        help="Create the hardened master_password file when it is missing or empty.",
    )
    init_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print the full traceback when provisioning fails.",
    )
    sub.add_parser("status", help="Show workspace info")

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "status": cmd_status,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
