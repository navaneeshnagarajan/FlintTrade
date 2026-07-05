import { useCallback, useState } from "react";
import type { BrokerInfo, AuthFlowState } from "@/types/broker";

function retiredConnectorMessage(broker?: BrokerInfo): string {
  const suffix = broker ? ` for ${broker.display_name}` : "";
  return (
    `The legacy gateway connector${suffix} is retired. Use Settings -> Brokers ` +
    "or the setup wizard's shared broker surface so OpenAlgo bridge accounts and " +
    "verified native adapters follow the same catalogue, connectable gate, and vault path."
  );
}

export function initialAuthFlowState(broker: BrokerInfo): AuthFlowState {
  return { step: "error", message: retiredConnectorMessage(broker) };
}

export function useBrokerAuth() {
  const [flowState, setFlowState] = useState<AuthFlowState>({ step: "idle" });

  const startFlow = useCallback((broker: BrokerInfo) => {
    setFlowState(initialAuthFlowState(broker));
  }, []);

  const submitCredentials = useCallback(async (
    _label?: string,
    _credentials?: Record<string, string>,
  ) => {
    setFlowState({ step: "error", message: retiredConnectorMessage() });
  }, []);

  const submitOAuth = useCallback(async (_label?: string) => {
    setFlowState({ step: "error", message: retiredConnectorMessage() });
  }, []);

  const reset = useCallback(() => {
    setFlowState({ step: "idle" });
  }, []);

  return { flowState, startFlow, submitCredentials, submitOAuth, reset };
}
