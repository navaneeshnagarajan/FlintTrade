import { FlintMiniSparkline } from "@flinttrade/design-system";
import { TrendingUp, TrendingDown } from "lucide-react";

export interface SparklineProps {
  prices:   number[];
  positive: boolean | null;
}

export function Sparkline({ prices, positive }: SparklineProps) {
  if (!prices || prices.length < 2) {
    return (
      <div className="w-10 h-4 flex items-center justify-center">
        {positive === true  && <TrendingUp  size={10} className="text-profit" />}
        {positive === false && <TrendingDown size={10} className="text-loss"  />}
        {positive == null  && <span className="text-xxs text-text-muted">—</span>}
      </div>
    );
  }

  const trendLabel = positive === false ? "falling" : positive === true ? "rising" : "flat";

  return (
    <FlintMiniSparkline
      points={prices}
      positive={positive !== false}
      ariaLabel={`Watchlist price trend: ${trendLabel}`}
      className="h-4 w-10 shrink-0"
    />
  );
}
