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
import { get } from "@/services/ftApi";

interface BrokerRec {
  broker_id: string;
  display_name?: string;
  connectable?: boolean;
  score: number;
  raw_score: number;
  rationale: string;
}

interface RecommendationsResponse {
  status: string;
  use_cases: Record<string, BrokerRec[]>;
}

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

function brokerName(rec: BrokerRec): string {
  return rec.display_name ?? rec.broker_id.charAt(0).toUpperCase() + rec.broker_id.slice(1);
}

export function BrokerRecommendations() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["broker", "recommendations"],
    queryFn: () => get<RecommendationsResponse>("broker/recommendations"),
    staleTime: 5 * 60_000,
  });

  // Pick the top positive-scoring, connectable broker per use-case.
  const top = Object.entries(data?.use_cases ?? {})
    .map(([useCase, recs]) => ({
      useCase,
      rec: recs.find((rec) => rec.connectable !== false && rec.raw_score > 0),
    }))
    .filter((r): r is { useCase: string; rec: BrokerRec } => Boolean(r.rec));

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

      {!isLoading && !isError && top.length === 0 && (
        <p className="text-xs text-text-muted">
          No native brokers available to rank yet.
        </p>
      )}

      {top.length > 0 && (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {top.map(({ useCase, rec }) => (
            <li
              key={useCase}
              className="rounded border border-border-default bg-surface-base px-3 py-2"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xxs uppercase tracking-wider text-text-muted">
                  {USE_CASE_LABELS[useCase] ?? useCase}
                </span>
                <span className="text-xs font-semibold text-accent">
                  {brokerName(rec)}
                </span>
              </div>
              <p className="mt-0.5 text-xxs text-text-secondary leading-snug">
                {rec.rationale}
              </p>
            </li>
          ))}
        </ul>
      )}

      {top.length > 0 && (
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
