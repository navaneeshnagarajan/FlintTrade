import { StrictMode, startTransition } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DURATION, motionConfig } from "@/lib/motion";
import PageTransition from "../PageTransition";

describe("PageTransition", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("fills the Trade route body so the desk can flex", () => {
    vi.spyOn(motionConfig, "prefersReducedMotion").mockReturnValue(false);

    render(
      <PageTransition locationKey="/trade">
        <div data-testid="trade-desk">Trade desk</div>
      </PageTransition>,
    );

    const fill = screen.getByTestId("route-body-fill");
    expect(fill.className).toMatch(/flex-1/);
    expect(fill.className).toMatch(/min-h-0/);
    expect(fill.className).toMatch(/h-full/);
    expect(screen.getByTestId("trade-desk")).toBeInTheDocument();
  });

  it("finishes the outgoing page before showing the next page", async () => {
    vi.spyOn(motionConfig, "prefersReducedMotion").mockReturnValue(false);

    const { rerender } = render(
      <PageTransition locationKey="/home">
        <span>Home page</span>
      </PageTransition>,
    );

    await waitFor(() => {
      expect(screen.getByText("Home page").parentElement).toHaveStyle({ opacity: "1" });
    });

    rerender(
      <PageTransition locationKey="/settings">
        <span>Settings page</span>
      </PageTransition>,
    );

    expect(screen.getByText("Home page")).toBeInTheDocument();
    expect(screen.queryByText("Settings page")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText("Home page")).not.toBeInTheDocument();
      expect(screen.getByText("Settings page").parentElement).toHaveStyle({ opacity: "1" });
    }, { timeout: 3_000 });
  });

  it.each(["Learn", "Home"])("settles on %s after interrupted navigation in StrictMode", async (latestPage) => {
    vi.spyOn(motionConfig, "prefersReducedMotion").mockReturnValue(false);
    const page = (key: string) => (
      <StrictMode>
        <PageTransition locationKey={`/${key}`}>
          <span>{key} page</span>
        </PageTransition>
      </StrictMode>
    );
    const { rerender } = render(page("Home"));

    await waitFor(() => {
      expect(screen.getByText("Home page").parentElement).toHaveStyle({ opacity: "1" });
    });
    await act(async () => {
      startTransition(() => rerender(page("Settings")));
    });
    expect(screen.getByText("Home page")).toBeInTheDocument();
    expect(screen.queryByText("Settings page")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(Number(screen.getByText("Home page").parentElement?.style.opacity)).toBeLessThan(1);
    });
    await act(async () => {
      startTransition(() => rerender(page(latestPage)));
    });

    await waitFor(() => {
      if (latestPage !== "Home") {
        expect(screen.queryByText("Home page")).not.toBeInTheDocument();
      }
      expect(screen.queryByText("Settings page")).not.toBeInTheDocument();
      expect(screen.getAllByText(`${latestPage} page`)).toHaveLength(1);
      expect(screen.getByText(`${latestPage} page`).parentElement).toHaveStyle({ opacity: "1" });
    }, { timeout: 3_000 });

    // An obsolete exit callback must not remove the page after re-entry.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, DURATION.cinematic * 1_000 + 100));
    });
    expect(screen.queryByText("Settings page")).not.toBeInTheDocument();
    expect(screen.getAllByText(`${latestPage} page`)).toHaveLength(1);
    expect(screen.getByText(`${latestPage} page`).parentElement).toHaveStyle({ opacity: "1" });
  });
});
