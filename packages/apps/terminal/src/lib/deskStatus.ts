/**
 * Three operator surfaces. Broker, Laya, and LLM never share one label.
 */

import { advisorLlmChromeLabel, type AdvisorLlmChrome } from "@/services/advisorChat";
import { honestBrokerStatus, type OperatorIncident } from "@/lib/operatorIncident";

export type DecisionStatus = "ready" | "degraded" | "down";

const CHAT_CHROME: readonly AdvisorLlmChrome[] = [
  "ready",
  "unconfigured",
  "not_installed",
  "disconnected",
  "error",
  "loading",
];

export function decisionSurfaceLabel(status: DecisionStatus | null | undefined): "Ready" | "Degraded" | "Down" {
  if (status === "degraded") return "Degraded";
  if (status === "down") return "Down";
  return "Ready";
}

export function chatSurfaceLabel(chrome: string | null | undefined): string {
  if (chrome && (CHAT_CHROME as readonly string[]).includes(chrome)) {
    return advisorLlmChromeLabel(chrome as AdvisorLlmChrome);
  }
  return "Not configured";
}

export function brokerSurfaceLabel(input: {
  connected: boolean;
  connectedRead: boolean;
  incident: OperatorIncident | null;
}): string {
  const honest = honestBrokerStatus({
    connected: input.connected,
    connectedRead: input.connectedRead,
    nativeMonday: input.connectedRead,
    incident: input.incident,
  });
  if (honest === "Connected" || honest === "Connected (read)") return honest;
  if (honest == null) return "Unavailable";
  return honest;
}
