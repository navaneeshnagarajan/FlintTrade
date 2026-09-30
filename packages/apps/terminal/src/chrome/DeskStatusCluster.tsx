/**
 * Broker, Laya, and LLM, each with its own label.
 *
 * The TopBar Status menu and the narrow More sheet use the stacked rows.
 * The inline cluster keeps the Laya popover the desk tests drive.
 */

import { useEffect, useState, type ReactNode } from "react";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { useAuthStore } from "@/stores/authStore";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";
import { useOperatorIncident } from "@/hooks/useOperatorIncident";
import { mondayReadChrome } from "@/lib/connectedReadChrome";
import { LayaDegradedLimitsNote } from "@/components/orders/LayaAdmissionNotice";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { brokerSurfaceLabel, chatSurfaceLabel, type DecisionStatus } from "@/lib/deskStatus";
import { buildHeaders, getBase, isDemoAuthSession } from "@/services/ftApi.helpers";
import {
  LAYA_CHECKING_DETAIL,
  LAYA_START_DOCS_HREF,
  layaChipLabel,
  layaChipStatus,
  layaDisabledLiveReason,
  layaReasonPlain,
  layaReasonTooltip,
} from "@/lib/layaStatus";
import { cn } from "@/lib/utils";

/** Shared across Status menu and cluster so Checking clears after the menu closes. */
const layaStartWatch: {
  awaiting: boolean;
  snapshot: { reason: string | null; practice: string | null } | null;
} = { awaiting: false, snapshot: null };

export interface DeskStatus {
  broker: string;
  decision: "Ready" | "Degraded" | "Down" | "Still loading" | "Checking";
  decisionStatus: DecisionStatus | null | undefined;
  chat: string;
}

interface LayaChipView {
  decision: DeskStatus["decision"];
  chipStatus: DecisionStatus | null;
  shownReason: string | null;
  plainReason: string | null;
  tooltip: string | undefined;
  liveReason: string | null;
  offerStart: boolean;
  starting: boolean;
  startNote: string | null;
  startLaya: () => Promise<void>;
}

export function useDeskStatus(): DeskStatus {
  const chip = useLayaChip();
  return {
    broker: chip.broker,
    decision: chip.decision,
    decisionStatus: chip.layaChecking ? null : chip.chipStatus,
    chat: chip.chat,
  };
}

function useLayaChip() {
  const accounts = useBrokerStore((state) => state.accounts);
  const incident = useOperatorIncident();
  const mode = useModeStore((state) => state.mode);
  const liveStatus = useOperatorSignalStore((state) => state.decisionStatus);
  const practiceStatus = useOperatorSignalStore((state) => state.layaPracticeStatus);
  const liveQualified = useOperatorSignalStore((state) => state.layaLiveQualified);
  const layaReason = useOperatorSignalStore((state) => state.layaReason);
  const layaPort = useOperatorSignalStore((state) => state.layaPort);
  const layaDownloadBytes = useOperatorSignalStore((state) => state.layaDownloadBytes);
  const layaDownloadTotal = useOperatorSignalStore((state) => state.layaDownloadTotal);
  const layaChecking = useOperatorSignalStore((state) => state.layaChecking);
  const llmChrome = useOperatorSignalStore((state) => state.llmChrome);
  const authStatus = useAuthStore((state) => state.status);
  const authToken = useAuthStore((state) => state.token);
  const [starting, setStarting] = useState(false);
  const [startNote, setStartNote] = useState<string | null>(null);
  const [watchTick, setWatchTick] = useState(0);
  const readOnly = accounts.some((account) => mondayReadChrome(account) !== null);
  const placeable = accounts.some(
    (account) => account.status === "connected" && mondayReadChrome(account) === null,
  );
  const operator = authStatus === "logged-in" && Boolean(authToken) && !isDemoAuthSession();
  const chipStatus = layaChipStatus({ mode, practice: practiceStatus, live: liveStatus });
  const liveReason = layaDisabledLiveReason({ practice: practiceStatus, liveQualified });
  const sidecarUp = practiceStatus === "ready" || practiceStatus === "degraded";
  const shownReason = layaStartWatch.awaiting ? "still_loading" : layaReason;
  const decision = layaChipLabel({
    mode,
    practice: practiceStatus,
    live: liveStatus,
    reason: shownReason,
    checking: layaChecking,
  });
  const plainReason = layaChecking
    ? LAYA_CHECKING_DETAIL
    : layaReasonPlain(shownReason, layaPort, layaDownloadBytes, layaDownloadTotal)
      ?? liveReason
      ?? (decision === "Down" ? "Not started" : null);
  const tooltip = layaChecking
    ? LAYA_CHECKING_DETAIL
    : layaReasonTooltip(shownReason, layaPort) ?? liveReason ?? undefined;

  useEffect(() => {
    if (!layaStartWatch.awaiting || !layaStartWatch.snapshot) return;
    const same = layaReason === layaStartWatch.snapshot.reason
      && practiceStatus === layaStartWatch.snapshot.practice;
    if (same) return;
    if (practiceStatus === "ready" || practiceStatus === "degraded") {
      layaStartWatch.awaiting = false;
      useOperatorSignalStore.getState().setLayaChecking(false);
      return;
    }
    if (layaReason === "still_loading") return;
    if (layaReason && layaReason !== "not_started") {
      layaStartWatch.awaiting = false;
      useOperatorSignalStore.getState().setLayaChecking(false);
    }
  }, [layaReason, practiceStatus, watchTick]);

  async function startLaya() {
    setStarting(true);
    setStartNote(null);
    try {
      const response = await fetch(`${getBase()}/api/v1/laya/start`, {
        method: "POST",
        headers: buildHeaders(true),
      });
      if (!response.ok) {
        layaStartWatch.awaiting = false;
        setStartNote("Laya could not be started.");
        return;
      }
      layaStartWatch.snapshot = { reason: layaReason, practice: practiceStatus };
      layaStartWatch.awaiting = true;
      useOperatorSignalStore.getState().noteLayaUnconfirmed();
      setWatchTick((tick) => tick + 1);
      setStartNote(null);
    } catch {
      setStartNote("Laya could not be started.");
    } finally {
      setStarting(false);
    }
  }

  const view: LayaChipView = {
    decision,
    chipStatus,
    shownReason,
    plainReason,
    tooltip,
    liveReason,
    offerStart: operator && !sidecarUp && !layaStartWatch.awaiting,
    starting,
    startNote,
    startLaya,
  };

  return {
    broker: brokerSurfaceLabel({
      connected: placeable,
      connectedRead: !placeable && readOnly,
      incident,
    }),
    chat: chatSurfaceLabel(llmChrome),
    layaChecking,
    ...view,
  };
}

function toneDot(tone: "ok" | "warn" | "down" | "idle"): string {
  if (tone === "ok") return "bg-profit";
  if (tone === "warn") return "bg-amber-400";
  if (tone === "down") return "bg-loss";
  return "bg-text-disabled";
}

function brokerTone(broker: string): "ok" | "warn" | "down" | "idle" {
  if (broker === "Connected") return "ok";
  if (broker === "Connected (read)" || broker.startsWith("Degraded")) return "warn";
  if (broker.startsWith("Unavailable —")) return "down";
  return "idle";
}

function decisionDot(decision: DeskStatus["decision"]): "ok" | "warn" | "down" | "idle" {
  if (decision === "Ready") return "ok";
  if (decision === "Down") return "down";
  if (decision === "Checking" || decision === "Still loading") return "idle";
  return "warn";
}

function chatTone(chat: string): "ok" | "warn" | "idle" {
  if (chat.startsWith("Connected")) return "ok";
  if (chat === "Error" || chat === "Disconnected") return "warn";
  return "idle";
}

function decisionTextClass(decision: DeskStatus["decision"]): string {
  if (decision === "Down") return "text-loss";
  if (decision === "Degraded") return "text-amber-400";
  return "text-text-secondary";
}

function StatusRow({
  testId,
  name,
  description,
  value,
  tone,
  valueClassName,
  children,
}: {
  testId: string;
  name: string;
  description: string;
  value: string;
  tone: "ok" | "warn" | "down" | "idle";
  valueClassName?: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex items-start gap-3 py-2">
      <span aria-hidden="true" className={cn("mt-1.5 size-2 shrink-0 rounded-full", toneDot(tone))} />
      <div className="min-w-0 flex-1">
        <p data-testid={testId} className="flex flex-wrap items-baseline justify-between gap-x-3 text-sm">
          <span className="font-medium text-text-primary">{name}</span>{" "}
          <span className={cn("text-text-secondary", valueClassName)}>{value}</span>
        </p>
        <p className="text-xs text-text-muted">{description}</p>
        {children}
      </div>
    </div>
  );
}

function LayaActions({
  chip,
}: {
  chip: LayaChipView;
}) {
  return (
    <div className="mt-2 space-y-2">
      <p data-testid="laya-reason">{chip.plainReason ?? `Laya ${chip.decision}`}</p>
      {chip.tooltip && chip.plainReason && !chip.tooltip.startsWith(chip.plainReason) ? (
        <p data-testid="laya-reason-tooltip">{chip.tooltip}</p>
      ) : null}
      <a data-testid="laya-start-docs" href={LAYA_START_DOCS_HREF} className="underline">
        How to start Laya
      </a>
      {chip.offerStart ? (
        <div>
          <Button type="button" disabled={chip.starting} onClick={() => void chip.startLaya()}>
            {chip.starting ? "Starting…" : "Start Laya"}
          </Button>
        </div>
      ) : null}
      {chip.startNote ? <p role="status">{chip.startNote}</p> : null}
    </div>
  );
}

export function DeskStatusCluster({ variant = "inline" }: { variant?: "inline" | "stacked" }) {
  const chip = useLayaChip();
  const decisionTextTone = decisionTextClass(chip.decision);
  const description = chip.plainReason ?? "Checks every order before it is placed.";

  if (variant === "stacked") {
    return (
      <div
        role="group"
        aria-label="Broker, Laya, and LLM status"
        data-testid="desk-status"
        className="divide-y divide-border-subtle"
      >
        <StatusRow
          testId="broker-surface"
          name="Broker"
          description="Your broker account for live orders and holdings."
          value={chip.broker}
          tone={brokerTone(chip.broker)}
        />
        <StatusRow
          testId="laya-surface"
          name="Laya"
          description={description}
          value={chip.decision}
          tone={decisionDot(chip.decision)}
          valueClassName={decisionTextTone}
        >
          <LayaActions chip={chip} />
          <LayaDegradedLimitsNote status={chip.layaChecking ? null : chip.chipStatus} />
        </StatusRow>
        <StatusRow
          testId="llm-surface"
          name="LLM"
          description="Optional AI model for chat and suggestions."
          value={chip.chat}
          tone={chatTone(chip.chat)}
        />
      </div>
    );
  }

  return (
    <div
      role="group"
      aria-label="Broker, Laya, and LLM status"
      data-testid="desk-status"
      className="flex items-center gap-2 text-xxs text-text-muted"
    >
      <span data-testid="broker-surface">Broker {chip.broker}</span>
      <span aria-hidden="true">·</span>
      <Popover>
        <PopoverTrigger asChild>
          <button
            type="button"
            data-testid="laya-surface"
            className={`${decisionTextTone} underline-offset-2 hover:underline`}
            title={chip.tooltip}
            aria-label={chip.plainReason ? `Laya ${chip.decision}. ${chip.plainReason}` : `Laya ${chip.decision}`}
            data-laya-reason={chip.shownReason ?? ""}
            data-laya-live-reason={chip.liveReason ?? ""}
          >
            Laya {chip.decision}
          </button>
        </PopoverTrigger>
        <PopoverContent aria-label="Laya status" className="w-64 space-y-2 p-3 text-xs">
          <LayaActions chip={chip} />
        </PopoverContent>
      </Popover>
      <LayaDegradedLimitsNote status={chip.layaChecking ? null : chip.chipStatus} />
      <span aria-hidden="true">·</span>
      <span data-testid="llm-surface">LLM {chip.chat}</span>
    </div>
  );
}
