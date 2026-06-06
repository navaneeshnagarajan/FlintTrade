"""Attribution completeness — every absorbed-from upstream must appear in `notice`.

Converts the one-off attribution audit into CI enforcement. The canonical list of
upstreams FlintTrade studied / adapted lives in
``scripts/check_absorption_drift.py`` (ABSORBED_REPOS); each must be credited in
the root ``notice`` file (the OSS-licence attribution surface the readme points
at). Also guards that the bundled Apache-2.0 licence text is the full verbatim
licence, not a URL stub (required for the bundled Lightweight Charts dependency).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent


def _absorbed_repo_names() -> list[str]:
    # Parse (not import) the script — no execution side effects. The only
    # `"name":` keys in the file are the ABSORBED_REPOS entries.
    text = (ROOT / "scripts" / "check_absorption_drift.py").read_text(encoding="utf-8")
    return re.findall(r'"name":\s*"([^"]+)"', text)


def test_every_absorbed_repo_is_attributed_in_notice() -> None:
    names = _absorbed_repo_names()
    assert names, "ABSORBED_REPOS parse found no names — did the script move?"

    notice = (ROOT / "notice").read_text(encoding="utf-8").lower()
    missing = [n for n in names if n.lower() not in notice]
    assert not missing, (
        f"upstreams in ABSORBED_REPOS but missing from `notice`: {missing}. "
        "Add an attribution row (name + github) to the notice."
    )


def test_apache_licence_bundle_is_verbatim_not_a_stub() -> None:
    # Lightweight Charts (Apache-2.0) is declared BUNDLED in `notice`, so §4.1
    # requires the full verbatim licence text, not a URL pointer.
    text = (ROOT / "licenses" / "apache-2.0.txt").read_text(encoding="utf-8")
    assert "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" in text
    assert "Grant of Patent License" in text
