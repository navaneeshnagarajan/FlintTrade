/**
 * MonitorsSection — Live strategy monitoring tab.
 * Auto-refreshes every 5 seconds. Allows stopping any running strategy.
 */

import { useState } from "react";
import { Activity, Loader2, Square } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { GlassCard } from "@/components/ui/GlassCard";
import { StaggeredList } from "@/components/motion/StaggeredList";
import {
  getRunningStrategies,
  stopStrategy,
  type RunningStrategy,
} from "@/services/ftApi";

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

function StrategyStatusDot({ status }: { status: string }) {
  const lower = status.toLowerCase();
  if (lower === "running")  return <span className="ft-dot-running" />;
  if (lower === "stopping") return <span className="ft-dot-paused" />;
  if (lower === "error")    return <span className="ft-dot-kill" />;
  return <span className="ft-dot-paused" style={{ background: "#6b7280" }} />;
}

function StrategyStatusBadge({ status }: { status: string }) {
  const lower = status.toLowerCase();
  if (lower === "running")  return <Badge className="text-xs bg-profit/10 text-profit border-0">Running</Badge>;
  if (lower === "stopping") return <Badge className="text-xs bg-atm-bg text-warning border-0">Stopping</Badge>;
  if (lower === "error")    return <Badge className="text-xs bg-loss/10 text-loss border-0">Error</Badge>;
  return <Badge className="text-xs bg-text-muted/10 text-text-muted border-0">{status}</Badge>;
}

function formatStartedAt(val: string): string {
  try {
    return new Date(val).toLocaleString("en-IN", {
      timeZone: "Asia/Kolkata",
      dateStyle: "short",
      timeStyle: "short",
    });
  } catch {
    return val;
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MonitorsSection() {
  const queryClient = useQueryClient();
  const [stoppingStrategy, setStoppingStrategy] = useState<string | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["runningStrategies"],
    queryFn: getRunningStrategies,
    refetchInterval: 5000,
  });

  const strategies: RunningStrategy[] = data ?? [];

  const stopMutation = useMutation({
    mutationFn: (name: string) => stopStrategy(name),
    onMutate: (name) => setStoppingStrategy(name),
    onSettled: () => {
      setStoppingStrategy(null);
      void queryClient.invalidateQueries({ queryKey: ["runningStrategies"] });
    },
  });

  return (
    <div className="space-y-4">
      <GlassCard className="p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="font-heading font-semibold text-lg text-text-primary">Live Strategy Monitors</h3>
            <p className="text-sm text-text-secondary mt-0.5">
              Auto-refreshes every 5 seconds. Stop any running strategy instantly.
            </p>
          </div>
          {isLoading && <Loader2 size={14} className="animate-spin text-text-muted" />}
        </div>

        {isError && (
          <p className="text-xs text-loss text-center py-6">
            Failed to load strategies. Backend may be offline.
          </p>
        )}

        {!isLoading && !isError && strategies.length === 0 && (
          <div className="flex flex-col items-center justify-center py-12 gap-2">
            <Activity size={28} className="text-text-muted opacity-40" />
            <p className="text-sm text-text-muted">No strategies running</p>
            <p className="text-xs text-text-muted opacity-60">
              Start a strategy from the Strategy Builder tool.
            </p>
          </div>
        )}

        {strategies.length > 0 && (
          <StaggeredList className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {strategies.map((s) => (
              <div
                key={`${s.name}-${s.symbol}`}
                className="bg-surface-base border border-border-default rounded-lg p-4"
              >
                <div className="flex items-start justify-between gap-2 mb-3">
                  <div className="flex items-center gap-2 min-w-0">
                    <StrategyStatusDot status={s.status} />
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-text-primary truncate">{s.name}</p>
                      <p className="text-xs text-text-muted mt-0.5">{s.symbol} · {s.exchange}</p>
                    </div>
                  </div>
                  <StrategyStatusBadge status={s.status} />
                </div>
                <div className="grid grid-cols-2 gap-2 mb-3">
                  <div>
                    <p className="text-xs text-text-muted">Ticks processed</p>
                    <p className="text-sm font-mono font-bold text-text-primary">
                      {s.tick_count.toLocaleString()}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-text-muted">Started at</p>
                    <p className="text-xs font-mono text-text-secondary">{formatStartedAt(s.started_at)}</p>
                  </div>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => stopMutation.mutate(s.name)}
                  disabled={stoppingStrategy === s.name}
                  className="w-full h-7 text-xs gap-1.5 border-loss/30 text-loss hover:bg-loss/10 hover:border-loss"
                >
                  {stoppingStrategy === s.name ? (
                    <Loader2 size={11} className="animate-spin" />
                  ) : (
                    <Square size={11} />
                  )}
                  {stoppingStrategy === s.name ? "Stopping…" : "Stop Strategy"}
                </Button>
              </div>
            ))}
          </StaggeredList>
        )}
      </GlassCard>
    </div>
  );
}
