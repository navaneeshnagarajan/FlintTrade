"""TDD tests for gateway Pydantic models."""

from __future__ import annotations

from datetime import datetime, timezone


from flinttrade_gateway.models import AuthFlowType, AccountStatus, BrokerInfo, BrokerAccountInfo


# ---------------------------------------------------------------------------
# AuthFlowType StrEnum
# ---------------------------------------------------------------------------


class TestAuthFlowType:
    def test_oauth_redirect_value(self) -> None:
        assert AuthFlowType.oauth_redirect == "oauth_redirect"

    def test_totp_form_value(self) -> None:
        assert AuthFlowType.totp_form == "totp_form"

    def test_api_key_direct_value(self) -> None:
        assert AuthFlowType.api_key_direct == "api_key_direct"

    def test_otp_sms_value(self) -> None:
        assert AuthFlowType.otp_sms == "otp_sms"

    def test_otp_multistep_value(self) -> None:
        assert AuthFlowType.otp_multistep == "otp_multistep"

    def test_all_members_present(self) -> None:
        members = {m.value for m in AuthFlowType}
        assert members == {
            "oauth_redirect",
            "totp_form",
            "api_key_direct",
            "otp_sms",
            "otp_multistep",
        }

    def test_is_str(self) -> None:
        assert isinstance(AuthFlowType.oauth_redirect, str)


# ---------------------------------------------------------------------------
# AccountStatus StrEnum
# ---------------------------------------------------------------------------


class TestAccountStatus:
    def test_disconnected_value(self) -> None:
        assert AccountStatus.disconnected == "disconnected"

    def test_authenticating_value(self) -> None:
        assert AccountStatus.authenticating == "authenticating"

    def test_connected_value(self) -> None:
        assert AccountStatus.connected == "connected"

    def test_error_value(self) -> None:
        assert AccountStatus.error == "error"

    def test_token_expired_value(self) -> None:
        assert AccountStatus.token_expired == "token_expired"

    def test_all_members_present(self) -> None:
        members = {m.value for m in AccountStatus}
        assert members == {
            "disconnected",
            "authenticating",
            "connected",
            "error",
            "token_expired",
        }

    def test_is_str(self) -> None:
        assert isinstance(AccountStatus.connected, str)


# ---------------------------------------------------------------------------
# BrokerInfo
# ---------------------------------------------------------------------------


class TestBrokerInfo:
    def test_creation_with_required_fields(self) -> None:
        info = BrokerInfo(
            name="zerodha",
            display_name="Zerodha",
            auth_flow=AuthFlowType.totp_form,
            exchanges=["NSE", "BSE", "NFO"],
        )
        assert info.name == "zerodha"
        assert info.display_name == "Zerodha"
        assert info.auth_flow == AuthFlowType.totp_form
        assert info.exchanges == ["NSE", "BSE", "NFO"]

    def test_default_max_symbols_per_ws(self) -> None:
        info = BrokerInfo(
            name="zerodha",
            display_name="Zerodha",
            auth_flow=AuthFlowType.totp_form,
            exchanges=["NSE"],
        )
        assert info.max_symbols_per_ws == 3000

    def test_default_supports_streaming_true(self) -> None:
        info = BrokerInfo(
            name="zerodha",
            display_name="Zerodha",
            auth_flow=AuthFlowType.totp_form,
            exchanges=["NSE"],
        )
        assert info.supports_streaming is True

    def test_default_oauth_url_template_none(self) -> None:
        info = BrokerInfo(
            name="zerodha",
            display_name="Zerodha",
            auth_flow=AuthFlowType.totp_form,
            exchanges=["NSE"],
        )
        assert info.oauth_url_template is None

    def test_default_is_sandbox_false(self) -> None:
        info = BrokerInfo(
            name="zerodha",
            display_name="Zerodha",
            auth_flow=AuthFlowType.totp_form,
            exchanges=["NSE"],
        )
        assert info.is_sandbox is False

    def test_creation_with_all_fields(self) -> None:
        info = BrokerInfo(
            name="broker_x",
            display_name="Broker X",
            auth_flow=AuthFlowType.oauth_redirect,
            exchanges=["NSE", "BSE"],
            max_symbols_per_ws=500,
            supports_streaming=False,
            oauth_url_template="https://broker.example.com/oauth?api_key={api_key}",
            is_sandbox=True,
        )
        assert info.max_symbols_per_ws == 500
        assert info.supports_streaming is False
        assert info.oauth_url_template == "https://broker.example.com/oauth?api_key={api_key}"
        assert info.is_sandbox is True

    def test_serialization_round_trip(self) -> None:
        info = BrokerInfo(
            name="zerodha",
            display_name="Zerodha",
            auth_flow=AuthFlowType.totp_form,
            exchanges=["NSE", "NFO"],
            max_symbols_per_ws=3000,
        )
        serialized = info.model_dump()
        restored = BrokerInfo(**serialized)
        assert restored == info

    def test_json_round_trip(self) -> None:
        info = BrokerInfo(
            name="zerodha",
            display_name="Zerodha",
            auth_flow=AuthFlowType.totp_form,
            exchanges=["NSE"],
        )
        json_str = info.model_dump_json()
        restored = BrokerInfo.model_validate_json(json_str)
        assert restored == info

    def test_auth_flow_string_coercion(self) -> None:
        info = BrokerInfo(
            name="zerodha",
            display_name="Zerodha",
            auth_flow="totp_form",  # type: ignore[arg-type]
            exchanges=["NSE"],
        )
        assert info.auth_flow == AuthFlowType.totp_form

    def test_default_aux_params_is_empty_list(self) -> None:
        info = BrokerInfo(
            name="zerodha",
            display_name="Zerodha",
            auth_flow=AuthFlowType.oauth_redirect,
            exchanges=["NSE"],
        )
        assert info.aux_params == []

    def test_aux_params_with_values(self) -> None:
        info = BrokerInfo(
            name="samco",
            display_name="Samco",
            auth_flow=AuthFlowType.otp_multistep,
            exchanges=["NSE", "BSE", "NFO", "CDS", "MCX"],
            aux_params=["secret_api_key", "primary_ip", "secondary_ip"],
        )
        assert info.aux_params == ["secret_api_key", "primary_ip", "secondary_ip"]

    def test_aux_params_serialises_in_model_dump(self) -> None:
        info = BrokerInfo(
            name="samco",
            display_name="Samco",
            auth_flow=AuthFlowType.otp_multistep,
            exchanges=["NSE"],
            aux_params=["secret_api_key"],
        )
        dumped = info.model_dump()
        assert dumped["aux_params"] == ["secret_api_key"]


# ---------------------------------------------------------------------------
# BrokerAccountInfo
# ---------------------------------------------------------------------------


class TestBrokerAccountInfo:
    def test_default_status_is_disconnected(self) -> None:
        account = BrokerAccountInfo(
            account_id="AB1234",
            broker="zerodha",
            label="My Zerodha",
        )
        assert account.status == AccountStatus.disconnected

    def test_default_connected_at_none(self) -> None:
        account = BrokerAccountInfo(
            account_id="AB1234",
            broker="zerodha",
            label="My Zerodha",
        )
        assert account.connected_at is None

    def test_default_error_message_none(self) -> None:
        account = BrokerAccountInfo(
            account_id="AB1234",
            broker="zerodha",
            label="My Zerodha",
        )
        assert account.error_message is None

    def test_default_is_primary_false(self) -> None:
        account = BrokerAccountInfo(
            account_id="AB1234",
            broker="zerodha",
            label="My Zerodha",
        )
        assert account.is_primary is False

    def test_connected_state(self) -> None:
        now = datetime.now(tz=timezone.utc)
        account = BrokerAccountInfo(
            account_id="AB1234",
            broker="zerodha",
            label="Primary",
            status=AccountStatus.connected,
            connected_at=now,
            is_primary=True,
        )
        assert account.status == AccountStatus.connected
        assert account.connected_at == now
        assert account.is_primary is True

    def test_error_state(self) -> None:
        account = BrokerAccountInfo(
            account_id="AB1234",
            broker="zerodha",
            label="Primary",
            status=AccountStatus.error,
            error_message="TOTP mismatch",
        )
        assert account.status == AccountStatus.error
        assert account.error_message == "TOTP mismatch"

    def test_token_expired_state(self) -> None:
        account = BrokerAccountInfo(
            account_id="AB1234",
            broker="zerodha",
            label="Primary",
            status=AccountStatus.token_expired,
        )
        assert account.status == AccountStatus.token_expired

    def test_serialization_round_trip(self) -> None:
        now = datetime.now(tz=timezone.utc)
        account = BrokerAccountInfo(
            account_id="AB1234",
            broker="zerodha",
            label="Primary",
            status=AccountStatus.connected,
            connected_at=now,
            is_primary=True,
        )
        serialized = account.model_dump()
        restored = BrokerAccountInfo(**serialized)
        assert restored == account

    def test_json_round_trip(self) -> None:
        account = BrokerAccountInfo(
            account_id="AB1234",
            broker="zerodha",
            label="Primary",
        )
        json_str = account.model_dump_json()
        restored = BrokerAccountInfo.model_validate_json(json_str)
        assert restored == account

    def test_multiple_accounts_different_brokers(self) -> None:
        accounts = [
            BrokerAccountInfo(account_id="Z1", broker="zerodha", label="Zerodha Main"),
            BrokerAccountInfo(account_id="A1", broker="angel", label="Angel Secondary"),
        ]
        assert accounts[0].broker == "zerodha"
        assert accounts[1].broker == "angel"
        assert all(a.status == AccountStatus.disconnected for a in accounts)
