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
  OLLAMA_START_ACTION,
  OLLAMA_STARTING_ACTION,
  OLLAMA_START_FAILED,
  layaChipLabel,
  layaChipStatus,
  layaDisabledLiveReason,
  type LayaChipLabel,
  layaReasonPlain,
  layaReasonTooltip,
  ollamaChipText,
  ollamaRouteTooltip,
  ollamaStatusMenuDetail,
} from "@/lib/layaStatus";
import { cn } from "@/lib/utils";

/** Shared across Status menu and cluster so Checking clears after the menu closes. */
const layaStartWatch: {
  awaiting: boolean;
  snapshot: { reason: string | null; practice: string | null } | null;
} = { awaiting: false, snapshot: null };

export interface DeskStatus {
  broker: string;
  decision: LayaChipLabel;
  decisionStatus: DecisionStatus | null | undefined;
  chat: string;
}

interface LayaChipView {
  decision: LayaChipLabel;
  chipStatus: DecisionStatus | null;
  shownReason: string | null;
  plainReason: string | null;
  tooltip: string | undefined;
  statusDetail: string | null;
  ollamaRoute: boolean;
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
  const layaRoute = useOperatorSignalStore((state) => state.layaRoute);
  const layaManaged = useOperatorSignalStore((state) => state.layaManaged);
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
  const awaitingStart = layaStartWatch.awaiting;
  const shownReason = awaitingStart ? "still_loading" : layaReason;
  const decision = layaChipLabel({
    mode,
    practice: practiceStatus,
    live: liveStatus,
    reason: shownReason,
    checking: layaChecking,
  });
  const ollamaRoute = layaRoute === "ollama";
  const plainReason = layaChecking
    ? LAYA_CHECKING_DETAIL
    : (ollamaRoute
      ? ollamaChipText(shownReason, layaPort, layaDownloadBytes, layaDownloadTotal)
      : layaReasonPlain(shownReason, layaPort, layaDownloadBytes, layaDownloadTotal))
      ?? liveReason
      ?? (decision === "Down" ? "Not started" : null);
  const tooltip = layaChecking
    ? LAYA_CHECKING_DETAIL
    : ollamaRoute
      ? ollamaRouteTooltip(shownReason, layaPort, layaManaged) ?? liveReason ?? undefined
      : layaReasonTooltip(shownReason, layaPort) ?? liveReason ?? undefined;
  const statusDetail = layaChecking || !ollamaRoute
    ? null
    : ollamaStatusMenuDetail(shownReason, layaManaged);

  useEffect(() => {
    // Use the value this instance rendered: another mounted Status surface may
    // already have settled the shared watcher before this effect runs.
    if (!awaitingStart || !layaStartWatch.snapshot) return;
    const same = layaReason === layaStartWatch.snapshot.reason
      && practiceStatus === layaStartWatch.snapshot.practice;
    // Start makes Checking true. A current-epoch heartbeat can clear it even
    // when a no-op start or failed retry ends at the exact previous status.
    if (same && layaChecking) return;
    if (practiceStatus === "ready" || practiceStatus === "degraded") {
      layaStartWatch.awaiting = false;
      useOperatorSignalStore.getState().setLayaChecking(false);
      // The ping may already have cleared Checking; redraw the settled watcher.
      setWatchTick((tick) => tick + 1);
      return;
    }
    if (layaReason === "still_loading") return;
    if (layaReason && layaReason !== "not_started") {
      layaStartWatch.awaiting = false;
      useOperatorSignalStore.getState().setLayaChecking(false);
      // The ping may already have cleared Checking; redraw the settled watcher.
      setWatchTick((tick) => tick + 1);
    }
  }, [awaitingStart, layaChecking, layaReason, practiceStatus, watchTick]);

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
        setStartNote(OLLAMA_START_FAILED);
        return;
      }
      layaStartWatch.snapshot = { reason: layaReason, practice: practiceStatus };
      layaStartWatch.awaiting = true;
      useOperatorSignalStore.getState().noteLayaUnconfirmed();
      setWatchTick((tick) => tick + 1);
      setStartNote(null);
    } catch {
      setStartNote(OLLAMA_START_FAILED);
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
    statusDetail,
    ollamaRoute,
    liveReason,
    offerStart: operator && !sidecarUp && !layaStartWatch.awaiting && (!ollamaRoute || layaManaged),
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
  if (decision === "Checking" || decision === "Still loading" || decision === "Downloading") return "idle";
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
  description = null,
  value,
  tone,
  valueClassName,
  children,
}: {
  testId: string;
  name: string;
  description?: string | null;
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
        {description ? <p className="text-xs text-text-muted">{description}</p> : null}
        {children}
      </div>
    </div>
  );
}

function LayaActions({
  chip,
  showFallbackReason = true,
}: {
  chip: LayaChipView;
  /** The popover always names the state. The stacked row already shows it as its value. */
  showFallbackReason?: boolean;
}) {
  const reason = chip.plainReason ?? (showFallbackReason ? `Laya ${chip.decision}` : null);
  return (
    <div className="mt-2 space-y-2">
      {reason ? (
        <p data-testid="laya-reason" className="font-medium text-text-primary">
          {reason}
        </p>
      ) : null}
      {chip.statusDetail && chip.statusDetail !== chip.plainReason ? (
        <p data-testid="laya-status-detail">{chip.statusDetail}</p>
      ) : null}
      {chip.tooltip && chip.plainReason && chip.tooltip !== chip.statusDetail && !chip.tooltip.startsWith(chip.plainReason) ? (
        <p data-testid="laya-reason-tooltip">{chip.tooltip}</p>
      ) : null}
      {chip.ollamaRoute ? null : (
        <a data-testid="laya-start-docs" href={LAYA_START_DOCS_HREF} className="underline">
          How to start Laya
        </a>
      )}
      {chip.offerStart ? (
        <div>
          <Button type="button" disabled={chip.starting} onClick={() => void chip.startLaya()}>
            {chip.starting ? OLLAMA_STARTING_ACTION : OLLAMA_START_ACTION}
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
  // The reason is the one bold line inside the row, so the grey description
  // only appears when there is no reason to show.
  const description = chip.plainReason ? null : "Checks every order before it is placed.";

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
          <LayaActions chip={chip} showFallbackReason={false} />
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
