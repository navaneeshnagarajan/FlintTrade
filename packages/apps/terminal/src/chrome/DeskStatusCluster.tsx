/**
 * Broker, Laya, and LLM, each with its own label.
 */

import { useState } from "react";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";
import { useOperatorIncident } from "@/hooks/useOperatorIncident";
import { mondayReadChrome } from "@/lib/mondayReadChrome";
import { LayaDegradedLimitsNote } from "@/components/orders/LayaAdmissionNotice";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { brokerSurfaceLabel, chatSurfaceLabel } from "@/lib/deskStatus";
import { buildHeaders, getBase } from "@/services/ftApi.helpers";
import {
  LAYA_START_COMMAND,
  LAYA_START_DOCS_HREF,
  layaChipLabel,
  layaChipStatus,
  layaDisabledLiveReason,
  layaReasonTooltip,
} from "@/lib/layaStatus";

export function DeskStatusCluster() {
  const accounts = useBrokerStore((state) => state.accounts);
  const incident = useOperatorIncident();
  const mode = useModeStore((state) => state.mode);
  const liveStatus = useOperatorSignalStore((state) => state.decisionStatus);
  const practiceStatus = useOperatorSignalStore((state) => state.layaPracticeStatus);
  const liveQualified = useOperatorSignalStore((state) => state.layaLiveQualified);
  const layaReason = useOperatorSignalStore((state) => state.layaReason);
  const layaPort = useOperatorSignalStore((state) => state.layaPort);
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
  const decision = layaChipLabel({
    mode,
    practice: practiceStatus,
    live: liveStatus,
    reason: layaReason,
  });
  const liveReason = layaDisabledLiveReason({ practice: practiceStatus, liveQualified });
  const operational = layaReasonTooltip(layaReason, layaPort);
  const sidecarUp = practiceStatus === "ready" || practiceStatus === "degraded";
  const downFallback = decision === "Down" || decision === "Still loading"
    ? layaReasonTooltip("not_started", layaPort)
    : null;
  const reasonText = operational ?? liveReason ?? downFallback;
  const offerStart = !sidecarUp && (decision === "Down" || decision === "Still loading");
  const [starting, setStarting] = useState(false);
  const [startNote, setStartNote] = useState<string | null>(null);
  const chat = chatSurfaceLabel(llmChrome);
  const decisionTone = decision === "Down"
    ? "text-loss"
    : decision === "Degraded"
      ? "text-amber-400"
      : "text-text-secondary";

  async function startLaya() {
    setStarting(true);
    setStartNote(null);
    try {
      const response = await fetch(`${getBase()}/api/v1/laya/start`, {
        method: "POST",
        headers: buildHeaders(true),
      });
      if (!response.ok) {
        setStartNote("Laya could not be started.");
        return;
      }
      setStartNote("Start requested.");
    } catch {
      setStartNote("Laya could not be started.");
    } finally {
      setStarting(false);
    }
  }

  return (
    <div
      role="group"
      aria-label="Broker, Laya, and LLM status"
      data-testid="desk-status"
      className="flex items-center gap-2 text-xxs text-text-muted"
    >
      <span data-testid="broker-surface">Broker {broker}</span>
      <span aria-hidden="true">·</span>
      <Dialog>
        <DialogTrigger asChild>
          <button
            type="button"
            data-testid="laya-surface"
            className={`${decisionTone} underline-offset-2 hover:underline`}
            title={reasonText ?? undefined}
            aria-label={reasonText ? `Laya ${decision}. ${reasonText}` : `Laya ${decision}`}
            data-laya-reason={layaReason ?? ""}
            data-laya-live-reason={liveReason ?? ""}
          >
            Laya {decision}
          </button>
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Laya {decision}</DialogTitle>
            <DialogDescription>{reasonText ?? `Laya ${decision}`}</DialogDescription>
          </DialogHeader>
          {offerStart ? (
            <div className="space-y-3 text-sm text-text-secondary">
              <p className="font-mono text-xs">{LAYA_START_COMMAND}</p>
              <a
                data-testid="laya-start-docs"
                href={LAYA_START_DOCS_HREF}
                className="underline"
              >
                How to start Laya
              </a>
              <div>
                <Button type="button" disabled={starting} onClick={() => void startLaya()}>
                  {starting ? "Starting…" : "Start Laya"}
                </Button>
              </div>
              {startNote ? <p role="status">{startNote}</p> : null}
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
      <LayaDegradedLimitsNote status={chipStatus} />
      <span aria-hidden="true">·</span>
      <span data-testid="llm-surface">LLM {chat}</span>
    </div>
  );
}
