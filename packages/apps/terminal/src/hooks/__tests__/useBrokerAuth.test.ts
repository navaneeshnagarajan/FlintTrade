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
  it("TOTP brokers fail closed into the shared broker surface", () => {
    const state = initialAuthFlowState(mockTOTPBroker);

    expect(state.step).toBe("error");
    if (state.step !== "error") {
      throw new Error("expected retired connector error state");
    }
    expect(state.message).toContain("legacy gateway connector");
    expect(state.message).toContain("Settings -> Brokers");
    expect(state.message).toContain("connectable gate");
  });

  it("OAuth brokers fail closed instead of opening the legacy redirect flow", () => {
    const state = initialAuthFlowState(mockOAuthBroker);

    expect(state.step).toBe("error");
    if (state.step !== "error") {
      throw new Error("expected retired connector error state");
    }
    expect(state.message).toContain("Zerodha");
  });

  it("API key brokers fail closed instead of opening the legacy credential flow", () => {
    const apiKeyBroker: BrokerInfo = {
      ...mockTOTPBroker,
      name: "groww",
      display_name: "Groww",
      auth_flow: "api_key_direct",
    };
    const state = initialAuthFlowState(apiKeyBroker);

    expect(state.step).toBe("error");
    if (state.step !== "error") {
      throw new Error("expected retired connector error state");
    }
    expect(state.message).toContain("Groww");
  });

  it("OTP brokers fail closed instead of opening the legacy OTP flow", () => {
    const otpBroker: BrokerInfo = {
      ...mockTOTPBroker,
      name: "definedge",
      auth_flow: "otp_sms",
    };
    const state = initialAuthFlowState(otpBroker);

    expect(state.step).toBe("error");
  });

  it("multi-step OTP brokers use the same retired connector message", () => {
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
