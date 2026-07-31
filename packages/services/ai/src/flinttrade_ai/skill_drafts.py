"""Skill drafts — the operator-approved skill write path (reference-map AI1).

After a trading session, the learning loop's :class:`ReflectionResult` is
rendered into a DRAFT skill markdown file under
``<workspace_dir>/skill_drafts/``. Drafts influence nothing: only after an
explicit operator approval (which moves the file into
``<workspace_dir>/skills/`` and flips its frontmatter status) does a skill
become loadable by the app's :class:`~flinttrade_ai.skill_system.SkillRegistry`
and therefore visible to any prompt.

No LLM call happens here — the draft renders material the reflection step
already produced. Rendering is deterministic per session date, so re-running
a session's reflection overwrites its own draft rather than accumulating
near-duplicates.
"""

from __future__ import annotations

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
    if not directory.is_dir():
        return None
    filename = f"{name}.md"
    match = next((path for path in directory.glob("*.md") if path.name == filename), None)
    # glob() yields directories too, and a directory called "<slug>.md" would
    # otherwise be returned as a draft: read_text() then raises IsADirectoryError
    # on POSIX and PermissionError on Windows, and the routes catch neither, so a
    # documented 404 becomes an unhandled 500.
    return match if match is not None and match.is_file() else None


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
        "influences nothing until an operator approves it.",
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
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{name}.md"
    path.write_text("\n".join(body_parts), encoding="utf-8")
    logger.info("Skill draft written: %s", path.name)
    return path


def list_drafts(workspace: Path) -> list[dict[str, Any]]:
    """Draft summaries (name, description, modified time), newest first."""
    directory = drafts_dir(workspace)
    if not directory.is_dir():
        return []
    from .skill_system import _load_skill_file  # noqa: PLC0415 - same-package helper

    rows: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.md")):
        if not is_valid_slug(path.stem):
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
    return path.read_text(encoding="utf-8")


def approve_draft(workspace: Path, name: str) -> Path:
    """Move a draft into the operator skills directory as approved.

    The frontmatter ``status: draft`` line becomes ``status: approved`` so
    provenance survives. Raises ``FileNotFoundError``/``ValueError`` on a
    missing draft or invalid name.
    """
    if not is_valid_slug(name):
        raise ValueError("invalid skill name")
    source = _existing_draft(workspace, name)
    if source is None:
        raise FileNotFoundError(name)
    content = source.read_text(encoding="utf-8")
    content = content.replace("status: draft", "status: approved", 1)
    target_dir = skills_dir(workspace)
    target_dir.mkdir(parents=True, exist_ok=True)
    # Named after the draft file itself, so the approved copy can only ever
    # land beside the other skills under the name the drafts directory listed.
    target = target_dir / source.name
    target.write_text(content, encoding="utf-8")
    source.unlink()
    logger.info("Skill draft approved: %s", name)
    return target


def reject_draft(workspace: Path, name: str) -> bool:
    """Delete a draft. Returns True when it existed."""
    path = _existing_draft(workspace, name)
    if path is None:
        return False
    path.unlink()
    logger.info("Skill draft rejected: %s", name)
    return True
