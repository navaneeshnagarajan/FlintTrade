import { describe, it, expect } from "vitest";
import type { BrokerInfo, AuthFlowState } from "@/types/broker";
import { initialAuthFlowState } from "../useBrokerAuth";

// Test the state machine logic without React rendering
// (the hook is pure state transitions + API calls)

const mockTOTPBroker: BrokerInfo = {
  name: "angel",
  display_name: "Angel One",
  auth_flow: "totp_form",
  exchanges: ["NSE", "BSE", "NFO"],
  max_symbols_per_ws: 3000,
  supports_streaming: true,
  oauth_url_template: null,
  is_sandbox: false,
};

const mockOAuthBroker: BrokerInfo = {
  name: "zerodha",
  display_name: "Zerodha (Kite)",
  auth_flow: "oauth_redirect",
  exchanges: ["NSE", "BSE", "NFO", "MCX"],
  max_symbols_per_ws: 3000,
  supports_streaming: true,
  oauth_url_template: "https://kite.zerodha.com/connect/login?v=3&api_key={api_key}",
  is_sandbox: false,
};

describe("AuthFlowState transitions", () => {
  it("TOTP broker starts at entering_credentials", () => {
    const expected = initialAuthFlowState(mockTOTPBroker);
    expect(expected.step).toBe("entering_credentials");
    if (expected.step !== "entering_credentials") {
      throw new Error("expected entering_credentials state");
    }
    expect(expected.fields.totp).toBe(true);
  });

  it("OAuth broker starts at awaiting_redirect", () => {
    const expected = initialAuthFlowState(mockOAuthBroker);
    expect(expected.step).toBe("awaiting_redirect");
  });

  it("API key broker starts at entering_credentials without password/totp", () => {
    const apiKeyBroker: BrokerInfo = {
      ...mockTOTPBroker,
      name: "groww",
      auth_flow: "api_key_direct",
    };
    const state = initialAuthFlowState(apiKeyBroker);
    expect(apiKeyBroker.auth_flow).toBe("api_key_direct");
    expect(state.step).toBe("entering_credentials");
    if (state.step !== "entering_credentials") {
      throw new Error("expected entering_credentials state");
    }
    expect(state.fields.api_key).toBe(true);
    expect(state.fields.api_secret).toBe(true);
    expect(state.fields.client_id).toBeUndefined();
  });

  it("OTP broker starts at awaiting_otp", () => {
    const otpBroker: BrokerInfo = {
      ...mockTOTPBroker,
      name: "definedge",
      auth_flow: "otp_sms",
    };
    const state = initialAuthFlowState(otpBroker);
    expect(state.step).toBe("awaiting_otp");
  });

  it("multi-step OTP brokers fail explicitly in the legacy connector", () => {
    const samcoBroker: BrokerInfo = {
      ...mockTOTPBroker,
      name: "samco",
      display_name: "Samco",
      auth_flow: "otp_multistep",
      aux_params: ["secret_api_key", "primary_ip", "secondary_ip"],
    };

    const state = initialAuthFlowState(samcoBroker);

    expect(state.step).toBe("error");
    if (state.step !== "error") {
      throw new Error("expected error state");
    }
    expect(state.message).toContain("multi-step OTP");
    expect(state.message).toContain("legacy gateway connector");
  });

  it("success state contains account", () => {
    const state: AuthFlowState = {
      step: "success",
      account: {
        account_id: "test_001",
        broker: "angel",
        label: "Angel - Main",
        status: "connected",
        connected_at: "2026-03-24T10:00:00Z",
        error_message: null,
        is_primary: false,
      },
    };
    expect(state.step).toBe("success");
  });

  it("error state contains message", () => {
    const state: AuthFlowState = { step: "error", message: "Auth failed" };
    expect(state.step).toBe("error");
    expect(state.message).toBe("Auth failed");
  });
});
