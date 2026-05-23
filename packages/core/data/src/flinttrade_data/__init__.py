"""Compatibility package for the post-restructure import name."""

from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parent.parent
__path__ = [str(_SRC_ROOT)]

_legacy_init = _SRC_ROOT / "__init__.py"
if _legacy_init.exists():
    exec(compile(_legacy_init.read_text(encoding="utf-8"), str(_legacy_init), "exec"), globals())
