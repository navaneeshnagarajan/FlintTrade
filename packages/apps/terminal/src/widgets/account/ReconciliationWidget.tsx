/**
 * ReconciliationWidget — broker-vs-FlintTrade reconciliation observability.
 *
 * Renders the engine ReconciliationRunner's persisted history per native
 * broker target: a clean/severity badge, severity counts, and the last run
 * time, with the latest report's diffs expandable per row. "Reconcile now"
 * triggers an operator `run_once()` cycle through the backend and refreshes
 * the table.
 *
 * API (via lib/reconciliationApi):
 *   GET  /ft-api/api/v1/reconciliation/status
 *   GET  /ft-api/api/v1/reconciliation/reports?broker=&account_id=&limit=
 *   POST /ft-api/api/v1/reconciliation/run
 *
 * Honesty: reconciliation only runs against ACTIVE native broker sessions.
 * When none exist (the runner is dormant) the widget says so plainly rather
 * than rendering fabricated targets.
 */

import { memo, useEffect, useId, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  Loader2,
  RefreshCw,
  Scale,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { emitNotification } from "@/components/NotificationCentre/useNotificationFeed";
import { emitOrdersChanged } from "@/hooks/useOrders";
import {
  useReconciliationOutcomes,
  useReconciliationReports,
  useReconciliationStatus,
  useResolveReconciliationOutcome,
  useRunReconciliation,
  type ReconciliationOutcome,
  type ReconciliationOutcomeItem,
  type ReconciliationReport,
  type ReconciliationResolutionOutcome,
  type ReconciliationTargetStatus,
  type ResolveReconciliationOutcomeResult,
} from "@/lib/reconciliationApi";
import { useModeStore } from "@/stores/modeStore";
import type { WidgetProps } from "@/types/widgets";

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function formatReportTime(iso: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    hour12: false,
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Badges
// ---------------------------------------------------------------------------

function StatusBadge({ target }: { target: ReconciliationTargetStatus }) {
  if (target.clean) {
    return (
      <Badge className="text-xxs bg-profit/10 text-profit border-0 gap-1">
        <ShieldCheck size={10} aria-hidden="true" /> Clean
      </Badge>
    );
  }
  const critical = target.severity === "critical";
  return (
    <Badge
      className={`text-xxs border-0 gap-1 ${
        critical ? "bg-loss/10 text-loss" : "bg-warning/10 text-warning"
      }`}
    >
      <AlertTriangle size={10} aria-hidden="true" />
      {critical ? "Critical" : "Warning"}
    </Badge>
  );
}

function SeverityCounts({ target }: { target: ReconciliationTargetStatus }) {
  const counts = target.severity_counts;
  const chips: Array<{ label: string; value: number; className: string }> = [
    { label: "critical", value: counts?.critical ?? 0, className: "text-loss" },
    {
      label: "warning",
      value: counts?.warning ?? 0,
      className: "text-warning",
    },
    { label: "info", value: counts?.info ?? 0, className: "text-text-muted" },
  ];
  const visible = chips.filter((c) => c.value > 0);
  if (visible.length === 0) {
    return <span className="text-xxs text-text-muted">—</span>;
  }
  return (
    <span className="flex items-center gap-2">
      {visible.map((c) => (
        <span
          key={c.label}
          className={`text-xxs font-mono tabular-nums ${c.className}`}
        >
          {c.value} {c.label}
        </span>
      ))}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Expanded latest-report detail
// ---------------------------------------------------------------------------

function DiffList({ report }: { report: ReconciliationReport }) {
  if (report.error) {
    return (
      <p className="text-xxs text-loss">
        Broker fetch failed — broker state unknown: {report.error}
      </p>
    );
  }
  if (report.clean) {
    return (
      <p className="text-xxs text-profit">
        Clean — the broker and FlintTrade agree completely.
      </p>
    );
  }
  return (
    <div className="space-y-2">
      {report.orders_diff.length > 0 && (
        <div>
          <p className="text-xxs uppercase tracking-wider text-text-muted mb-0.5">
            Orders
          </p>
          <ul className="space-y-0.5">
            {report.orders_diff.map((d, i) => (
              <li
                key={`${d.order_id}-${d.discrepancy}-${i}`}
                className="text-xxs text-text-secondary"
              >
                <span className="font-mono">{d.order_id}</span> {d.symbol} —{" "}
                {d.discrepancy}
                {d.flinttrade_status || d.broker_status
                  ? ` (flinttrade: ${d.flinttrade_status || "—"}, broker: ${d.broker_status || "—"})`
                  : ""}
                {d.detail ? ` · ${d.detail}` : ""}{" "}
                <span
                  className={
                    d.severity === "critical" ? "text-loss" : "text-warning"
                  }
                >
                  [{d.severity}]
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {report.positions_diff.length > 0 && (
        <div>
          <p className="text-xxs uppercase tracking-wider text-text-muted mb-0.5">
            Positions
          </p>
          <ul className="space-y-0.5">
            {report.positions_diff.map((d, i) => (
              <li
                key={`${d.symbol}-${d.exchange}-${d.product}-${i}`}
                className="text-xxs text-text-secondary"
              >
                <span className="font-mono">{d.symbol}</span> {d.exchange}{" "}
                {d.product} — {d.discrepancy}: flinttrade {d.flinttrade_qty} vs
                broker {d.broker_qty}{" "}
                <span className="text-loss">[{d.severity}]</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {report.holdings_diff.length > 0 && (
        <div>
          <p className="text-xxs uppercase tracking-wider text-text-muted mb-0.5">
            Holdings
          </p>
          <ul className="space-y-0.5">
            {report.holdings_diff.map((d, i) => (
              <li
                key={`${d.symbol}-${d.exchange}-${i}`}
                className="text-xxs text-text-secondary"
              >
                <span className="font-mono">{d.symbol}</span> {d.exchange} —{" "}
                {d.discrepancy}: flinttrade {d.flinttrade_qty} vs broker{" "}
                {d.broker_qty}{" "}
                <span className="text-warning">[{d.severity}]</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ReportDetail({
  broker,
  accountId,
}: {
  broker: string;
  accountId: string;
}) {
  const { data, isLoading, isError, error } = useReconciliationReports(
    broker,
    accountId,
    1,
    true,
  );
  if (isLoading) {
    return (
      <p className="text-xxs text-text-muted flex items-center gap-1">
        <Loader2 size={10} className="animate-spin" aria-hidden="true" />{" "}
        Loading latest report…
      </p>
    );
  }
  if (isError) {
    return (
      <p className="text-xxs text-loss">
        Could not load the latest report
        {error instanceof Error ? `: ${error.message}` : ""}
      </p>
    );
  }
  const report = data?.[0];
  if (!report) {
    return (
      <p className="text-xxs text-text-muted">
        No persisted report for this target yet.
      </p>
    );
  }
  return <DiffList report={report} />;
}

// ---------------------------------------------------------------------------
// Unknown-outcome recovery
// ---------------------------------------------------------------------------

function isPlacementOutcome(attempt: ReconciliationOutcome): boolean {
  return (
    attempt.operation === "place_order" ||
    attempt.operation === "place_multi_order" ||
    attempt.operation === "place_reducing_order"
  );
}

function placementItems(
  attempt: ReconciliationOutcome,
): ReconciliationOutcomeItem[] {
  if (!isPlacementOutcome(attempt)) return [];
  if (attempt.operation === "place_multi_order") return attempt.items;
  return [
    {
      item_index: 0,
      symbol: attempt.symbol,
      exchange: attempt.exchange,
      product: attempt.product,
      action: attempt.action,
      quantity: attempt.quantity,
      price: attempt.price,
      trigger_price: attempt.trigger_price,
      price_type: attempt.price_type,
      variety: attempt.variety,
      validity: attempt.validity,
      strategy: attempt.strategy,
    },
  ];
}

function outcomeConfirmationLabel(
  outcome: ReconciliationResolutionOutcome,
): string {
  switch (outcome) {
    case "confirmed_applied":
      return "APPLIED";
    case "confirmed_not_applied":
      return "NOT_APPLIED";
    case "confirmed_partial":
      return "PARTIAL";
  }
}

function expectedConfirmation(
  attempt: ReconciliationOutcome,
  outcome: ReconciliationResolutionOutcome | null,
): string {
  if (outcome === null) return "Select an outcome first";
  const selector = `${attempt.adapter_id}:${attempt.account_id}:${attempt.attempt_id}`;
  return `CONFIRM ${outcomeConfirmationLabel(outcome)} ${selector}`;
}

function isPendingFinalisation(attempt: ReconciliationOutcome): boolean {
  return (
    attempt.resolution?.status === "PENDING_AUDIT" ||
    attempt.resolution?.status === "PENDING_ROUTER_CLEAR"
  );
}

function childIdentity(item: ReconciliationOutcomeItem): string {
  return [
    item.symbol,
    item.exchange,
    item.product,
    `${item.action} ${item.quantity}`,
    `price ${item.price}`,
    item.price_type,
    `trigger ${item.trigger_price}`,
    `variety ${item.variety || "—"}`,
    `validity ${item.validity || "—"}`,
    `strategy ${item.strategy || "—"}`,
  ].join(" · ");
}

function resolutionNotification(result: ResolveReconciliationOutcomeResult): {
  category: "system" | "alert";
  body: string;
} {
  if (result.writes_unblocked) {
    return {
      category: "system",
      body: "The resolution was committed and normal broker writes are unblocked.",
    };
  }
  if (result.status !== "COMMITTED") {
    return {
      category: "alert",
      body:
        `The evidence is recorded, but finalisation remains ${result.status}. ` +
        "Retry finalisation before treating the outcome as resolved.",
    };
  }
  if (
    typeof result.remaining_outcomes === "number" &&
    result.remaining_outcomes > 0
  ) {
    return {
      category: "alert",
      body:
        `The resolution was committed. Normal writes remain blocked by ${result.remaining_outcomes} ` +
        `unresolved outcome${result.remaining_outcomes === 1 ? "" : "s"}.`,
    };
  }
  return {
    category: "alert",
    body: "The resolution was committed, but normal writes remain blocked. Review reconciliation status.",
  };
}

interface OutcomeResolutionDialogProps {
  attempt: ReconciliationOutcome;
  errorMessage: string | null;
  isLive: boolean;
  onClose: () => void;
  onErrorMessageChange: (message: string | null) => void;
}

function OutcomeResolutionDialog({
  attempt,
  errorMessage,
  isLive,
  onClose,
  onErrorMessageChange,
}: OutcomeResolutionDialogProps) {
  const inputId = useId();
  const items = placementItems(attempt);
  const pendingResolution = attempt.resolution;
  const retryOnly = isPendingFinalisation(attempt);
  const [selectedOutcome, setSelectedOutcome] =
    useState<ReconciliationResolutionOutcome | null>(
      pendingResolution?.outcome ?? null,
    );
  const [childEvidence, setChildEvidence] = useState(() => {
    const appliedIndexes = pendingResolution?.broker_order_item_indexes ?? [];
    const notAppliedIndexes = pendingResolution?.not_applied_item_indexes ?? [];
    return items.map((item, position) => {
      let appliedPosition = appliedIndexes.indexOf(item.item_index);
      if (
        appliedPosition === -1 &&
        pendingResolution?.outcome === "confirmed_applied" &&
        appliedIndexes.length === 0
      ) {
        appliedPosition = position;
      }
      const pendingNotApplied =
        notAppliedIndexes.includes(item.item_index) ||
        (pendingResolution?.outcome === "confirmed_not_applied" &&
          notAppliedIndexes.length === 0);
      return {
        item,
        decision:
          appliedPosition >= 0
            ? ("applied" as const)
            : pendingNotApplied
              ? ("not_applied" as const)
              : null,
        brokerOrderId:
          appliedPosition >= 0
            ? (pendingResolution?.broker_order_ids[appliedPosition] ?? "")
            : "",
      };
    });
  });
  const [confirmation, setConfirmation] = useState("");
  const [note, setNote] = useState(pendingResolution?.note ?? "");
  const resolveMutation = useResolveReconciliationOutcome({
    onSuccess: (result) => {
      if (
        result.outcome === "confirmed_applied" ||
        result.outcome === "confirmed_partial"
      ) {
        emitOrdersChanged();
      }
      const notification = resolutionNotification(result);
      emitNotification({
        category: notification.category,
        title: "Order outcome resolved",
        body: notification.body,
      });
      onClose();
    },
    onError: (error, _variables, errorResolution) => {
      const resolution = errorResolution?.resolution;
      if (resolution?.status === "COMMITTED") {
        if (
          resolution.outcome === "confirmed_applied" ||
          resolution.outcome === "confirmed_partial"
        ) {
          emitOrdersChanged();
        }
        emitNotification({
          category: "system",
          title: "Order outcome resolved",
          body: "The durable decision was committed. Reconciliation status is refreshing.",
        });
        onClose();
        return;
      }
      if (
        (resolution?.status === "PENDING_AUDIT" ||
          resolution?.status === "PENDING_ROUTER_CLEAR") &&
        (resolution.outcome === "confirmed_applied" ||
          resolution.outcome === "confirmed_partial")
      ) {
        emitOrdersChanged();
      }
      onErrorMessageChange(error.message || "Outcome resolution failed.");
    },
  });

  const confirmationPhrase = expectedConfirmation(attempt, selectedOutcome);
  const supportedOutcomes = new Set(attempt.recovery_supported_outcomes ?? []);
  const appliedRecoveryAvailable =
    supportedOutcomes.has("confirmed_applied") &&
    (attempt.operation !== "place_multi_order" || items.length > 0);
  const notAppliedRecoveryAvailable = supportedOutcomes.has(
    "confirmed_not_applied",
  );
  const partialRecoveryAvailable =
    supportedOutcomes.has("confirmed_partial") &&
    attempt.operation === "place_multi_order" &&
    items.length > 1;
  const appliedEvidence = childEvidence.filter((entry) =>
    selectedOutcome === "confirmed_applied"
      ? true
      : entry.decision === "applied",
  );
  const notAppliedEvidence = childEvidence.filter((entry) =>
    selectedOutcome === "confirmed_not_applied"
      ? true
      : entry.decision === "not_applied",
  );
  const canonicalBrokerOrderIds = appliedEvidence.map((entry) =>
    entry.brokerOrderId.trim(),
  );
  const brokerOrderIdsValid =
    canonicalBrokerOrderIds.every((orderId) => orderId.length > 0) &&
    new Set(canonicalBrokerOrderIds).size === canonicalBrokerOrderIds.length;
  const freshEvidenceValid =
    selectedOutcome === "confirmed_applied"
      ? !isPlacementOutcome(attempt) ||
        (appliedRecoveryAvailable &&
          appliedEvidence.length === items.length &&
          brokerOrderIdsValid)
      : selectedOutcome === "confirmed_not_applied"
        ? true
        : selectedOutcome === "confirmed_partial"
          ? partialRecoveryAvailable &&
            appliedEvidence.length > 0 &&
            notAppliedEvidence.length > 0 &&
            appliedEvidence.length + notAppliedEvidence.length ===
              items.length &&
            brokerOrderIdsValid
          : false;
  const noteRequired =
    !retryOnly &&
    (selectedOutcome === "confirmed_not_applied" ||
      selectedOutcome === "confirmed_partial");
  const canSubmit =
    isLive &&
    selectedOutcome !== null &&
    confirmation === confirmationPhrase &&
    (retryOnly || freshEvidenceValid) &&
    (!noteRequired || note.trim().length > 0) &&
    !resolveMutation.isPending;

  const selectOutcome = (outcome: ReconciliationResolutionOutcome) => {
    if (retryOnly || selectedOutcome === outcome) return;
    setSelectedOutcome(outcome);
    setConfirmation("");
    setChildEvidence((current) =>
      current.map((entry) => ({
        ...entry,
        decision:
          outcome === "confirmed_applied"
            ? "applied"
            : outcome === "confirmed_not_applied"
              ? "not_applied"
              : null,
        brokerOrderId: "",
      })),
    );
    onErrorMessageChange(null);
  };

  const updateBrokerOrderId = (itemIndex: number, value: string) => {
    setChildEvidence((current) =>
      current.map((entry) =>
        entry.item.item_index === itemIndex
          ? { ...entry, brokerOrderId: value }
          : entry,
      ),
    );
  };

  const updateChildDecision = (
    itemIndex: number,
    decision: "applied" | "not_applied",
  ) => {
    if (retryOnly) return;
    setChildEvidence((current) =>
      current.map((entry) =>
        entry.item.item_index === itemIndex
          ? {
              ...entry,
              decision,
              brokerOrderId:
                decision === "not_applied" ? "" : entry.brokerOrderId,
            }
          : entry,
      ),
    );
  };

  const handleResolve = () => {
    if (!canSubmit || selectedOutcome === null) return;
    onErrorMessageChange(null);
    const pendingBody =
      retryOnly && pendingResolution
        ? {
            broker_order_ids: [...pendingResolution.broker_order_ids],
            broker_order_item_indexes: [
              ...(pendingResolution.broker_order_item_indexes ?? []),
            ],
            not_applied_item_indexes: [
              ...(pendingResolution.not_applied_item_indexes ?? []),
            ],
            note: pendingResolution.note,
          }
        : null;
    const multiOrder = attempt.operation === "place_multi_order";
    resolveMutation.mutate({
      attemptId: attempt.attempt_id,
      body: {
        broker: attempt.adapter_id,
        account_id: attempt.account_id,
        business_date: attempt.business_date,
        outcome: selectedOutcome,
        broker_order_ids:
          pendingBody?.broker_order_ids ?? canonicalBrokerOrderIds,
        broker_order_item_indexes:
          pendingBody?.broker_order_item_indexes ??
          (multiOrder
            ? appliedEvidence.map((entry) => entry.item.item_index)
            : []),
        not_applied_item_indexes:
          pendingBody?.not_applied_item_indexes ??
          (multiOrder
            ? notAppliedEvidence.map((entry) => entry.item.item_index)
            : []),
        confirmation,
        note: pendingBody?.note ?? note.trim(),
      },
    });
  };

  return (
    <AlertDialog
      open
      onOpenChange={(open) => {
        if (!open && !resolveMutation.isPending) onClose();
      }}
    >
      <AlertDialogContent className="max-h-[min(90vh,42rem)] overflow-y-auto sm:max-w-lg">
        <AlertDialogHeader>
          <AlertDialogTitle>
            {retryOnly
              ? "Retry outcome finalisation"
              : "Resolve unknown order outcome"}
          </AlertDialogTitle>
          <AlertDialogDescription>
            Record only the result verified in {attempt.adapter_id} account{" "}
            {attempt.account_id}. This records evidence and does not submit,
            modify, or cancel a broker order.
          </AlertDialogDescription>
        </AlertDialogHeader>

        <dl className="grid grid-cols-1 gap-x-4 gap-y-1 border-y border-border-default py-2 text-xs sm:grid-cols-2">
          <div className="min-w-0">
            <dt className="text-xxs uppercase text-text-muted">Attempt</dt>
            <dd className="break-all font-mono text-text-primary">
              {attempt.attempt_id}
            </dd>
          </div>
          <div className="min-w-0">
            <dt className="text-xxs uppercase text-text-muted">
              Business date
            </dt>
            <dd className="font-mono text-text-primary">
              {attempt.business_date}
            </dd>
          </div>
        </dl>

        {retryOnly && pendingResolution && (
          <p
            className="border border-warning/30 bg-warning/10 px-2 py-1.5 text-xs text-warning"
            role="status"
          >
            Finalisation is {pendingResolution.status}. The recorded decision
            and evidence are locked; this action only retries audit/finalisation
            and router clearance.
          </p>
        )}

        <div className="space-y-2">
          <p
            id={`${inputId}-outcome-label`}
            className="text-xs font-medium text-text-primary"
          >
            Broker-verified outcome
          </p>
          <div
            role="group"
            aria-labelledby={`${inputId}-outcome-label`}
            className="grid grid-cols-1 gap-2 sm:grid-cols-3"
          >
            <Button
              type="button"
              variant="outline"
              aria-pressed={selectedOutcome === "confirmed_applied"}
              onClick={() => selectOutcome("confirmed_applied")}
              disabled={
                retryOnly ||
                resolveMutation.isPending ||
                !appliedRecoveryAvailable
              }
              className={`h-10 justify-start gap-2 whitespace-normal text-xs ${
                selectedOutcome === "confirmed_applied"
                  ? "border-accent bg-accent/10 text-text-primary"
                  : "border-border-default text-text-secondary"
              }`}
            >
              <CheckCircle2 size={14} aria-hidden="true" />
              Confirmed applied
            </Button>
            <Button
              type="button"
              variant="outline"
              aria-pressed={selectedOutcome === "confirmed_not_applied"}
              onClick={() => selectOutcome("confirmed_not_applied")}
              disabled={
                retryOnly ||
                resolveMutation.isPending ||
                !notAppliedRecoveryAvailable
              }
              className={`h-10 justify-start gap-2 whitespace-normal text-xs ${
                selectedOutcome === "confirmed_not_applied"
                  ? "border-accent bg-accent/10 text-text-primary"
                  : "border-border-default text-text-secondary"
              }`}
            >
              <XCircle size={14} aria-hidden="true" />
              Confirmed not applied
            </Button>
            <Button
              type="button"
              variant="outline"
              aria-pressed={selectedOutcome === "confirmed_partial"}
              onClick={() => selectOutcome("confirmed_partial")}
              disabled={
                retryOnly ||
                resolveMutation.isPending ||
                !partialRecoveryAvailable
              }
              className={`h-10 justify-start gap-2 whitespace-normal text-xs ${
                selectedOutcome === "confirmed_partial"
                  ? "border-accent bg-accent/10 text-text-primary"
                  : "border-border-default text-text-secondary"
              }`}
            >
              <AlertTriangle size={14} aria-hidden="true" />
              Confirmed partial
            </Button>
          </div>
          {attempt.recovery_blocked_reason.trim().length > 0 ? (
            <p className="text-xs text-warning" role="status">
              {attempt.recovery_blocked_reason}
            </p>
          ) : !appliedRecoveryAvailable ? (
            <p className="text-xs text-warning">
              Applied recovery is unavailable without persisted child intents.
            </p>
          ) : null}
        </div>

        {selectedOutcome !== null && isPlacementOutcome(attempt) && (
          <div className="space-y-2">
            {childEvidence.map((entry, position) => {
              const acceptsOrderId =
                selectedOutcome === "confirmed_applied" ||
                entry.decision === "applied";
              return (
                <div
                  key={entry.item.item_index}
                  className="space-y-1.5 border-t border-border-subtle pt-2 first:border-t-0 first:pt-0"
                >
                  <p className="break-words font-mono text-xxs text-text-muted">
                    {childIdentity(entry.item)}
                  </p>
                  {selectedOutcome === "confirmed_partial" && (
                    <div
                      className="flex gap-2"
                      role="group"
                      aria-label={`Child ${position + 1} outcome`}
                    >
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        aria-pressed={entry.decision === "applied"}
                        aria-label={`Mark child ${position + 1} applied`}
                        onClick={() =>
                          updateChildDecision(entry.item.item_index, "applied")
                        }
                        disabled={retryOnly || resolveMutation.isPending}
                        className="h-7 text-xxs"
                      >
                        Applied
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        aria-pressed={entry.decision === "not_applied"}
                        aria-label={`Mark child ${position + 1} not applied`}
                        onClick={() =>
                          updateChildDecision(
                            entry.item.item_index,
                            "not_applied",
                          )
                        }
                        disabled={retryOnly || resolveMutation.isPending}
                        className="h-7 text-xxs"
                      >
                        Not applied
                      </Button>
                    </div>
                  )}
                  {acceptsOrderId && (
                    <div className="space-y-1">
                      <Label htmlFor={`${inputId}-broker-order-${position}`}>
                        Broker order ID {position + 1}
                      </Label>
                      <Input
                        id={`${inputId}-broker-order-${position}`}
                        value={entry.brokerOrderId}
                        onChange={(event) =>
                          updateBrokerOrderId(
                            entry.item.item_index,
                            event.target.value,
                          )
                        }
                        autoComplete="off"
                        spellCheck={false}
                        disabled={retryOnly || resolveMutation.isPending}
                        className="font-mono"
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        <div className="space-y-1">
          <Label htmlFor={`${inputId}-note`}>
            Operator note {noteRequired ? "(required)" : "(optional)"}
          </Label>
          <Textarea
            id={`${inputId}-note`}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            maxLength={500}
            disabled={retryOnly || resolveMutation.isPending}
            className="min-h-16 resize-y text-xs"
          />
        </div>

        <div className="space-y-1">
          <Label htmlFor={`${inputId}-confirmation`}>
            Type {confirmationPhrase} to{" "}
            {retryOnly ? "retry finalisation" : "resolve"}
          </Label>
          <Input
            id={`${inputId}-confirmation`}
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            placeholder={confirmationPhrase}
            autoComplete="off"
            spellCheck={false}
            disabled={resolveMutation.isPending}
            className="font-mono"
          />
        </div>

        {!isLive && (
          <p className="text-xs text-warning" role="status">
            Switch the current UI mode to Live before resolving this outcome.
          </p>
        )}
        {errorMessage && (
          <p className="text-xs text-loss" role="alert">
            {errorMessage}
          </p>
        )}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={resolveMutation.isPending}>
            Cancel
          </AlertDialogCancel>
          <AlertDialogAction
            aria-label={`${
              retryOnly ? "Confirm retry finalisation" : "Confirm resolution"
            } for attempt ${attempt.attempt_id}`}
            disabled={!canSubmit}
            onClick={(event) => {
              event.preventDefault();
              handleResolve();
            }}
          >
            {resolveMutation.isPending ? (
              <>
                <Loader2
                  size={13}
                  className="animate-spin"
                  aria-hidden="true"
                />
                Resolving…
              </>
            ) : retryOnly ? (
              "Retry finalisation"
            ) : (
              "Resolve outcome"
            )}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

interface UnknownOutcomesTableProps {
  outcomes: ReconciliationOutcome[];
  isLive: boolean;
  onResolve: (attemptId: string) => void;
}

function UnknownOutcomesTable({
  outcomes,
  isLive,
  onResolve,
}: UnknownOutcomesTableProps) {
  return (
    <Table className="min-w-[680px]">
      <TableHeader>
        <TableRow className="border-border-default hover:bg-transparent">
          <TableHead className="h-7 px-2 py-1 text-xxs uppercase text-text-muted">
            Attempt
          </TableHead>
          <TableHead className="h-7 px-2 py-1 text-xxs uppercase text-text-muted">
            Target
          </TableHead>
          <TableHead className="h-7 px-2 py-1 text-xxs uppercase text-text-muted">
            Intent
          </TableHead>
          <TableHead className="h-7 px-2 py-1 text-xxs uppercase text-text-muted">
            Unknown since
          </TableHead>
          <TableHead className="h-7 px-2 py-1 text-right text-xxs uppercase text-text-muted">
            Action
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {outcomes.map((outcome) => {
          const retryOnly = isPendingFinalisation(outcome);
          const recoveryBlocked =
            !retryOnly &&
            (outcome.recovery_supported_outcomes?.length ?? 0) === 0;
          const recoveryRestricted =
            !retryOnly &&
            !recoveryBlocked &&
            outcome.recovery_blocked_reason.trim().length > 0;
          return (
            <TableRow key={outcome.attempt_id} className="border-border-subtle">
              <TableCell className="max-w-48 px-2 py-1.5">
                <span
                  className="block truncate font-mono text-xxs"
                  title={outcome.attempt_id}
                >
                  {outcome.attempt_id}
                </span>
                <span className="block text-xxs text-loss">
                  {outcome.error_kind || "Unknown result"}
                </span>
                {retryOnly && (
                  <span className="block text-xxs text-warning">
                    {outcome.resolution?.status}
                  </span>
                )}
                {(recoveryBlocked || recoveryRestricted) && (
                  <span
                    className="block text-xxs text-warning"
                    title={outcome.recovery_blocked_reason}
                  >
                    {recoveryBlocked
                      ? "Evidence unavailable"
                      : "Recovery restricted"}
                  </span>
                )}
              </TableCell>
              <TableCell className="px-2 py-1.5">
                <span className="block font-mono text-xxs">
                  {outcome.adapter_id}
                </span>
                <span className="block font-mono text-xxs text-text-muted">
                  {outcome.account_id}
                </span>
              </TableCell>
              <TableCell className="px-2 py-1.5">
                <span className="block font-mono text-xxs">
                  {outcome.symbol || outcome.operation}
                </span>
                <span className="block text-xxs text-text-muted">
                  {outcome.action ? `${outcome.action} ` : ""}
                  {outcome.quantity ? `${outcome.quantity} · ` : ""}
                  {outcome.operation}
                  {outcome.items.length > 1
                    ? ` · ${outcome.items.length} children`
                    : ""}
                </span>
              </TableCell>
              <TableCell className="px-2 py-1.5 text-xxs text-text-muted">
                {formatReportTime(outcome.unknown_at)}
              </TableCell>
              <TableCell className="px-2 py-1.5 text-right">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onResolve(outcome.attempt_id)}
                  disabled={!isLive || recoveryBlocked}
                  aria-label={`${
                    retryOnly ? "Retry finalisation for" : "Resolve"
                  } attempt ${outcome.attempt_id}`}
                  title={
                    recoveryBlocked || recoveryRestricted
                      ? outcome.recovery_blocked_reason
                      : isLive
                        ? retryOnly
                          ? "Retry the locked outcome decision"
                          : "Resolve broker-verified outcome"
                        : "Live mode is required"
                  }
                  className="h-6 gap-1 px-2 text-xxs"
                >
                  <ShieldCheck size={11} aria-hidden="true" />
                  {retryOnly
                    ? "Retry finalisation"
                    : recoveryBlocked
                      ? "Blocked"
                      : "Resolve"}
                </Button>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

// ---------------------------------------------------------------------------
// Widget
// ---------------------------------------------------------------------------

function ReconciliationWidget(_props: WidgetProps) {
  const { data, isLoading, isError, error, refetch, isFetching } =
    useReconciliationStatus();
  const {
    data: outcomesData,
    isLoading: outcomesLoading,
    isError: outcomesError,
    error: outcomesQueryError,
    refetch: refetchOutcomes,
    isFetching: outcomesFetching,
  } = useReconciliationOutcomes();
  const runMutation = useRunReconciliation();
  const appMode = useModeStore((state) => state.mode);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const [resolutionAttemptId, setResolutionAttemptId] = useState<string | null>(
    null,
  );
  const [resolutionError, setResolutionError] = useState<{
    attemptId: string;
    message: string;
  } | null>(null);

  const targets = data?.targets ?? [];
  const runnerActive = data?.runner_active ?? false;
  const outcomes = outcomesData?.outcomes ?? [];
  const resolutionTarget =
    resolutionAttemptId === null
      ? null
      : (outcomes.find(
          (outcome) => outcome.attempt_id === resolutionAttemptId,
        ) ?? null);
  const showOutcomes = outcomesLoading || outcomesError || outcomes.length > 0;
  const isLive = appMode === "live";

  useEffect(() => {
    if (
      resolutionAttemptId !== null &&
      !outcomesLoading &&
      resolutionTarget === null
    ) {
      setResolutionAttemptId(null);
      setResolutionError(null);
    }
  }, [outcomesLoading, resolutionAttemptId, resolutionTarget]);

  const openResolution = (attemptId: string) => {
    setResolutionError(null);
    setResolutionAttemptId(attemptId);
  };

  const closeResolution = () => {
    setResolutionError(null);
    setResolutionAttemptId(null);
  };

  const handleRun = () => {
    runMutation.mutate(undefined, {
      onSuccess: (result) => {
        emitNotification({
          category: "system",
          title: "Reconciliation cycle ran",
          body:
            result.count === 0
              ? "No targets were due — each broker reconciles on its own cadence."
              : `Produced ${result.count} report${result.count === 1 ? "" : "s"}.`,
        });
      },
      onError: (err) => {
        emitNotification({
          category: "alert",
          title: "Reconciliation failed",
          body:
            err instanceof Error
              ? err.message
              : "Could not run reconciliation.",
        });
      },
    });
  };

  return (
    <div className="h-full flex flex-col overflow-hidden text-xs bg-surface-base">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border-default shrink-0">
        <div className="flex items-center gap-2">
          <Scale size={13} className="text-accent" aria-hidden="true" />
          <span className="text-xxs uppercase tracking-wider text-text-muted font-heading font-semibold">
            Reconciliation
          </span>
          <span
            className={`text-xxs ${runnerActive ? "text-profit" : "text-text-muted"}`}
            title={
              runnerActive
                ? "The background runner is polling active native broker sessions."
                : "The background runner is dormant — no native broker sessions."
            }
          >
            {runnerActive ? "Runner active" : "Runner dormant"}
          </span>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={handleRun}
          disabled={runMutation.isPending}
          aria-label="Reconcile now"
          className="h-6 px-2 text-xxs gap-1 border-border-default text-text-secondary hover:text-text-primary transition-colors"
        >
          <RefreshCw
            size={10}
            className={runMutation.isPending ? "animate-spin" : ""}
          />
          {runMutation.isPending ? "Reconciling…" : "Reconcile now"}
        </Button>
      </div>

      {/* Error banner */}
      {isError && (
        <div className="flex items-center gap-2 px-3 py-2 mx-3 mt-2 bg-loss/10 border border-loss/20 rounded-md text-sm text-loss">
          <span className="flex-1">
            Failed to load reconciliation status
            {error instanceof Error ? `: ${error.message}` : ""}
          </span>
          <Button
            variant="link"
            size="sm"
            onClick={() => void refetch()}
            disabled={isFetching}
            className="shrink-0 h-auto p-0 text-xs font-medium text-loss hover:text-loss/80 disabled:opacity-50"
          >
            {isFetching ? "Retrying…" : "Retry"}
          </Button>
        </div>
      )}

      {/* Body */}
      <div className="flex min-h-0 flex-1 flex-col overflow-auto">
        {showOutcomes && (
          <section
            aria-labelledby="unknown-outcomes-heading"
            className="shrink-0 border-b border-border-default"
          >
            <div className="flex min-h-8 flex-wrap items-center justify-between gap-x-3 gap-y-1 px-3 py-1.5">
              <div className="flex min-w-0 items-center gap-2">
                <AlertTriangle
                  size={13}
                  className="shrink-0 text-warning"
                  aria-hidden="true"
                />
                <h2
                  id="unknown-outcomes-heading"
                  className="text-xxs font-semibold uppercase text-text-primary"
                >
                  Unknown order outcomes
                </h2>
                {outcomes.length > 0 && (
                  <Badge className="border-0 bg-warning/10 text-xxs text-warning">
                    {outcomes.length} unresolved
                  </Badge>
                )}
              </div>
              {!isLive && outcomes.length > 0 && (
                <span className="text-xxs text-warning">
                  Live mode required to resolve
                </span>
              )}
            </div>

            {outcomesLoading ? (
              <div className="flex items-center gap-2 border-t border-border-subtle px-3 py-2 text-text-muted">
                <Loader2
                  size={12}
                  className="animate-spin"
                  aria-hidden="true"
                />
                <span className="text-xxs">Loading unknown outcomes…</span>
              </div>
            ) : outcomesError ? (
              <div className="flex items-center gap-2 border-t border-border-subtle px-3 py-2 text-loss">
                <p className="min-w-0 flex-1 text-xs" role="alert">
                  Failed to load unknown outcomes
                  {outcomesQueryError instanceof Error
                    ? `: ${outcomesQueryError.message}`
                    : ""}
                </p>
                <Button
                  variant="link"
                  size="sm"
                  onClick={() => void refetchOutcomes()}
                  disabled={outcomesFetching}
                  className="h-auto shrink-0 p-0 text-xs font-medium text-loss hover:text-loss/80"
                >
                  {outcomesFetching ? "Retrying…" : "Retry"}
                </Button>
              </div>
            ) : (
              <UnknownOutcomesTable
                outcomes={outcomes}
                isLive={isLive}
                onResolve={openResolution}
              />
            )}
          </section>
        )}

        {isLoading ? (
          <div className="flex min-h-40 flex-1 items-center justify-center gap-2 text-text-muted">
            <Loader2 size={14} className="animate-spin" aria-hidden="true" />
            <span className="text-xs">Loading…</span>
          </div>
        ) : targets.length === 0 ? (
          <div className="flex min-h-40 flex-1 flex-col items-center justify-center gap-2 px-4 text-center text-text-muted">
            <Scale
              size={24}
              className="text-text-disabled"
              aria-hidden="true"
            />
            <span className="text-sm">No reconciliation reports yet</span>
            <span className="max-w-72 text-xxs">
              {runnerActive
                ? "The runner is active — the first cycle will appear here shortly."
                : "No native broker sessions active — reconciliation runs once a native adapter is live"}
            </span>
          </div>
        ) : (
          <div className="min-h-0 flex-1">
            <Table>
              <TableHeader className="sticky top-0 bg-surface-card z-10">
                <TableRow className="border-border-default hover:bg-transparent">
                  <TableHead className="text-xxs text-text-muted uppercase tracking-wider px-2 py-1 w-6" />
                  <TableHead className="text-xxs text-text-muted uppercase tracking-wider px-2 py-1">
                    Broker
                  </TableHead>
                  <TableHead className="text-xxs text-text-muted uppercase tracking-wider px-2 py-1">
                    Account
                  </TableHead>
                  <TableHead className="text-xxs text-text-muted uppercase tracking-wider px-2 py-1">
                    Status
                  </TableHead>
                  <TableHead className="text-xxs text-text-muted uppercase tracking-wider px-2 py-1">
                    Issues
                  </TableHead>
                  <TableHead className="text-xxs text-text-muted uppercase tracking-wider px-2 py-1">
                    Last run
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {targets.map((target) => {
                  const key = `${target.broker}:${target.account_id}`;
                  const expanded = expandedKey === key;
                  return [
                    <TableRow
                      key={key}
                      className="border-t border-border-subtle hover:bg-surface-hover/50"
                    >
                      <TableCell className="px-2 py-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setExpandedKey(expanded ? null : key)}
                          aria-label={`${expanded ? "Hide" : "Show"} latest report for ${target.broker} ${target.account_id}`}
                          aria-expanded={expanded}
                          className="h-5 w-5 p-0 text-text-muted hover:text-text-primary"
                        >
                          {expanded ? (
                            <ChevronDown size={12} />
                          ) : (
                            <ChevronRight size={12} />
                          )}
                        </Button>
                      </TableCell>
                      <TableCell className="px-2 py-1 font-mono font-medium whitespace-nowrap">
                        {target.broker}
                      </TableCell>
                      <TableCell className="px-2 py-1 font-mono text-text-secondary whitespace-nowrap">
                        {target.account_id}
                      </TableCell>
                      <TableCell className="px-2 py-1">
                        <StatusBadge target={target} />
                      </TableCell>
                      <TableCell className="px-2 py-1">
                        <SeverityCounts target={target} />
                      </TableCell>
                      <TableCell className="px-2 py-1 text-text-muted whitespace-nowrap">
                        {formatReportTime(target.last_report_at)}
                      </TableCell>
                    </TableRow>,
                    expanded ? (
                      <TableRow
                        key={`${key}-detail`}
                        className="border-t border-border-subtle"
                      >
                        <TableCell
                          colSpan={6}
                          className="px-4 py-2 bg-surface-card/50"
                        >
                          <ReportDetail
                            broker={target.broker}
                            accountId={target.account_id}
                          />
                        </TableCell>
                      </TableRow>
                    ) : null,
                  ];
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      {resolutionTarget && (
        <OutcomeResolutionDialog
          key={`${resolutionAttemptId}:${resolutionTarget.resolution?.resolution_id ?? "new"}:${resolutionTarget.resolution?.status ?? "none"}`}
          attempt={resolutionTarget}
          errorMessage={
            resolutionError?.attemptId === resolutionTarget.attempt_id
              ? resolutionError.message
              : null
          }
          isLive={isLive}
          onClose={closeResolution}
          onErrorMessageChange={(message) => {
            setResolutionError(
              message === null
                ? null
                : { attemptId: resolutionTarget.attempt_id, message },
            );
          }}
        />
      )}
    </div>
  );
}

export default memo(ReconciliationWidget);
