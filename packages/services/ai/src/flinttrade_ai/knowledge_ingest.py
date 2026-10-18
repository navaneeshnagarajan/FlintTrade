"""Read retained portable input packages without moving or executing any member."""
from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from flinttrade_ai.skill_system import _parse_frontmatter

NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,127}\Z")


def validate_package(name: str, files: Mapping[str, str]) -> None:
    """Require a complete procedure and exact declared member identities."""
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError("invalid skill name")
    main = name + ".md" if name + ".md" in files else "SKILL.md"
    if main not in files:
        raise ValueError("package has no procedure document")
    metadata, _body = _parse_frontmatter(files[main])
    if metadata.get("name", name) != name:
        raise ValueError("package procedure identity mismatch")
    for key in ("references", "scripts"):
        members = metadata.get(key, [])
        if type(members) is not list or any(type(member) is not str or member not in files for member in members):
            raise ValueError("package must include every declared member")


def read_package(root: Path, name: str) -> dict[str, str]:
    """Snapshot exact UTF-8 bytes, including declared references/script hashes.

    A declaration is data, not permission to execute scripts or read outside the
    input directory. Invalid or missing members refuse the entire package.
    """
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError("invalid skill name")
    if root.is_symlink():
        raise ValueError("symlink input directory")

    def read(relative: str) -> str:
        if (not isinstance(relative, str) or not relative or "\\" in relative
                or PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts
                or str(PurePosixPath(relative)) != relative):
            raise ValueError("invalid package member")
        path = root
        for part in PurePosixPath(relative).parts:
            path = path / part
            if path.is_symlink():
                raise ValueError("symlink package member")
        return path.read_bytes().decode("utf-8")

    main = name + ".md"
    text = read(main)
    metadata, _body = _parse_frontmatter(text)
    if metadata.get("name", name) != name:
        raise ValueError("skill identity differs from filename")
    package = {main: text}
    for field in ("references", "scripts"):
        members = metadata.get(field, [])
        if type(members) is not list or any(type(item) is not str for item in members):
            raise ValueError("declared members must be a list of paths")
        for member in members:
            package[member] = read(member)
    validate_package(name, package)
    return package
