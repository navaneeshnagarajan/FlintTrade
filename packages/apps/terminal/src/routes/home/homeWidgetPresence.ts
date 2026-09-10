/**
 * Home dashboard widgets are singletons: one card per catalogue type.
 * The Add-widget picker and layout store share this rule so an already-present
 * Watchlist (or any other home card) cannot be duplicated.
 */

export interface HomeWidgetCardRef {
  id: string;
  componentId: string;
}

export type HomeWidgetPlacement =
  | { kind: "focus"; cardId: string }
  | { kind: "add"; componentId: string };

export function presentHomeComponentIds(
  cards: readonly { componentId: string }[],
): ReadonlySet<string> {
  return new Set(cards.map((card) => card.componentId));
}

export function resolveHomeWidgetPlacement(
  cards: readonly HomeWidgetCardRef[],
  componentId: string,
): HomeWidgetPlacement {
  const existing = cards.find((card) => card.componentId === componentId);
  if (existing) {
    return { kind: "focus", cardId: existing.id };
  }
  return { kind: "add", componentId };
}
