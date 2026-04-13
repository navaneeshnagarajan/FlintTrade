/**
 * NewsCard — Top 3 news stories with sentiment-coloured left borders.
 *
 * Sentiment colour mapping:
 *   positive → #22c55e (green)
 *   negative → #ef4444 (red)
 *   neutral  → #505068 (muted)
 */

import { BentoCard } from "@/components/bento/BentoCard";
import { Newspaper } from "lucide-react";

type Sentiment = "positive" | "negative" | "neutral";

interface NewsItem {
  id: string;
  headline: string;
  source: string;
  sentiment: Sentiment;
  timeAgo: string;
}

const SENTIMENT_COLOR: Record<Sentiment, string> = {
  positive: "#22c55e",
  negative: "#ef4444",
  neutral:  "#505068",
};

// Placeholder stories — will be replaced by real news API in Phase 2
const PLACEHOLDER_NEWS: NewsItem[] = [
  {
    id: "1",
    headline: "RBI holds repo rate steady at 6.5%; maintains accommodative stance",
    source: "ET Markets",
    sentiment: "positive",
    timeAgo: "2h ago",
  },
  {
    id: "2",
    headline: "FIIs sell ₹2,400 Cr in equities; DIIs absorb pressure",
    source: "Moneycontrol",
    sentiment: "negative",
    timeAgo: "4h ago",
  },
  {
    id: "3",
    headline: "IT sector outlook stable; Nifty IT holds 200-DMA support",
    source: "NSE",
    sentiment: "neutral",
    timeAgo: "6h ago",
  },
];

export function NewsCard() {
  return (
    <BentoCard size="wide" label="Top Stories" data-testid="news-card">
      <div className="p-4 h-full flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Newspaper size={13} className="text-[#505068]" aria-hidden="true" />
          <p className="text-[10px] font-medium uppercase tracking-widest text-[#505068]">
            Top Stories
          </p>
        </div>

        <div className="flex-1 space-y-2">
          {PLACEHOLDER_NEWS.map((item) => (
            <div
              key={item.id}
              className="flex gap-3 py-1.5"
              style={{
                borderLeft: `2px solid ${SENTIMENT_COLOR[item.sentiment]}`,
                paddingLeft: "10px",
              }}
            >
              <div className="flex-1 min-w-0">
                <p className="text-xs text-[#e8e8f0] leading-snug line-clamp-2">
                  {item.headline}
                </p>
                <p className="text-[10px] text-[#505068] mt-0.5">
                  {item.source} · {item.timeAgo}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </BentoCard>
  );
}
