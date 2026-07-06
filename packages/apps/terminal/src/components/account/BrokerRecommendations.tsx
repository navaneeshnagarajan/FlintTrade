/**
 * BrokerRecommendations — broker capability metadata for routing setup.
 *
 * Surfaces the backend recommendation engine
 * (GET /api/v1/broker/recommendations) which ranks login/read verified native
 * broker metadata per operator-selected job from declared capabilities (lowest
 * cost, market depth, historical data, options analytics, throughput,
 * runtime-ready streaming, advanced orders).
 *
 * This is capability-derived metadata, not live prices or financial advice, so
 * it carries no isConnected guard.
 */

import { useQuery } from "@tanstack/react-query";
import { Lightbulb } from "lucide-react";
import {
  listBrokerRecommendations,
  type BrokerRecommendation,
} from "@/services/ftApi.native";

const USE_CASE_LABELS: Record<string, string> = {
  low_cost_execution: "Lowest cost",
  market_depth: "Market depth",
  historical_data: "Historical data",
  options_analytics: "Options analytics",
  options_history: "Rolling options history",
  order_throughput: "Order throughput",
  streaming: "Live streaming",
  advanced_orders: "Advanced orders",
};

function brokerName(rec: BrokerRecommendation): string {
  return rec.display_name ?? rec.broker_id.charAt(0).toUpperCase() + rec.broker_id.slice(1);
}

interface UseCaseRow {
  useCase: string;
  rec: BrokerRecommendation | null;
  unavailableReason: string;
}

function useCaseRows(useCases: Record<string, BrokerRecommendation[]>): UseCaseRow[] {
  return Object.entries(useCases).map(([useCase, recs]) => {
    const connectable = recs.filter((rec) => rec.connectable !== false);
    const winner = connectable.find((rec) => rec.raw_score > 0) ?? null;
    return {
      useCase,
      rec: winner,
      unavailableReason: winner
        ? ""
        : connectable[0]?.rationale ?? "No verified native broker is ready for this use case.",
    };
  });
}

export function BrokerRecommendations() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["broker", "recommendations"],
    queryFn: listBrokerRecommendations,
    staleTime: 5 * 60_000,
  });

  const rows = useCaseRows(data?.use_cases ?? {});

  return (
    <section
      aria-label="Smart routing suggestions"
      className="rounded-lg border border-border-default bg-surface-card p-4 space-y-3"
    >
      <div className="flex items-center gap-2">
        <Lightbulb size={14} className="text-accent" aria-hidden="true" />
        <h3 className="text-sm font-heading font-semibold text-text-primary">
          Smart routing suggestions
        </h3>
      </div>

      {isLoading && (
        <p className="text-xs text-text-muted">Ranking brokers…</p>
      )}

      {isError && (
        <p className="text-xs text-text-muted">
          Broker recommendations are unavailable right now.
        </p>
      )}

      {data?.openalgo_first && (
        <div className="rounded border border-accent/40 bg-accent/10 px-3 py-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xxs uppercase tracking-wider text-text-muted">Recommended first</span>
            <span className="text-xs font-semibold text-accent">
              {data.openalgo_first.display_name}
            </span>
          </div>
          <p className="mt-0.5 text-xxs text-text-secondary leading-snug">
            {data.openalgo_first.note}
          </p>
        </div>
      )}

      {!isLoading && !isError && rows.length === 0 && (
        <p className="text-xs text-text-muted">
          No native brokers available to rank yet.
        </p>
      )}

      {rows.length > 0 && (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {rows.map(({ useCase, rec, unavailableReason }) => (
            <li
              key={useCase}
              className="rounded border border-border-default bg-surface-base px-3 py-2"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xxs uppercase tracking-wider text-text-muted">
                  {USE_CASE_LABELS[useCase] ?? useCase}
                </span>
                <span
                  className={
                    rec
                      ? "text-xs font-semibold text-accent"
                      : "text-xs font-semibold text-text-muted"
                  }
                >
                  {rec ? brokerName(rec) : "Not ready"}
                </span>
              </div>
              <p className="mt-0.5 text-xxs text-text-secondary leading-snug">
                {rec ? rec.rationale : unavailableReason}
              </p>
            </li>
          ))}
        </ul>
      )}

      {rows.length > 0 && (
        // Honest scope note: these rankings are derived from each broker's
        // advertised API capabilities and default to connectable native brokers.
        // Built-but-disabled adapters such as Kotak Neo stay out until their
        // live checks pass.
        <p className="text-xxs text-text-muted leading-snug border-t border-border-default pt-2">
          Capability-based suggestions for login/read verified native brokers. Coming-soon
          adapters stay hidden here until their live checks pass.
        </p>
      )}
    </section>
  );
}
