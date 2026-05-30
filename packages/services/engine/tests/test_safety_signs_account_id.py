"""T12 (gap G7) CI validator: account_id stays in the SafetyContext signed tuple.

A source-level grep gate (§8.1 style) that locks the T4-C invariant — the
resolved ``account_id`` is part of the HMAC canonical tuple AND is compared at
verify time — so a refactor cannot silently drop the account binding and reopen
the account-swap replay vector.
"""

from __future__ import annotations

from pathlib import Path

_SAFETY = Path(__file__).resolve().parents[1] / "src" / "flinttrade_engine" / "safety.py"


def test_account_id_signed_and_verified() -> None:
    text = _SAFETY.read_text(encoding="utf-8")
    # account_id is a field on the frozen SafetyContext dataclass.
    assert "account_id: str" in text
    # verify() compares the live account_id against the signed one.
    assert "if account_id != self.account_id:" in text
    # the canonical HMAC tuple carries account_id alongside adapter_id.
    canonical_start = text.index("def _hmac_canonical(")
    canonical_body = text[canonical_start : canonical_start + 1600]
    assert "account_id," in canonical_body
