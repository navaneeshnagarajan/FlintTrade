/**
 * LockedTabs.tsx
 *
 * Feature-locked placeholder tabs: IPO.
 * These render a FeatureLockCard until their backends are built.
 *
 * StocksTab has been moved to StocksTab.tsx (real implementation).
 * EtfTab has been moved to EtfTab.tsx.
 * Colocated in one file since each remaining tab is trivially small.
 */

import { TrendingUp } from "lucide-react";
import { FeatureLockCard } from "@/components/teasers";

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
