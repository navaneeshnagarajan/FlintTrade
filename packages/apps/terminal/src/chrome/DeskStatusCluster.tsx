/**
 * Broker, Laya, and LLM, each with its own label.
 */

import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";
import { useOperatorIncident } from "@/hooks/useOperatorIncident";
import { mondayReadChrome } from "@/lib/mondayReadChrome";
import { LayaDegradedLimitsNote } from "@/components/orders/LayaAdmissionNotice";
import { brokerSurfaceLabel, chatSurfaceLabel, decisionSurfaceLabel } from "@/lib/deskStatus";
import { layaChipStatus, layaDisabledLiveReason } from "@/lib/layaStatus";

export function DeskStatusCluster() {
  const accounts = useBrokerStore((state) => state.accounts);
  const incident = useOperatorIncident();
  const mode = useModeStore((state) => state.mode);
  const liveStatus = useOperatorSignalStore((state) => state.decisionStatus);
  const practiceStatus = useOperatorSignalStore((state) => state.layaPracticeStatus);
  const liveQualified = useOperatorSignalStore((state) => state.layaLiveQualified);
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
  const chipStatus = layaChipStatus({ mode, practice: practiceStatus, live: liveStatus });
  const decision = decisionSurfaceLabel(chipStatus);
  const liveReason = layaDisabledLiveReason({ practice: practiceStatus, liveQualified });
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
      <span aria-hidden="true">·</span>
      <span
        data-testid="laya-surface"
        className={decisionTone}
        title={liveReason ?? undefined}
        data-laya-live-reason={liveReason ?? ""}
      >
        Laya {decision}
      </span>
      <LayaDegradedLimitsNote status={chipStatus} />
      <span aria-hidden="true">·</span>
      <span data-testid="llm-surface">LLM {chat}</span>
    </div>
  );
}
