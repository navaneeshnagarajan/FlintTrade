"""Password reset must not strand enrolled MFA or keep old session authority."""
from __future__ import annotations

import secrets

import pyotp
import pytest

from flinttrade_core.auth_service import AuthService

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("cold", [False, True])
@pytest.mark.parametrize("regenerated", [False, True])
def test_password_reset_preserves_authenticator_or_refuses_before_mutation(tmp_path, cold, regenerated):
    path = tmp_path / "auth.sqlite"
    svc = AuthService(db_path=path)
    old = secrets.token_urlsafe(24)
    new = secrets.token_urlsafe(24)
    svc.setup_account("operator", "operator@example.test", old, "")
    secret = svc.get_totp_secret()
    assert secret is not None
    assert svc.enable_totp(pyotp.TOTP(secret).now())
    binding = svc.current_session_binding()
    svc.close()
    svc = AuthService(db_path=path)
    if not cold:
        assert svc.verify_password(old)
    if regenerated:
        assert svc.regenerate_totp(old) is not None
        secret = svc.get_totp_secret()
        assert svc.enable_totp(pyotp.TOTP(secret).now())
        if cold:
            svc.close()
            svc = AuthService(db_path=path)
    try:
        if cold:
            with pytest.raises(RuntimeError, match="recovery"):
                svc.update_password("operator", new)
            assert svc.current_session_binding() == binding
        else:
            assert svc.update_password("operator", new)
            assert svc.current_session_binding() != binding
    finally:
        svc.close()
    fresh = AuthService(db_path=path)
    try:
        assert fresh.verify_password(old if cold else new)
        assert fresh.verify_totp(pyotp.TOTP(secret).now())
        assert fresh.is_totp_enabled()
    finally:
        fresh.close()
