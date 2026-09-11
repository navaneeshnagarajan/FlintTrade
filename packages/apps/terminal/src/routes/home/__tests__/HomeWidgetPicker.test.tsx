import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { HomeWidgetPicker } from "@/routes/home/HomeWidgetPicker";

describe("HomeWidgetPicker", () => {
  it("disables Watchlist when it is already on the dashboard", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn();

    render(
      <HomeWidgetPicker
        isOpen
        onClose={() => undefined}
        onAdd={onAdd}
        presentComponentIds={new Set(["WatchlistCard"])}
      />,
    );

    const watchlist = screen.getByRole("button", { name: /watchlist widget/i });
    expect(watchlist).toBeDisabled();
    expect(watchlist).toHaveTextContent("Already on the dashboard");

    await user.click(watchlist);
    expect(onAdd).not.toHaveBeenCalled();
  });

  it("keeps a removed widget type addable", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn();

    render(
      <HomeWidgetPicker
        isOpen
        onClose={() => undefined}
        onAdd={onAdd}
        presentComponentIds={new Set(["WelcomeCard"])}
      />,
    );

    const watchlist = screen.getByRole("button", { name: /add watchlist widget/i });
    expect(watchlist).toBeEnabled();

    await user.click(watchlist);
    expect(onAdd).toHaveBeenCalledWith("WatchlistCard");
  });
});
