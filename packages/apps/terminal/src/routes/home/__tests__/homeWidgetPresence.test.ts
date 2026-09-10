import { describe, expect, it } from "vitest";
import {
  presentHomeComponentIds,
  resolveHomeWidgetPlacement,
} from "@/routes/home/homeWidgetPresence";

describe("home widget presence", () => {
  it("collects component ids already on the dashboard", () => {
    const present = presentHomeComponentIds([
      { componentId: "WatchlistCard" },
      { componentId: "WelcomeCard" },
    ]);

    expect([...present]).toEqual(["WatchlistCard", "WelcomeCard"]);
  });

  it("focuses an existing Watchlist instead of adding another", () => {
    expect(
      resolveHomeWidgetPlacement(
        [{ id: "card-watchlist", componentId: "WatchlistCard" }],
        "WatchlistCard",
      ),
    ).toEqual({ kind: "focus", cardId: "card-watchlist" });
  });

  it("adds a widget type that is not already on the dashboard", () => {
    expect(
      resolveHomeWidgetPlacement(
        [{ id: "card-welcome", componentId: "WelcomeCard" }],
        "WatchlistCard",
      ),
    ).toEqual({ kind: "add", componentId: "WatchlistCard" });
  });
});
