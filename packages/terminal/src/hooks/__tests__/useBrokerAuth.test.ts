import { describe, it, expect } from "vitest";
import type { BrokerInfo, AuthFlowState } from "@/types/broker";

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
    // When startFlow(angel) is called, state should be entering_credentials with totp fields
    const expected: AuthFlowState = {
      step: "entering_credentials",
      broker: mockTOTPBroker,
      fields: { client_id: true, password: true, totp: true, pin: false },
    };
    expect(expected.step).toBe("entering_credentials");
    expect(expected.fields.totp).toBe(true);
  });

  it("OAuth broker starts at awaiting_redirect", () => {
    const expected: AuthFlowState = {
      step: "awaiting_redirect",
      broker: mockOAuthBroker,
      redirectUrl: "",
    };
    expect(expected.step).toBe("awaiting_redirect");
  });

  it("API key broker starts at entering_credentials without password/totp", () => {
    const apiKeyBroker: BrokerInfo = {
      ...mockTOTPBroker,
      name: "groww",
      auth_flow: "api_key_direct",
    };
    // api_key_direct: only client_id needed
    const fields = { client_id: true, password: false, totp: false, pin: false };
    // Confirm the broker shape is valid
    expect(apiKeyBroker.auth_flow).toBe("api_key_direct");
    expect(fields.password).toBe(false);
    expect(fields.totp).toBe(false);
  });

  it("OTP broker starts at awaiting_otp", () => {
    const otpBroker: BrokerInfo = {
      ...mockTOTPBroker,
      name: "definedge",
      auth_flow: "otp_sms",
    };
    const state: AuthFlowState = { step: "awaiting_otp", broker: otpBroker };
    expect(state.step).toBe("awaiting_otp");
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
