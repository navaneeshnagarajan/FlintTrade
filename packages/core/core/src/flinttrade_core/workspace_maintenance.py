"""Maintenance exclusion shared with every normal backend/guardian startup.

Exclusion is not permission to stop protection, erase records or re-arm a run.
Callers retain this context through staging, publication AND archive/deletion.
They must refuse destructive work without independently verified policy.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from flinttrade_core.backend_instance import BackendInstanceAlreadyRunning, _acquire_workspace_exclusion


class WorkspaceMaintenanceUnavailable(RuntimeError):
    """Ownership cannot be established; keep every data target unchanged."""


@contextmanager
def acquire_workspace_maintenance(workspace: Path) -> Iterator[None]:
    """Exclude normal backend owners for the entire maintenance transaction.

    This non-waiting lease uses the backend's kernel ownership, including its
    legacy inode. It does not signal a process, infer safety from a PID/port,
    issue a backend proof or grant destructive-operation permission. The stable
    sibling lock inode must never be removed, including by purge callers.

    Raises:
        WorkspaceMaintenanceUnavailable: Live, ambiguous or inaccessible owner.
    """
    try:
        lease = _acquire_workspace_exclusion(workspace)
    except (BackendInstanceAlreadyRunning, OSError, ValueError) as exc:
        raise WorkspaceMaintenanceUnavailable(
            "Workspace maintenance unavailable: ownership is busy or uncertain; data retained."
        ) from exc
    try:
        yield
    finally:
        lease.release()


def main() -> int:
    """Fail closed at public maintenance callers until safe policy is mounted.

    A free kernel lock proves exclusion, not absence of exposure or surviving
    protection obligations. Do not turn that observation into destructive
    permission. There is deliberately no --force or ambient-policy bypass.
    """
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("stop", "purge", "provision"))
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--yes", action="store_true", help="Explicitly confirm the complete printed purge scope")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    if not 0 < args.timeout <= 300:
        parser.error("--timeout must be greater than zero and at most 300 seconds")
    if args.operation == "provision":
        import runpy
        import sys

        from flinttrade_core.workspace import workspace_dir

        # Run the existing public initialiser inside the same process/lease;
        # no child can outlive us and keep writing after exclusion is released.
        workspace = workspace_dir(ensure_exists=False)
        try:
            lease = _acquire_workspace_exclusion(workspace, initialise=True)
            try:
                from .maintenance_history import initialise_fresh_history

                initialise_fresh_history(workspace, lease)
                sys.argv = ["flinttrade_core.cli", "init", "--provision-master-password"]
                if args.verbose:
                    sys.argv.append("--verbose")
                runpy.run_module("flinttrade_core.cli", run_name="__main__")
            finally:
                lease.release()
        except (BackendInstanceAlreadyRunning, OSError, ValueError):
            print("Workspace provisioning refused: maintenance ownership busy or uncertain.", file=sys.stderr)
            return 1
        return 0
    if args.workspace is None:
        parser.error("--workspace is required")
    from .maintenance_control import stop_workspace, stopped_workspace
    from .maintenance_custody import MaintenanceRefused

    try:
        if args.operation == "stop":
            stop_workspace(args.workspace, timeout=args.timeout)
        else:
            from .installation_state import InstallationState, stable_application_state_root
            from .maintenance_purge import PurgePlan

            if not args.yes:
                raise MaintenanceRefused("explicit --purge and --yes confirmation required")
            root = stable_application_state_root()
            if not (root / "installation_id").exists() or not (root / ".installation-id-binding").exists():
                raise MaintenanceRefused("installation custody and safe policy unavailable")
            preview = PurgePlan(args.workspace, InstallationState(root))
            print("Explicitly confirmed COMPLETE purge scope (credentials, journals and account history included):")
            for target in preview.targets:
                print(f"  {target}")
            identities = {path: (path.lstat().st_dev, path.lstat().st_ino) for path in preview.roots}
            with stopped_workspace(args.workspace, operation="purge", timeout=args.timeout) as installation:
                plan = PurgePlan(args.workspace, installation)
                if plan.targets != preview.targets or any(
                    (path.lstat().st_dev, path.lstat().st_ino) != value for path, value in identities.items()
                ):
                    raise MaintenanceRefused("confirmed complete target set changed during managed stop")
                plan.execute()
                if plan.receipt().get("phase") != "complete":
                    raise MaintenanceRefused("purge completion could not be read back")
            print("Purge complete: every explicitly confirmed target is absent; stable exclusion and receipt retained.")
    except (MaintenanceRefused, OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, MaintenanceRefused) else "exact owner/path custody unavailable"
        print(f"{args.operation.capitalize()} refused: {reason}; unremoved data and pending cleanup retained.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
