import { useMemo } from "react";
import { LayoutGrid, Wrench, Navigation, Zap, Palette } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Command, CommandCategory } from "./useCommandRegistry";

const CATEGORY_ICONS: Record<CommandCategory, React.ReactNode> = {
  widget:   <LayoutGrid  size={13} aria-hidden="true" />,
  tool:     <Wrench      size={13} aria-hidden="true" />,
  navigate: <Navigation  size={13} aria-hidden="true" />,
  action:   <Zap         size={13} aria-hidden="true" />,
  theme:    <Palette     size={13} aria-hidden="true" />,
};

interface CommandsTabProps {
  commands: Command[];
  query: string;
  activeIndex: number;
  onSelect: (cmd: Command) => void;
  onActiveIndexChange: (index: number) => void;
}

export function CommandsTab({ commands, query, activeIndex, onSelect, onActiveIndexChange }: CommandsTabProps) {
  const filtered = useMemo(() => {
    if (!query) return commands;
    const q = query.toLowerCase();
    return commands.filter(
      (cmd) =>
        cmd.title.toLowerCase().includes(q) ||
        cmd.description?.toLowerCase().includes(q),
    );
  }, [commands, query]);

  if (filtered.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-text-muted">
        <p className="text-sm">No commands match &ldquo;{query}&rdquo;</p>
      </div>
    );
  }

  return (
    <ul role="listbox" aria-label="Commands" className="overflow-y-auto max-h-80 py-1">
      {filtered.map((cmd, i) => (
        <li
          key={cmd.id}
          role="option"
          aria-selected={i === activeIndex}
          onMouseEnter={() => onActiveIndexChange(i)}
          onClick={() => onSelect(cmd)}
          className={cn(
            "flex items-center gap-3 px-4 py-2.5 cursor-pointer select-none transition-colors",
            i === activeIndex ? "bg-glass-l3" : "hover:bg-glass-l2",
          )}
        >
          <span
            className={cn(
              "shrink-0 flex items-center justify-center w-6 h-6 rounded text-text-muted",
              i === activeIndex && "text-accent",
            )}
          >
            {CATEGORY_ICONS[cmd.category]}
          </span>
          <span className="flex-1 min-w-0">
            <span className="block text-sm text-text-primary leading-snug truncate">
              <HighlightMatch text={cmd.title} query={query} />
            </span>
            {cmd.description && (
              <span className="block text-xs text-text-muted leading-snug truncate mt-0.5">
                {cmd.description}
              </span>
            )}
          </span>
          {cmd.shortcut && (
            <kbd className="shrink-0 font-mono text-[10px] text-text-muted bg-glass-l1 border border-glass-l1 rounded px-1.5 py-0.5 leading-none">
              {cmd.shortcut}
            </kbd>
          )}
        </li>
      ))}
    </ul>
  );
}

function HighlightMatch({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return <>{text}</>;
  return (
    <>
      {text.slice(0, idx)}
      <span className="text-accent font-medium">{text.slice(idx, idx + query.length)}</span>
      {text.slice(idx + query.length)}
    </>
  );
}
