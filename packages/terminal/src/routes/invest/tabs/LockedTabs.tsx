/**
 * LockedTabs.tsx
 *
 * Feature-locked placeholder tabs: ETFs, Stocks, IPO.
 * All three render a FeatureLockCard until their backends are built.
 * Colocated in one file since each is trivially small.
 */

import { BarChart3, Search, TrendingUp } from "lucide-react";
import { FeatureLockCard } from "@/components/teasers";

export function EtfTab() {
  return (
    <div className="flex items-center justify-center h-full min-h-80 px-8">
      <FeatureLockCard
        config={{ featureName: "ETF Tracker", status: "in_dev", version: "v0.3.0" }}
        description="Track ETF performance, compare with indices, analyze tracking error."
        icon={<BarChart3 className="w-8 h-8" />}
        className="max-w-sm w-full"
      />
    </div>
  );
}

export function StocksTab() {
  return (
    <div className="flex items-center justify-center h-full min-h-80 px-8">
      <FeatureLockCard
        config={{ featureName: "Stock Screener", status: "in_dev", version: "v0.3.0" }}
        description="Filter stocks by technical indicators, fundamentals, and custom criteria."
        icon={<Search className="w-8 h-8" />}
        className="max-w-sm w-full"
      />
    </div>
  );
}

export function IpoTab() {
  return (
    <div className="flex items-center justify-center h-full min-h-80 px-8">
      <FeatureLockCard
        config={{ featureName: "IPO Tracker", status: "in_dev", version: "v0.3.0" }}
        description="Upcoming IPOs, subscription status, listing performance analysis."
        icon={<TrendingUp className="w-8 h-8" />}
        className="max-w-sm w-full"
      />
    </div>
  );
}
