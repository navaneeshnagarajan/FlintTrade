import type { DragEvent, PointerEvent as ReactPointerEvent, ReactNode } from "react";
import { GripVertical, Maximize2, RectangleHorizontal, RectangleVertical, Square, Trash2 } from "lucide-react";
import type { BentoCardConfig } from "@/stores/bentoStore";
import type { BentoCardSize } from "@/components/bento/BentoCard";
import { cn } from "@/lib/utils";

const SIZE_STYLES: Record<BentoCardSize, React.CSSProperties> = {
  default: {},
  wide: { gridColumn: "span 2" },
  tall: { gridRow: "span 2" },
  hero: { gridColumn: "span 2", gridRow: "span 2" },
};

const SIZE_OPTIONS = [
  { size: "default", label: "default", icon: Square },
  { size: "wide", label: "wide", icon: RectangleHorizontal },
  { size: "tall", label: "tall", icon: RectangleVertical },
  { size: "hero", label: "hero", icon: Maximize2 },
] satisfies Array<{
  size: BentoCardSize;
  label: string;
  icon: typeof Square;
}>;

interface HomeWidgetFrameProps {
  card: BentoCardConfig;
  children: ReactNode;
  isDragOver: boolean;
  label: string;
  onDragEnd: () => void;
  onDragLeave: (cardId: string) => void;
  onDragOver: (cardId: string, event: DragEvent<HTMLDivElement>) => void;
  onDragStart: (cardId: string, event: DragEvent<HTMLButtonElement>) => void;
  onDrop: (cardId: string, event: DragEvent<HTMLDivElement>) => void;
  onPointerDragStart: (cardId: string, event: ReactPointerEvent<HTMLButtonElement>) => void;
  onRemove: (cardId: string) => void;
  onResize: (cardId: string, size: BentoCardSize) => void;
}

export function HomeWidgetFrame({
  card,
  children,
  isDragOver,
  label,
  onDragEnd,
  onDragLeave,
  onDragOver,
  onDragStart,
  onDrop,
  onPointerDragStart,
  onRemove,
  onResize,
}: HomeWidgetFrameProps) {
  return (
    <div
      data-testid={`home-widget-frame-${card.id}`}
      data-home-card-id={card.id}
      data-bento-size={card.size}
      className={cn(
        "home-widget-frame group relative flex min-h-28 flex-col gap-1 transition-[opacity,outline-color,transform] duration-150",
        isDragOver && "rounded outline outline-2 outline-accent/60",
      )}
      style={SIZE_STYLES[card.size]}
      onDragOver={(event) => onDragOver(card.id, event)}
      onDragLeave={() => onDragLeave(card.id)}
      onDrop={(event) => onDrop(card.id, event)}
    >
      <div className="home-widget-toolbar ml-auto flex h-8 items-center gap-1 rounded border border-border-default/80 bg-surface-card/90 p-1 shadow-sm backdrop-blur-sm opacity-80 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
        <button
          type="button"
          draggable
          data-drag-handle="true"
          aria-label={`Drag ${label} widget`}
          title={`Drag ${label}`}
          className="flex size-6 cursor-grab items-center justify-center rounded text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary active:cursor-grabbing focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
          onDragStart={(event) => onDragStart(card.id, event)}
          onDragEnd={onDragEnd}
          onPointerDown={(event) => onPointerDragStart(card.id, event)}
        >
          <GripVertical size={13} aria-hidden="true" />
        </button>

        <span aria-hidden="true" className="h-4 w-px bg-border-default" />

        {SIZE_OPTIONS.map((option) => {
          const Icon = option.icon;
          const isActive = card.size === option.size;
          return (
            <button
              key={option.size}
              type="button"
              aria-label={`Make ${label} widget ${option.label}`}
              aria-pressed={isActive}
              title={`${label}: ${option.label}`}
              className={cn(
                "flex size-6 items-center justify-center rounded transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
                isActive
                  ? "bg-accent/15 text-accent"
                  : "text-text-muted hover:bg-surface-hover hover:text-text-primary",
              )}
              onClick={() => onResize(card.id, option.size)}
            >
              <Icon size={12} aria-hidden="true" />
            </button>
          );
        })}

        <span aria-hidden="true" className="h-4 w-px bg-border-default" />

        <button
          type="button"
          aria-label={`Remove ${label} widget`}
          title={`Remove ${label}`}
          className="flex size-6 items-center justify-center rounded text-text-muted transition-colors hover:bg-loss/10 hover:text-loss focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-loss/40"
          onClick={() => onRemove(card.id)}
        >
          <Trash2 size={12} aria-hidden="true" />
        </button>
      </div>

      {children}

      <style>{`
        .home-widget-frame > .bento-card {
          flex: 1 1 auto;
          height: 100%;
          min-height: 100%;
        }
      `}</style>
    </div>
  );
}
