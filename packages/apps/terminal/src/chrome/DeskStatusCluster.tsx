/**
 * Broker, Laya, and LLM, each with its own label.
 */

import { useBrokerStore } from "@/stores/brokerStore";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";
import { useOperatorIncident } from "@/hooks/useOperatorIncident";
import { mondayReadChrome } from "@/lib/mondayReadChrome";
import { brokerSurfaceLabel, chatSurfaceLabel, decisionSurfaceLabel } from "@/lib/deskStatus";

export function DeskStatusCluster() {
  const accounts = useBrokerStore((state) => state.accounts);
  const incident = useOperatorIncident();
  const decisionStatus = useOperatorSignalStore((state) => state.decisionStatus);
  const llmChrome = useOperatorSignalStore((state) => state.llmChrome);
  const readOnly = accounts.some((account) => mondayReadChrome(account) !== null);
  const placeable = accounts.some(
    (account) => account.status === "connected" && mondayReadChrome(account) === null,
  );
  const broker = brokerSurfaceLabel({
    connected: placeable,
    connectedRead: !placeable && readOnly,
    incident,
  });
  const decision = decisionSurfaceLabel(decisionStatus);
  const chat = chatSurfaceLabel(llmChrome);
  const decisionTone = decision === "Down"
    ? "text-loss"
    : decision === "Degraded"
      ? "text-amber-400"
      : "text-text-secondary";

  return (
    <div
      role="group"
      aria-label="Broker, Laya, and LLM status"
      data-testid="desk-status"
      className="flex items-center gap-2 text-xxs text-text-muted"
    >
      <span data-testid="broker-surface">Broker {broker}</span>
      <span data-testid="laya-surface" className={decisionTone}>
        Laya {decision}
      </span>
      <span data-testid="llm-surface">LLM {chat}</span>
    </div>
  );
}
