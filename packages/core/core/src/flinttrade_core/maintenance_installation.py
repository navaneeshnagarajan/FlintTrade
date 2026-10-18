"""Installer receipt path proofs, separate from protection/stop authority."""
from __future__ import annotations

import os
import re
from pathlib import Path

from .maintenance_custody import MaintenanceRefused
from .secure_file import HeldOwnerDirectory, digest_owner_owned_regular_file


def proven_web_targets(home: Path) -> list[Path]:
    """Prove the official owner-private POSIX web receipt and exact launcher.

    Source shape is checked in addition to, never instead of, the installer
    receipt. The maintenance controller must still authorise safe disposal.
    """
    receipt_dir = home / ".local/state/flinttrade-web"
    if not os.path.lexists(receipt_dir):
        return []
    if receipt_dir.resolve(strict=True) != receipt_dir:
        raise MaintenanceRefused("web receipt path contains an alias")
    with HeldOwnerDirectory(receipt_dir) as held:
        if sorted(os.listdir(held._descriptor)) != ["web-install.receipt"]:
            raise MaintenanceRefused("web receipt directory contains unknown state")
        lines = held.read_text("web-install.receipt").splitlines()
        keys = ("format", "platform", "shim", "shim_sha256", "shortcut", "source", "tools")
        if len(lines) != len(keys) or any(not line.startswith(key + "=") for key, line in zip(keys, lines, strict=True)):
            raise MaintenanceRefused("web install receipt malformed")
        values = dict(line.split("=", 1) for line in lines)
        if values["format"] != "flinttrade-web-install-v1" or values["platform"] != "Linux" or values["shortcut"]:
            raise MaintenanceRefused("web install receipt platform or kind unqualified")
        launcher = Path(values["shim"])
        if launcher not in {home / ".local/bin/flinttrade-web", home / ".local/bin/flinttrade"}:
            raise MaintenanceRefused("receipt does not name a known web launcher")
        if not re.fullmatch("[0-9a-fA-F]{64}", values["shim_sha256"]):
            raise MaintenanceRefused("web launcher digest missing")
        result: list[Path] = []
        if os.path.lexists(launcher):
            if launcher.resolve(strict=True) != launcher:
                raise MaintenanceRefused("web launcher path contains an alias")
            if digest_owner_owned_regular_file(launcher) != values["shim_sha256"].lower():
                raise MaintenanceRefused("web launcher no longer matches its installer receipt")
            result.append(launcher)
        source = Path(values["source"])
        if not source.is_absolute() or source == home or not source.is_relative_to(home):
            raise MaintenanceRefused("web receipt source is not a known owner-local checkout")
        if os.path.lexists(source):
            if source.resolve(strict=True) != source or not source.is_dir():
                raise MaintenanceRefused("web receipt source contains an alias")
            if not all(os.path.lexists(source / marker) for marker in (".git", "pnpm-lock.yaml", "uv.lock", "pyproject.toml")):
                raise MaintenanceRefused("web receipt source checkout identity incomplete")
            result.append(source)
        tools = Path(values["tools"])
        if tools != home / ".flinttrade/tools":
            raise MaintenanceRefused("web receipt tools are not the known managed tools")
        if os.path.lexists(tools):
            result.append(tools)
        result.append(receipt_dir)
        return result
