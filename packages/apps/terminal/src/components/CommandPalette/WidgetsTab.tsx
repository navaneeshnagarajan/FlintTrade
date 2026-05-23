// WidgetsTab.tsx
import { useEffect, useMemo } from "react";
import { LayoutGrid } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Command } from "./useCommandRegistry";

interface WidgetsTabProps {
  widgets: Command[];
  query: string;
  activeIndex: number;
  onSelect: (cmd: Command) => void;
  onActiveIndexChange: (index: number) => void;
}

export function WidgetsTab({ widgets, query, activeIndex, onSelect, onActiveIndexChange }: WidgetsTabProps) {
  const filtered = useMemo(() => {
    if (!query) return widgets;
    const q = query.replace(/^#\s*/, "").toLowerCase();
    if (!q) return widgets;
    return widgets.filter(
      (w) => w.title.toLowerCase().includes(q) || w.description?.toLowerCase().includes(q),
    );
  }, [widgets, query]);

  // Clamp activeIndex to list bounds
  useEffect(() => {
    if (filtered.length > 0 && activeIndex >= filtered.length) {
      onActiveIndexChange(filtered.length - 1);
    }
  }, [activeIndex, filtered.length, onActiveIndexChange]);

  if (filtered.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-text-muted">
        <p className="text-sm">No widgets match &ldquo;{query.replace(/^#\s*/, "")}&rdquo;</p>
      </div>
    );
  }

  return (
    <ul role="listbox" aria-label="Widgets" className="overflow-y-auto max-h-80 py-1">
      {filtered.map((w, i) => (
        <li
          key={w.id}
          role="option"
          aria-selected={i === activeIndex}
          onMouseEnter={() => onActiveIndexChange(i)}
          onClick={() => onSelect(w)}
          className={cn(
            "flex items-center gap-3 px-4 py-2.5 cursor-pointer select-none transition-colors",
            i === activeIndex ? "bg-glass-l3" : "hover:bg-glass-l2",
          )}
        >
          <LayoutGrid size={13} aria-hidden="true" className={cn("shrink-0 text-text-muted", i === activeIndex && "text-accent")} />
          <span className="flex-1 min-w-0">
            <span className="block text-sm text-text-primary leading-snug truncate">{w.title}</span>
            {w.description && (
              <span className="block text-xs text-text-muted leading-snug truncate mt-0.5">{w.description}</span>
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}
