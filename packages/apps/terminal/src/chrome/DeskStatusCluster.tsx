/**
 * Broker, Laya, and LLM, each with its own label.
 */

import { useEffect, useRef, useState } from "react";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { useAuthStore } from "@/stores/authStore";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";
import { useOperatorIncident } from "@/hooks/useOperatorIncident";
import { mondayReadChrome } from "@/lib/mondayReadChrome";
import { LayaDegradedLimitsNote } from "@/components/orders/LayaAdmissionNotice";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { brokerSurfaceLabel, chatSurfaceLabel } from "@/lib/deskStatus";
import { buildHeaders, getBase, isDemoAuthSession } from "@/services/ftApi.helpers";
import {
  LAYA_START_DOCS_HREF,
  layaChipLabel,
  layaChipStatus,
  layaDisabledLiveReason,
  layaReasonPlain,
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
  const authStatus = useAuthStore((state) => state.status);
  const authToken = useAuthStore((state) => state.token);
  const operator = authStatus === "logged-in" && Boolean(authToken) && !isDemoAuthSession();
  const liveReason = layaDisabledLiveReason({ practice: practiceStatus, liveQualified });
  const sidecarUp = practiceStatus === "ready" || practiceStatus === "degraded";
  const [starting, setStarting] = useState(false);
  const [awaitingLaya, setAwaitingLaya] = useState(false);
  const [startNote, setStartNote] = useState<string | null>(null);
  const startSnapshot = useRef<{ reason: string | null; practice: string | null } | null>(null);
  const shownReason = awaitingLaya ? "still_loading" : layaReason;
  const decision = layaChipLabel({
    mode,
    practice: practiceStatus,
    live: liveStatus,
    reason: shownReason,
  });
  const plainReason = layaReasonPlain(shownReason, layaPort)
    ?? liveReason
    ?? (decision === "Down" ? "Not started" : null);
  const tooltip = layaReasonTooltip(shownReason, layaPort) ?? liveReason ?? undefined;
  const offerStart = operator && !sidecarUp && !awaitingLaya;
  const chat = chatSurfaceLabel(llmChrome);
  const decisionTone = decision === "Down"
    ? "text-loss"
    : decision === "Degraded"
      ? "text-amber-400"
      : "text-text-secondary";

  useEffect(() => {
    if (!awaitingLaya || !startSnapshot.current) return;
    const same = layaReason === startSnapshot.current.reason
      && practiceStatus === startSnapshot.current.practice;
    if (same) return;
    if (practiceStatus === "ready" || practiceStatus === "degraded") {
      setAwaitingLaya(false);
      return;
    }
    if (layaReason === "still_loading") return;
    if (layaReason && layaReason !== "not_started") setAwaitingLaya(false);
  }, [awaitingLaya, practiceStatus, layaReason]);

  async function startLaya() {
    setStarting(true);
    setStartNote(null);
    try {
      const response = await fetch(`${getBase()}/api/v1/laya/start`, {
        method: "POST",
        headers: buildHeaders(true),
      });
      if (!response.ok) {
        setAwaitingLaya(false);
        setStartNote("Laya could not be started.");
        return;
      }
      startSnapshot.current = { reason: layaReason, practice: practiceStatus };
      setAwaitingLaya(true);
      setStartNote(null);
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
      <Popover>
        <PopoverTrigger asChild>
          <button
            type="button"
            data-testid="laya-surface"
            className={`${decisionTone} underline-offset-2 hover:underline`}
            title={tooltip}
            aria-label={plainReason ? `Laya ${decision}. ${plainReason}` : `Laya ${decision}`}
            data-laya-reason={shownReason ?? ""}
            data-laya-live-reason={liveReason ?? ""}
          >
            Laya {decision}
          </button>
        </PopoverTrigger>
        <PopoverContent aria-label="Laya status" className="w-64 space-y-2 p-3 text-xs">
          <p data-testid="laya-reason">{plainReason ?? `Laya ${decision}`}</p>
          <a
            data-testid="laya-start-docs"
            href={LAYA_START_DOCS_HREF}
            className="underline"
          >
            How to start Laya
          </a>
          {offerStart ? (
            <div>
              <Button type="button" disabled={starting} onClick={() => void startLaya()}>
                {starting ? "Starting…" : "Start Laya"}
              </Button>
            </div>
          ) : null}
          {startNote ? <p role="status">{startNote}</p> : null}
        </PopoverContent>
      </Popover>
      <LayaDegradedLimitsNote status={chipStatus} />
      <span aria-hidden="true">·</span>
      <span data-testid="llm-surface">LLM {chat}</span>
    </div>
  );
}
