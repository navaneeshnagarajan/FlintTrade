"""The account authority can consume verified identity without HTTP imports."""

from __future__ import annotations

import subprocess
import sys


def test_operator_evidence_import_does_not_construct_http_or_broker_runtime():
    """Catch an account contract importing Flask/auth or broker runtime owners."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from flinttrade_core.operator_session import VerifiedOperatorSession\n"
            "import sys\n"
            "assert not any(name == 'flask' or name.startswith(('flask.', 'flinttrade_gateway.')) "
            "for name in sys.modules)\n"
            "assert 'flinttrade_core.auth_routes' not in sys.modules\n",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_full_session_verifier_returns_the_neutral_evidence_contract(monkeypatch):
    """Catch a parallel DTO that the coordinator's exact type checks reject."""
    import importlib.util

    assert importlib.util.find_spec("flinttrade_core.operator_session") is not None
    from flinttrade_core import auth_routes
    from flinttrade_core.operator_session import VerifiedOperatorSession

    monkeypatch.setattr(auth_routes, "_get_jwt_secret", lambda: "synthetic-session-key")
    monkeypatch.setattr(
        auth_routes,
        "_decode_token_with_signing_key",
        lambda token, signing_key: {
            "type": "session", "sub": "synthetic-operator", "jti": "synthetic-jti",
            "scopes": ["admin.accounts.write"],
        },
    )
    evidence = auth_routes.verify_operator_session_token("synthetic-token")
    assert type(evidence) is VerifiedOperatorSession
    assert auth_routes.VerifiedOperatorSession is VerifiedOperatorSession
    assert evidence.scopes == ("admin.accounts.write",)
    assert not hasattr(evidence, "token")
    assert not hasattr(evidence, "jti")
