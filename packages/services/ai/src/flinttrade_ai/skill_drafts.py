"""Retained candidate inputs, not an operator-approval activation bypass.

No model call happens here. Changed reflections get new filenames; existing
bytes remain intact. The shared KnowledgeRuntime snapshots candidates, and
only trusted independent evaluation plus current rights can publish them.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.ai.skill_drafts")

DRAFTS_DIRNAME = "skill_drafts"
SKILLS_DIRNAME = "skills"

# Slug-only names: file operations on these can never traverse paths.
# Matched with ``fullmatch`` rather than a ``$``-anchored ``match`` — ``$`` also
# matches just before a trailing newline, so ``match`` admitted "some-name\n".
SLUG_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,80}")


def drafts_dir(workspace: Path) -> Path:
    return workspace / DRAFTS_DIRNAME


def skills_dir(workspace: Path) -> Path:
    return workspace / SKILLS_DIRNAME


def is_valid_slug(name: str) -> bool:
    """True for a safe, slug-only skill name."""
    return bool(SLUG_PATTERN.fullmatch(name or ""))


def _existing_draft(workspace: Path, name: str) -> Path | None:
    """Return the draft file called ``name``, or ``None`` when there is none.

    The path is picked out of a listing of the drafts directory rather than
    built by joining the caller's string onto it, so a draft is addressable
    only when it is already one of the files in that directory. Containment is
    therefore a property of how the path is obtained, not an assertion about a
    string. :func:`is_valid_slug` still rejects non-slug names up front.

    Args:
        workspace: The workspace directory (``workspace_dir()``).
        name: Requested draft name (must be a slug).

    Returns:
        The draft's path, or ``None`` when the name is invalid or unknown.
    """
    if not is_valid_slug(name):
        return None
    directory = drafts_dir(workspace)
    if directory.is_symlink() or not directory.is_dir():
        return None
    filename = f"{name}.md"
    match = next((path for path in directory.glob("*.md") if path.name == filename), None)
    # glob() yields directories too, and a directory called "<slug>.md" would
    # otherwise be returned as a draft: read_text() then raises IsADirectoryError
    # on POSIX and PermissionError on Windows, and the routes catch neither, so a
    # documented 404 becomes an unhandled 500.
    return match if match is not None and not match.is_symlink() and match.is_file() else None


def _render_list(title: str, items: list[str]) -> str:
    lines = [f"## {title}", ""]
    lines += [f"- {str(item).strip()}" for item in items if str(item).strip()]
    lines.append("")
    return "\n".join(lines)


def draft_skill_from_reflection(
    workspace: Path,
    result: Any,
    *,
    session_date: str,
    symbols: list[str],
) -> Path | None:
    """Render a session's reflection into a draft skill file.

    Args:
        workspace: The workspace directory (``workspace_dir()``).
        result: A :class:`~flinttrade_ai.trade_reflection.ReflectionResult`.
        session_date: ISO date of the session (drives the deterministic name).
        symbols: Symbols traded this session (provenance frontmatter).

    Returns:
        The draft path, or ``None`` when the reflection carries no usable
        content (no patterns and no recommendations — an empty skill would
        be noise, not knowledge).
    """
    recommendations = [str(r) for r in getattr(result, "recommendations", []) or []]
    winning = [str(p) for p in getattr(result, "winning_patterns", []) or []]
    losing = [str(p) for p in getattr(result, "losing_patterns", []) or []]
    insights = str(getattr(result, "market_insights", "") or "").strip()
    if not (recommendations or winning or losing):
        return None

    name = f"session-lessons-{session_date}"
    if not is_valid_slug(name):
        logger.warning("Skill draft name %r is not a valid slug — skipping", name)
        return None

    win_rate = float(getattr(result, "win_rate", 0.0) or 0.0)
    trades_analysed = int(getattr(result, "trades_analysed", 0) or 0)
    description = (
        f"Session lessons from {session_date} "
        f"({trades_analysed} trades, {win_rate:.0%} win rate)"
    )

    body_parts = [
        "---",
        f"name: {name}",
        f"description: {description}",
        "status: draft",
        f"session_date: {session_date}",
        f"symbols: {', '.join(symbols)}",
        f"trades_analysed: {trades_analysed}",
        f"win_rate: {win_rate:.4f}",
        "source: autonomous-agent-reflection",
        "---",
        "",
        f"# Session lessons — {session_date}",
        "",
        "Drafted automatically from the post-session reflection. This file",
        "influences nothing until independently validated with current rights.",
        "",
    ]
    if recommendations:
        body_parts.append(_render_list("Recommendations", recommendations))
    if winning:
        body_parts.append(_render_list("Winning patterns", winning))
    if losing:
        body_parts.append(_render_list("Losing patterns", losing))
    if insights:
        body_parts += ["## Market insights", "", insights, ""]

    target_dir = drafts_dir(workspace)
    if target_dir.is_symlink():
        raise ValueError("draft directory must not be a symlink")
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{name}.md"
    if path.is_symlink():
        raise ValueError("draft must not be a symlink")
    content = "\n".join(body_parts)
    if path.exists() and path.read_bytes() != content.encode():
        revision = name + "-" + hashlib.sha256(content.encode()).hexdigest()[:16]
        content = content.replace(f"name: {name}\n", f"name: {revision}\n", 1)
        path = target_dir / f"{revision}.md"
    if path.is_symlink():
        raise ValueError("draft must not be a symlink")
    try:
        with path.open("xb") as stream:
            stream.write(content.encode())
    except FileExistsError:
        if path.read_bytes() != content.encode():
            raise ValueError("draft identity conflict; existing bytes preserved") from None
    logger.info("Skill draft written: %s", path.name)
    return path


def list_drafts(workspace: Path) -> list[dict[str, Any]]:
    """Draft summaries (name, description, modified time), newest first."""
    directory = drafts_dir(workspace)
    if directory.is_symlink() or not directory.is_dir():
        return []
    from .skill_system import _load_skill_file  # noqa: PLC0415 - same-package helper

    rows: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.md")):
        if not is_valid_slug(path.stem) or path.is_symlink() or not path.is_file():
            continue
        config = _load_skill_file(path)
        rows.append(
            {
                "name": path.stem,
                "description": (config.description if config else "") or "",
                "modified_at": path.stat().st_mtime,
            }
        )
    rows.sort(key=lambda r: r["modified_at"], reverse=True)
    return rows


def read_draft(workspace: Path, name: str) -> str | None:
    """Full markdown of one draft, or None."""
    path = _existing_draft(workspace, name)
    if path is None:
        return None
    return path.read_bytes().decode("utf-8")


def approve_draft(workspace: Path, name: str, *, runtime: Any = None) -> str:
    """Compatibility alias for immutable intake, never approval or a file move."""
    if not is_valid_slug(name):
        raise ValueError("invalid skill name")
    source = _existing_draft(workspace, name)
    if source is None:
        raise FileNotFoundError(name)
    if runtime is None or runtime.workspace != workspace:
        raise RuntimeError("shared KnowledgeRuntime required; use ingest_skill; draft preserved")
    return runtime.ingest_skill(name)


def reject_draft(workspace: Path, name: str, *, runtime: Any = None) -> bool:
    """Retire a retained input without deleting its file or ledger lineage."""
    path = _existing_draft(workspace, name)
    if path is None:
        return False
    candidate = approve_draft(workspace, name, runtime=runtime)
    runtime.store.retire(candidate, reason="legacy draft rejection")
    return True
