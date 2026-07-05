import { useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { gatewayApi } from "@/services/gatewayApi";
import { useBrokerStore } from "@/stores/brokerStore";
import type { BrokerInfo, AuthFlowState } from "@/types/broker";

export function initialAuthFlowState(broker: BrokerInfo): AuthFlowState {
  switch (broker.auth_flow) {
    case "oauth_redirect":
      return { step: "awaiting_redirect", broker, redirectUrl: "" };
    case "totp_form":
      return {
        step: "entering_credentials",
        broker,
        fields: { client_id: true, password: true, totp: true, pin: false },
      };
    case "api_key_direct":
      return {
        step: "entering_credentials",
        broker,
        fields: { api_key: true, api_secret: true },
      };
    case "otp_sms":
      return { step: "awaiting_otp", broker };
    case "otp_multistep":
      return {
        step: "error",
        message: `${broker.display_name} uses a multi-step OTP flow that is not available in the legacy gateway connector. Use the native broker setup once this broker is marked connectable.`,
      };
  }
}

export function useBrokerAuth() {
  const [flowState, setFlowState] = useState<AuthFlowState>({ step: "idle" });
  const addAccount = useBrokerStore((s) => s.addAccount);
  const queryClient = useQueryClient();

  const startFlow = useCallback((broker: BrokerInfo) => {
    setFlowState(initialAuthFlowState(broker));
  }, []);

  const submitCredentials = useCallback(
    async (label: string, credentials: Record<string, string>) => {
      if (flowState.step !== "entering_credentials") return;
      const broker = flowState.broker;
      setFlowState({ step: "authenticating", broker });
      try {
        const account = await gatewayApi.addAccount(broker.name, label, credentials);
        addAccount(account);
        queryClient.invalidateQueries({ queryKey: ["gateway", "accounts"] });
        setFlowState({ step: "success", account });
      } catch (e) {
        setFlowState({ step: "error", message: e instanceof Error ? e.message : "Unknown error" });
      }
    },
    [flowState, addAccount, queryClient],
  );

  const submitOAuth = useCallback(
    async (label: string) => {
      if (flowState.step !== "awaiting_redirect") return;
      const broker = flowState.broker;
      try {
        const { redirect_url } = await gatewayApi.startOAuth(broker.name, label);
        setFlowState({ step: "awaiting_redirect", broker, redirectUrl: redirect_url });
        window.open(redirect_url, "_blank");
      } catch (e) {
        setFlowState({ step: "error", message: e instanceof Error ? e.message : "Unknown error" });
      }
    },
    [flowState],
  );

  const reset = useCallback(() => {
    setFlowState({ step: "idle" });
  }, []);

  return { flowState, startFlow, submitCredentials, submitOAuth, reset };
}
