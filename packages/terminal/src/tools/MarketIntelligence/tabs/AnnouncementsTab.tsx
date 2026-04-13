import { useState, useMemo } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ANNOUNCEMENTS, CATEGORY_COLORS } from "../data";
import { DataNotice } from "../shared";

export function AnnouncementsTab() {
  const [filterCat, setFilterCat] = useState<string>("All");

  const categories = ["All", ...Array.from(new Set(ANNOUNCEMENTS.map((a) => a.category)))];

  const filtered = useMemo(() => {
    if (filterCat === "All") return ANNOUNCEMENTS;
    return ANNOUNCEMENTS.filter((a) => a.category === filterCat);
  }, [filterCat]);

  return (
    <div className="p-4">
      <DataNotice text="Corporate announcements from NSE/BSE. Live feed via data source. Showing representative structure." />

      <div className="flex flex-wrap gap-1.5 mb-4">
        {categories.map((cat) => (
          <button
            key={cat}
            onClick={() => setFilterCat(cat)}
            className={[
              "text-xs px-2 py-0.5 rounded border transition-colors",
              filterCat === cat
                ? "bg-neutral-bg text-primary border-neutral-border"
                : "bg-surface-card text-text-muted border-border-default hover:border-border-strong",
            ].join(" ")}
          >
            {cat}
          </button>
        ))}
        <span className="text-xs text-text-muted ml-auto self-center">
          {filtered.length} of {ANNOUNCEMENTS.length}
        </span>
      </div>

      <div className="space-y-2">
        {filtered.map((ann, i) => {
          const catCls = CATEGORY_COLORS[ann.category] ?? "text-text-secondary border-border-default";
          return (
            <Card key={i} className="bg-surface-card border-border-default hover:border-border-default transition-colors">
              <CardContent className="pt-3 pb-3 px-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs font-semibold font-mono text-primary">{ann.symbol}</span>
                      <Badge className={`text-xxs h-4 px-1.5 bg-transparent border ${catCls}`}>
                        {ann.category}
                      </Badge>
                      <Badge className="text-xxs h-4 px-1.5 bg-surface-elevated text-text-muted border-border-default">
                        {ann.exchange}
                      </Badge>
                    </div>
                    <p className="text-xs text-text-secondary leading-relaxed line-clamp-2">
                      {ann.subject}
                    </p>
                  </div>
                  <div className="text-xs text-text-muted font-mono shrink-0 pt-0.5">
                    {ann.date}
                  </div>
                </div>
              </CardContent>
            </Card>
          );
        })}
        {filtered.length === 0 && (
          <div className="text-center py-8 text-xs text-text-muted">
            No announcements in this category.
          </div>
        )}
      </div>
    </div>
  );
}
