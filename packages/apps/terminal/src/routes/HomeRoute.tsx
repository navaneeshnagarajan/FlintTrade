/**
 * HomeRoute — Bento dashboard. Default route for all personas.
 * Renders a scrollable BentoGrid of persona-adaptive cards.
 *
 * Wire-up: registered as "/" inside AppLayout in main.tsx.
 */

import { useEffect, useMemo, useState } from "react";
import type { DragEvent, PointerEvent as ReactPointerEvent } from "react";
import { BentoGrid, BentoGridContainer } from "@/components/bento/BentoGrid";
import { AddWidgetCard } from "@/components/bento/AddWidgetCard";
import { BentoCard } from "@/components/bento/BentoCard";
import type { BentoCardSize } from "@/components/bento/BentoCard";
import { HomeWidgetFrame } from "@/routes/home/HomeWidgetFrame";
import { HomeWidgetPicker } from "@/routes/home/HomeWidgetPicker";
import { HOME_WIDGET_CATALOG, HOME_WIDGET_COMPONENTS } from "@/routes/home/homeWidgetRegistry";
import { useBentoStore } from "@/stores/bentoStore";
import StatusBar from "@/chrome/StatusBar";

function UnknownHomeWidgetCard({ componentId }: { componentId: string }) {
  return (
    <BentoCard size="default" label="Unavailable widget">
      <div className="flex h-full min-h-28 flex-col justify-center gap-2 p-4">
        <p className="text-xs font-medium text-text-primary">Unavailable widget</p>
        <p className="text-[11px] leading-snug text-text-muted">
          {componentId} is saved in this layout but is not registered in the home dashboard.
        </p>
      </div>
    </BentoCard>
  );
}

export default function HomeRoute() {
  const [isWidgetPickerOpen, setIsWidgetPickerOpen] = useState(false);
  const [draggedCardId, setDraggedCardId] = useState<string | null>(null);
  const [dragOverCardId, setDragOverCardId] = useState<string | null>(null);
  const [highlightedCardId, setHighlightedCardId] = useState<string | null>(null);
  const cards = useBentoStore((s) => s.cards);
  const addCard = useBentoStore((s) => s.addCard);
  const removeCard = useBentoStore((s) => s.removeCard);
  const reorderCards = useBentoStore((s) => s.reorderCards);
  const resizeCard = useBentoStore((s) => s.resizeCard);
  const sortedCards = useMemo(
    () => [...cards].sort((a, b) => a.order - b.order),
    [cards],
  );
  const widgetLabels = useMemo(
    () => new Map(HOME_WIDGET_CATALOG.map((widget) => [widget.componentId, widget.name])),
    [],
  );

  useEffect(() => {
    if (!highlightedCardId) return undefined;

    const animationFrame = window.requestAnimationFrame(() => {
      const frame = document.querySelector<HTMLElement>(
        `[data-home-card-id="${highlightedCardId}"]`,
      );
      frame?.scrollIntoView({ block: "center", behavior: "smooth" });
      frame?.focus({ preventScroll: true });
    });
    const timeout = window.setTimeout(() => setHighlightedCardId(null), 1800);

    return () => {
      window.cancelAnimationFrame(animationFrame);
      window.clearTimeout(timeout);
    };
  }, [highlightedCardId]);

  function handleAddWidget(componentId: string) {
    const cardId = addCard(componentId);
    setIsWidgetPickerOpen(false);
    setHighlightedCardId(cardId);
  }

  function handleDragStart(cardId: string, event: DragEvent<HTMLButtonElement>) {
    setDraggedCardId(cardId);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("application/x-flinttrade-home-card", cardId);
  }

  function handleDragOver(cardId: string, event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    setDragOverCardId(cardId);
  }

  function handleDragLeave(cardId: string) {
    setDragOverCardId((current) => (current === cardId ? null : current));
  }

  function reorderCard(sourceCardId: string, targetCardId: string) {
    if (sourceCardId === targetCardId) return;
    const nextIds = sortedCards.map((card) => card.id);
    const sourceIndex = nextIds.indexOf(sourceCardId);
    const targetIndex = nextIds.indexOf(targetCardId);
    if (sourceIndex < 0 || targetIndex < 0) return;

    nextIds.splice(sourceIndex, 1);
    nextIds.splice(targetIndex, 0, sourceCardId);
    reorderCards(nextIds);
  }

  function handleDrop(targetCardId: string, event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    const sourceCardId =
      event.dataTransfer.getData("application/x-flinttrade-home-card") || draggedCardId;
    setDraggedCardId(null);
    setDragOverCardId(null);
    if (!sourceCardId) return;
    reorderCard(sourceCardId, targetCardId);
  }

  function handleDragEnd() {
    setDraggedCardId(null);
    setDragOverCardId(null);
  }

  function getPointerTargetCardId(clientX: number, clientY: number): string | null {
    const element = document.elementFromPoint?.(clientX, clientY);
    const frame = element?.closest?.("[data-home-card-id]") as HTMLElement | null;
    return frame?.dataset.homeCardId ?? null;
  }

  function handlePointerDragStart(cardId: string, event: ReactPointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) return;

    event.preventDefault();
    setDraggedCardId(cardId);

    function clearPointerDrag() {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", clearPointerDrag);
      setDraggedCardId(null);
      setDragOverCardId(null);
    }

    function handlePointerMove(pointerEvent: PointerEvent) {
      const targetCardId = getPointerTargetCardId(pointerEvent.clientX, pointerEvent.clientY);
      setDragOverCardId(targetCardId);
    }

    function handlePointerUp(pointerEvent: PointerEvent) {
      const targetCardId = getPointerTargetCardId(pointerEvent.clientX, pointerEvent.clientY);
      clearPointerDrag();
      if (targetCardId) reorderCard(cardId, targetCardId);
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp, { once: true });
    window.addEventListener("pointercancel", clearPointerDrag, { once: true });
  }

  function handleResize(cardId: string, size: BentoCardSize) {
    resizeCard(cardId, size);
  }

  function handleRemove(cardId: string) {
    removeCard(cardId);
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface-base" data-testid="home-route">
      <BentoGridContainer className="min-h-0 flex-1 px-3 pb-20 pt-3">
        <BentoGrid data-testid="home-bento-grid">
          {sortedCards.map((card) => {
            const Widget = HOME_WIDGET_COMPONENTS[card.componentId];
            const label = widgetLabels.get(card.componentId) ?? card.componentId;
            return (
              <HomeWidgetFrame
                key={card.id}
                card={card}
                label={label}
                isDragOver={dragOverCardId === card.id && draggedCardId !== card.id}
                isHighlighted={highlightedCardId === card.id}
                onDragStart={handleDragStart}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onDragEnd={handleDragEnd}
                onPointerDragStart={handlePointerDragStart}
                onRemove={handleRemove}
                onResize={handleResize}
              >
                {Widget ? <Widget /> : <UnknownHomeWidgetCard componentId={card.componentId} />}
              </HomeWidgetFrame>
            );
          })}
          <AddWidgetCard onClick={() => setIsWidgetPickerOpen(true)} />
        </BentoGrid>
      </BentoGridContainer>

      <StatusBar cardCount={sortedCards.length} layoutName="Default" />
      <HomeWidgetPicker
        isOpen={isWidgetPickerOpen}
        onClose={() => setIsWidgetPickerOpen(false)}
        onAdd={handleAddWidget}
      />
    </div>
  );
}
