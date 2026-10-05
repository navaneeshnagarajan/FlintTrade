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
  if (status === "ready") return "Ready";
  if (status === "down") return "Down";
  // No heartbeat yet. Do not paint Ready until Laya reports one.
  return "Degraded";
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

export type DeskStatusTone = "ok" | "warn" | "down" | "neutral";

/**
 * One worst-first summary of the three surfaces, for the TopBar Status dot.
 * The label names the worst row, and "All systems ready" is used only when
 * no row is worse than Ready.
 * Example data has nothing connected by design, so it is neutral, never red.
 * No broker is expected in Practice, so it reads "Broker unavailable" in the
 * neutral colour; in Live it is the first thing to fix.
 * A model download reads "Laya starting", also neutral.
 * The LLM is optional: unconfigured stays quiet, a failing one warns.
 */
export function summariseDeskStatus(input: {
  mode: "explore" | "practice" | "live";
  broker: string;
  decision: "Ready" | "Degraded" | "Down" | "Still loading" | "Checking" | "Downloading";
  chat: string;
}): { tone: DeskStatusTone; label: string } {
  if (input.mode === "explore") return { tone: "neutral", label: "Example data only" };
  if (input.decision === "Down") return { tone: "down", label: "Laya down" };
  if (input.broker.startsWith("Unavailable —")) return { tone: "down", label: "Broker unavailable" };
  if (input.mode === "live" && input.broker === "Unavailable") {
    return { tone: "down", label: "No broker connected" };
  }
  if (input.decision === "Degraded") return { tone: "warn", label: "Laya degraded" };
  if (input.broker.startsWith("Degraded —")) return { tone: "warn", label: "Broker degraded" };
  if (input.chat === "Error" || input.chat === "Disconnected") {
    return { tone: "warn", label: "AI model offline" };
  }
  if (input.decision === "Checking") return { tone: "neutral", label: "Checking Laya" };
  if (input.decision === "Still loading") return { tone: "neutral", label: "Laya still loading" };
  if (input.decision === "Downloading") return { tone: "neutral", label: "Laya starting" };
  if (input.broker === "Unavailable") return { tone: "neutral", label: "Broker unavailable" };
  return { tone: "ok", label: "All systems ready" };
}
