/**
 * Broker, Laya, and LLM, each with its own label.
 */

import type { ReactNode } from "react";
import { useBrokerStore } from "@/stores/brokerStore";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";
import { useOperatorIncident } from "@/hooks/useOperatorIncident";
import { mondayReadChrome } from "@/lib/connectedReadChrome";
import { LayaDegradedLimitsNote } from "@/components/orders/LayaAdmissionNotice";
import {
  brokerSurfaceLabel,
  chatSurfaceLabel,
  decisionSurfaceLabel,
  type DecisionStatus,
} from "@/lib/deskStatus";
import { cn } from "@/lib/utils";

export interface DeskStatus {
  broker: string;
  decision: "Ready" | "Degraded" | "Down";
  decisionStatus: DecisionStatus | null | undefined;
  chat: string;
}

export function useDeskStatus(): DeskStatus {
  const accounts = useBrokerStore((state) => state.accounts);
  const incident = useOperatorIncident();
  const decisionStatus = useOperatorSignalStore((state) => state.decisionStatus);
  const llmChrome = useOperatorSignalStore((state) => state.llmChrome);
  const readOnly = accounts.some((account) => mondayReadChrome(account) !== null);
  const placeable = accounts.some(
    (account) => account.status === "connected" && mondayReadChrome(account) === null,
  );
  return {
    broker: brokerSurfaceLabel({
      connected: placeable,
      connectedRead: !placeable && readOnly,
      incident,
    }),
    decision: decisionSurfaceLabel(decisionStatus),
    decisionStatus,
    chat: chatSurfaceLabel(llmChrome),
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

function decisionTone(decision: DeskStatus["decision"]): "ok" | "warn" | "down" {
  if (decision === "Ready") return "ok";
  if (decision === "Down") return "down";
  return "warn";
}

function chatTone(chat: string): "ok" | "warn" | "idle" {
  if (chat.startsWith("Connected")) return "ok";
  if (chat === "Error" || chat === "Disconnected") return "warn";
  return "idle";
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

export function DeskStatusCluster({ variant = "inline" }: { variant?: "inline" | "stacked" }) {
  const { broker, decision, decisionStatus, chat } = useDeskStatus();
  const decisionTextTone = decision === "Down"
    ? "text-loss"
    : decision === "Degraded"
      ? "text-amber-400"
      : "text-text-secondary";

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
          value={broker}
          tone={brokerTone(broker)}
        />
        <StatusRow
          testId="laya-surface"
          name="Laya"
          description="Checks every order before it is placed."
          value={decision}
          tone={decisionTone(decision)}
          valueClassName={decisionTextTone}
        >
          <LayaDegradedLimitsNote status={decisionStatus} />
        </StatusRow>
        <StatusRow
          testId="llm-surface"
          name="LLM"
          description="Optional AI model for chat and suggestions."
          value={chat}
          tone={chatTone(chat)}
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
      <span data-testid="broker-surface">Broker {broker}</span>
      <span aria-hidden="true">·</span>
      <span data-testid="laya-surface" className={decisionTextTone}>
        Laya {decision}
      </span>
      <LayaDegradedLimitsNote status={decisionStatus} />
      <span aria-hidden="true">·</span>
      <span data-testid="llm-surface">LLM {chat}</span>
    </div>
  );
}
