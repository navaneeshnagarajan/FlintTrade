/**
 * ActionCenterWidget — pending order approval queue.
 *
 * Displays orders that have been queued by the engine's 5-layer safety
 * system and require manual approval before being sent to the broker.
 *
 * Features:
 * - Table: Symbol / Action / Qty / Price / Order type / Strategy / Approve / Reject
 * - "Approve All" button at the top
 * - Badge count of pending orders (also shown on TOOLS button in TopBar)
 * - Auto-refresh every 5s when the widget is mounted
 *
 * API:
 *   GET  /ft-api/api/v1/action-center/pending
 *   POST /ft-api/api/v1/action-center/approve/:id
 *   POST /ft-api/api/v1/action-center/reject/:id
 *   POST /ft-api/api/v1/action-center/approve-all
 */

import { useCallback, memo } from "react";
import { CheckCircle2, XCircle, CheckCheck, Loader2, ShieldCheck } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  getPendingOrders,
  approveOrder,
  rejectOrder,
  approveAllOrders,
  type PendingOrder,
} from "@/services/ftApi";
import type { WidgetProps } from "@/types/widgets";

// ---------------------------------------------------------------------------
// Action badge colour for BUY / SELL
// ---------------------------------------------------------------------------

function ActionBadge({ action }: { action: PendingOrder["action"] }) {
  if (action === "BUY") {
    return (
      <Badge className="text-xxs bg-profit/10 text-profit border-0 font-mono">
        BUY
      </Badge>
    );
  }
  return (
    <Badge className="text-xxs bg-loss/10 text-loss border-0 font-mono">
      SELL
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

interface OrderRowProps {
  order: PendingOrder;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  disabled: boolean;
}

function OrderRow({ order, onApprove, onReject, disabled }: OrderRowProps) {
  const age = Math.floor(
    (Date.now() - new Date(order.created_at).getTime()) / 1000,
  );
  const ageLabel =
    age < 60 ? `${age}s` : age < 3600 ? `${Math.floor(age / 60)}m` : `${Math.floor(age / 3600)}h`;

  return (
    <TableRow className="border-border-default hover:bg-surface-hover">
      <TableCell className="py-1.5 text-xs font-mono font-medium text-text-primary">
        {order.symbol}
      </TableCell>
      <TableCell className="py-1.5">
        <ActionBadge action={order.action} />
      </TableCell>
      <TableCell className="py-1.5 text-xs font-mono tabular-nums text-text-primary">
        {order.quantity}
      </TableCell>
      <TableCell className="py-1.5 text-xs font-mono tabular-nums text-text-primary">
        {order.price > 0
          ? order.price.toLocaleString("en-IN", {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })
          : "MKT"}
      </TableCell>
      <TableCell className="py-1.5 text-xxs text-text-secondary">
        {order.order_type}
      </TableCell>
      <TableCell className="py-1.5 text-xxs text-text-muted max-w-20 truncate">
        {order.strategy}
      </TableCell>
      <TableCell className="py-1.5 text-xxs text-text-muted font-mono tabular-nums">
        {ageLabel}
      </TableCell>
      <TableCell className="py-1.5">
        <div className="flex items-center gap-1">
          <Button
            size="sm"
            variant="ghost"
            disabled={disabled}
            onClick={() => onApprove(order.id)}
            aria-label={`Approve order: ${order.action} ${order.quantity} ${order.symbol}`}
            className="h-6 w-6 p-0 text-profit hover:bg-profit/10 transition-colors"
          >
            <CheckCircle2 size={13} />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={disabled}
            onClick={() => onReject(order.id)}
            aria-label={`Reject order: ${order.action} ${order.quantity} ${order.symbol}`}
            className="h-6 w-6 p-0 text-loss hover:bg-loss/10 transition-colors"
          >
            <XCircle size={13} />
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
}

// ---------------------------------------------------------------------------
// Widget
// ---------------------------------------------------------------------------

function ActionCenterWidget(_props: WidgetProps) {
  const queryClient = useQueryClient();

  const { data: orders, isLoading, isError } = useQuery({
    queryKey: ["actionCenterPending"],
    queryFn: getPendingOrders,
    refetchInterval: 5_000,
  });

  const pending = orders ?? [];

  const invalidate = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["actionCenterPending"] });
  }, [queryClient]);

  const approveMutation = useMutation({
    mutationFn: (id: string) => approveOrder(id),
    onSettled: invalidate,
  });

  const rejectMutation = useMutation({
    mutationFn: (id: string) => rejectOrder(id),
    onSettled: invalidate,
  });

  const approveAllMutation = useMutation({
    mutationFn: () => approveAllOrders(),
    onSettled: invalidate,
  });

  const anyPending =
    approveMutation.isPending ||
    rejectMutation.isPending ||
    approveAllMutation.isPending;

  return (
    <div className="h-full flex flex-col overflow-hidden bg-surface-base text-xs">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border-default shrink-0">
        <div className="flex items-center gap-2">
          <ShieldCheck size={13} className="text-accent" aria-hidden="true" />
          <span className="text-xxs uppercase tracking-wider text-text-muted font-heading font-semibold">
            Action Center
          </span>
          {pending.length > 0 && (
            <Badge
              className="text-xxs px-1.5 py-0 h-4 bg-loss/15 text-loss border-0 font-mono"
              aria-label={`${pending.length} pending`}
            >
              {pending.length}
            </Badge>
          )}
        </div>

        {pending.length > 0 && (
          <Button
            size="sm"
            variant="outline"
            disabled={anyPending}
            onClick={() => approveAllMutation.mutate()}
            className="h-6 px-2 text-xxs gap-1 border-border-default text-profit hover:bg-profit/10 hover:border-profit/40 hover:text-profit transition-colors"
            aria-label={`Approve all ${pending.length} pending orders`}
          >
            {approveAllMutation.isPending ? (
              <Loader2 size={10} className="animate-spin" />
            ) : (
              <CheckCheck size={10} />
            )}
            Approve All
          </Button>
        )}
      </div>

      {/* Body */}
      {isLoading && (
        <div className="flex items-center justify-center flex-1 gap-2 text-text-muted">
          <Loader2 size={14} className="animate-spin" />
          <span className="text-xs">Loading…</span>
        </div>
      )}

      {isError && (
        <div className="flex flex-col items-center justify-center flex-1 gap-1 text-center px-4">
          <span className="text-loss text-xs">Failed to load pending orders.</span>
          <span className="text-text-muted text-xxs">Backend may be offline.</span>
        </div>
      )}

      {!isLoading && !isError && pending.length === 0 && (
        <div className="flex flex-col items-center justify-center flex-1 gap-2 text-center px-4">
          <CheckCheck size={22} className="text-profit/50" aria-hidden="true" />
          <span className="text-xs text-text-muted">No pending orders.</span>
          <span className="text-xxs text-text-muted">
            Orders queued for approval will appear here.
          </span>
        </div>
      )}

      {!isLoading && !isError && pending.length > 0 && (
        <ScrollArea className="flex-1">
          <Table>
            <TableHeader>
              <TableRow className="border-border-default hover:bg-transparent">
                <TableHead className="text-xxs text-text-muted font-medium py-1.5">
                  Symbol
                </TableHead>
                <TableHead className="text-xxs text-text-muted font-medium py-1.5">
                  Side
                </TableHead>
                <TableHead className="text-xxs text-text-muted font-medium py-1.5">
                  Qty
                </TableHead>
                <TableHead className="text-xxs text-text-muted font-medium py-1.5">
                  Price
                </TableHead>
                <TableHead className="text-xxs text-text-muted font-medium py-1.5">
                  Type
                </TableHead>
                <TableHead className="text-xxs text-text-muted font-medium py-1.5">
                  Strategy
                </TableHead>
                <TableHead className="text-xxs text-text-muted font-medium py-1.5">
                  Age
                </TableHead>
                <TableHead className="text-xxs text-text-muted font-medium py-1.5 w-16">
                  Action
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pending.map((order) => (
                <OrderRow
                  key={order.id}
                  order={order}
                  onApprove={(id) => approveMutation.mutate(id)}
                  onReject={(id) => rejectMutation.mutate(id)}
                  disabled={anyPending}
                />
              ))}
            </TableBody>
          </Table>
        </ScrollArea>
      )}

      {/* Footer — reason for last order if available */}
      {pending.length > 0 && pending[0].reason && (
        <div className="px-3 py-1.5 border-t border-border-default shrink-0">
          <p className="text-xxs text-text-muted truncate">
            Reason: {pending[0].reason}
          </p>
        </div>
      )}
    </div>
  );
}

export default memo(ActionCenterWidget);
