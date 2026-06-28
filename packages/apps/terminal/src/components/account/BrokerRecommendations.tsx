/**
 * BrokerRecommendations — broker capability metadata for routing setup.
 *
 * Surfaces the backend recommendation engine
 * (GET /api/v1/broker/recommendations) which ranks native broker metadata per
 * operator-selected job from declared capabilities (lowest cost, market depth,
 * historical data, options analytics, throughput, streaming, advanced orders).
 *
 * This is capability-derived metadata, not live prices or financial advice, so
 * it carries no isConnected guard.
 */

import { useQuery } from "@tanstack/react-query";
import { Lightbulb } from "lucide-react";
import { get } from "@/services/ftApi";

interface BrokerRec {
  broker_id: string;
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

const BROKER_NAMES: Record<string, string> = {
  dhan: "Dhan",
  upstox: "Upstox",
  kotakneo: "Kotak Neo",
  zerodha: "Zerodha",
  indmoney: "IndMoney",
};

function brokerName(id: string): string {
  return BROKER_NAMES[id] ?? id.charAt(0).toUpperCase() + id.slice(1);
}

export function BrokerRecommendations() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["broker", "recommendations"],
    queryFn: () => get<RecommendationsResponse>("broker/recommendations"),
    staleTime: 5 * 60_000,
  });

  // Pick the top broker per use-case (engine returns each list ranked desc).
  const top = Object.entries(data?.use_cases ?? {})
    .map(([useCase, recs]) => ({ useCase, rec: recs[0] }))
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
                  {brokerName(rec.broker_id)}
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
        // ADVERTISED API capabilities, not a live execution test. The native
        // Dhan/Upstox/Kotak adapters require their SDK + activation before they
        // can place orders; until then orders route through the OpenAlgo bridge.
        <p className="text-xxs text-text-muted leading-snug border-t border-border-default pt-2">
          Capability-based suggestions. Native broker execution needs the broker
          SDK and activation; until activated, orders route via the OpenAlgo
          bridge.
        </p>
      )}
    </section>
  );
}
