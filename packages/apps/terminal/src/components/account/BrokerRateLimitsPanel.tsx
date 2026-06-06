/**
 * BrokerRateLimitsPanel — per-broker API rate-limit controls.
 *
 * Reads the live effective limits from the gateway (GET /ft-api/v1/rate-limits)
 * and lets the operator tune each broker's order/data throttle (requests/sec,
 * 0 = unlimited). A save applies live to the running limiter and persists to
 * workspace.json. The limiter sits BELOW the safety gate — it can only delay a
 * dispatch, never bypass safety — so this never affects order validation.
 */

import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Gauge } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { gatewayApi } from "@/services/gatewayApi";

interface RowState {
  order: string;
  data: string;
}

function isValidRate(v: string): boolean {
  const n = Number(v);
  return v.trim() !== "" && !Number.isNaN(n) && n >= 0;
}

export function BrokerRateLimitsPanel() {
  const queryClient = useQueryClient();
  const { data: limits, isLoading } = useQuery({
    queryKey: ["gateway", "rate-limits"],
    queryFn: gatewayApi.getRateLimits,
  });

  const [edits, setEdits] = useState<Record<string, RowState>>({});
  useEffect(() => {
    if (limits) {
      setEdits(
        Object.fromEntries(
          Object.entries(limits).map(([broker, v]) => [
            broker,
            { order: String(v.order), data: String(v.data) },
          ]),
        ),
      );
    }
  }, [limits]);

  const save = useMutation({
    mutationFn: (args: { brokerId: string; order: number; data: number }) =>
      gatewayApi.setRateLimit(args.brokerId, args.order, args.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["gateway", "rate-limits"] }),
  });

  const brokers = Object.keys(limits ?? {});

  return (
    <div className="rounded-lg border border-border-default bg-surface-base p-4" data-testid="rate-limits-panel">
      <div className="flex items-center gap-2 mb-3">
        <Gauge size={14} className="text-accent" aria-hidden="true" />
        <span className="text-sm font-semibold text-text-primary">API Rate Limits</span>
      </div>

      {isLoading ? (
        <p className="text-xs text-text-muted py-2">Loading limits…</p>
      ) : brokers.length === 0 ? (
        <p className="text-xs text-text-muted py-2">
          No rate-limited brokers connected. Limits appear here once a broker adapter with
          rate metadata is active.
        </p>
      ) : (
        <ul className="space-y-2" aria-label="Per-broker rate limits">
          {brokers.map((broker) => {
            const row = edits[broker] ?? { order: "", data: "" };
            const valid = isValidRate(row.order) && isValidRate(row.data);
            const setRow = (patch: Partial<RowState>) =>
              setEdits((prev) => ({ ...prev, [broker]: { ...row, ...patch } }));
            return (
              <li
                key={broker}
                className="flex items-center gap-2 rounded border border-border-default bg-surface-card px-2 py-1.5"
              >
                <span className="text-xs font-medium text-text-primary w-24 truncate">{broker}</span>
                <label className="flex items-center gap-1 text-xxs text-text-muted">
                  Orders/s
                  <Input
                    value={row.order}
                    onChange={(e) => setRow({ order: e.target.value })}
                    aria-label={`${broker} order rate per second`}
                    className="h-6 w-16 text-xs font-mono"
                    inputMode="decimal"
                  />
                </label>
                <label className="flex items-center gap-1 text-xxs text-text-muted">
                  Data/s
                  <Input
                    value={row.data}
                    onChange={(e) => setRow({ data: e.target.value })}
                    aria-label={`${broker} data rate per second`}
                    className="h-6 w-16 text-xs font-mono"
                    inputMode="decimal"
                  />
                </label>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-6 px-2 text-xxs ml-auto"
                  disabled={!valid || save.isPending}
                  onClick={() =>
                    save.mutate({ brokerId: broker, order: Number(row.order), data: Number(row.data) })
                  }
                  aria-label={`Save ${broker} rate limits`}
                >
                  {save.isPending && save.variables?.brokerId === broker ? "Saving…" : "Save"}
                </Button>
              </li>
            );
          })}
        </ul>
      )}

      <p className="text-xxs text-text-muted mt-3">
        Requests per second; <span className="font-mono">0</span> = unlimited. Changes apply
        live and are saved to <span className="font-mono">workspace.json</span> for the next restart.
      </p>
      {save.isError && (
        <p className="text-xxs text-loss mt-1">Could not save — {(save.error as Error).message}</p>
      )}
    </div>
  );
}
