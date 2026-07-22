"""Backend → Electron-shell native notification bridge.

The Electron source guardian drains the backend's stdout and raises a native OS
notification for each ``FLINTTRADE_NOTIFY\\t<title>\\t<body>`` line. This is the
*producer* side: best-effort, dependency-free, and a no-op unless the backend is
actually running under the desktop shell (``FLINTTRADE_DESKTOP=1``, set by the
guardian spawn) — so ``make start`` / CLI runs never print stray sentinel lines.

Notifications fire even while the window is hidden in the tray, which is the
point for an AI-trading app: the operator must learn of fills, safety-gate
blocks, and agent turns without watching the screen.
"""

from __future__ import annotations

import os
import sys

#: Stdout prefix the desktop shell parses. Must match ``NOTIFICATION_PREFIX`` in
#: ``electron/guardian-protocol.ts``. Tab-delimited: PREFIX \t title \t body.
NOTIFY_SENTINEL = "FLINTTRADE_NOTIFY"


def desktop_shell_active() -> bool:
    """Whether the backend is running under the Electron desktop shell."""
    return os.environ.get("FLINTTRADE_DESKTOP", "").strip() not in ("", "0", "false")


def notify(title: str, body: str = "") -> None:
    """Raise a native desktop notification, best-effort.

    A no-op unless running under the desktop shell. Never raises: a
    notification failure must not perturb the order/safety path that calls it.
    Tabs and newlines in the payload are flattened to spaces so the single-line
    sentinel protocol stays intact.

    Args:
        title: Short notification title (required, non-empty).
        body: Optional notification body.
    """
    if not desktop_shell_active():
        return
    clean_title = _one_line(title)
    if not clean_title:
        return
    try:
        sys.stdout.write(f"{NOTIFY_SENTINEL}\t{clean_title}\t{_one_line(body)}\n")
        sys.stdout.flush()
    except Exception:  # noqa: BLE001 - notifications are never allowed to break a caller
        pass


def _one_line(text: str) -> str:
    """Collapse tabs/newlines to spaces so the sentinel line stays single-line."""
    return " ".join(str(text or "").split())
