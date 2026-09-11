import { beforeEach, describe, expect, it } from "vitest";
import { DEFAULT_CARDS, useBentoStore } from "@/stores/bentoStore";

beforeEach(() => {
  localStorage.clear();
  useBentoStore.setState({
    cards: DEFAULT_CARDS.map((card) => ({ ...card })),
    presets: [],
    activePresetId: null,
  });
});

describe("bentoStore.addCard", () => {
  it("does not create a second Watchlist card when one is already present", () => {
    const before = useBentoStore.getState().cards;
    const existing = before.find((card) => card.componentId === "WatchlistCard");
    expect(existing).toBeDefined();

    const returnedId = useBentoStore.getState().addCard("WatchlistCard");

    const after = useBentoStore.getState().cards;
    expect(returnedId).toBe(existing?.id);
    expect(after.filter((card) => card.componentId === "WatchlistCard")).toHaveLength(1);
    expect(after).toHaveLength(before.length);
  });

  it("adds a Watchlist card after the existing one has been removed", () => {
    useBentoStore.getState().removeCard("card-watchlist");
    expect(
      useBentoStore.getState().cards.some((card) => card.componentId === "WatchlistCard"),
    ).toBe(false);

    const returnedId = useBentoStore.getState().addCard("WatchlistCard");

    const watchlists = useBentoStore.getState().cards.filter(
      (card) => card.componentId === "WatchlistCard",
    );
    expect(watchlists).toHaveLength(1);
    expect(watchlists[0]?.id).toBe(returnedId);
  });
});
