import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";

const mockSearchDocs = vi.hoisted(() => vi.fn());

// Mock framer-motion for AnimatedTabs
vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: Record<string, unknown>) => {
      const safe = { ...props };
      for (const k of ["initial", "animate", "exit", "variants", "transition", "layoutId"]) delete safe[k];
      return <div {...safe}>{children as React.ReactNode}</div>;
    },
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/services/api", () => ({
  searchSymbol: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/components/DocsSearch/DocsSearch", () => ({
  searchDocs: mockSearchDocs,
}));

vi.mock("jotai", async (importOriginal) => ({
  // Real jotai (marketAtoms calls atom() at module scope, and the FDC3
  // channel atoms load transitively through the palette's intent path)…
  ...(await importOriginal<typeof import("jotai")>()),
  // …with reads stubbed as before: every atom reads null in this suite.
  useAtomValue: vi.fn().mockReturnValue(null),
}));

vi.mock("@/atoms/marketAtoms", async (importOriginal) => ({
  // The real module (the FDC3 red channel aliases selectedSymbolAtom, which
  // the palette's intent path now pulls in transitively)…
  ...(await importOriginal<typeof import("@/atoms/marketAtoms")>()),
  // …with the tick family stubbed as before.
  tickAtomFamily: vi.fn().mockReturnValue({}),
}));

vi.mock("@/stores/aiConversationStore", () => ({
  useAIConversationStore: vi.fn((sel: (s: Record<string, unknown>) => unknown) =>
    sel({ messages: [], isStreaming: false, addMessage: vi.fn() }),
  ),
}));

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: vi.fn((sel: (s: Record<string, unknown>) => unknown) =>
    sel({ setTheme: vi.fn(), setMode: vi.fn(), mode: "dark" }),
  ),
}));

vi.mock("@/layout/widgetFactory", () => ({
  widgetCatalog: [
    { id: "chart", name: "Chart", category: "analysis" },
    { id: "positions", name: "Positions", category: "trading" },
  ],
}));

import CommandPalette from "../CommandPalette";
import { searchSymbol } from "@/services/api";

const wrapper = ({ children }: { children: React.ReactNode }) =>
  createElement(
    QueryClientProvider,
    { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
    children,
  );

function renderPalette(isOpen = true) {
  const onClose = vi.fn();
  const result = render(
    createElement(wrapper, null,
      createElement(CommandPalette, { isOpen, onClose }),
    ),
  );
  return { ...result, onClose };
}

describe("CommandPalette — tabbed", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSearchDocs.mockResolvedValue([]);
    vi.mocked(searchSymbol).mockResolvedValue([]);
  });

  it("renders 4 tabs: Symbols, Commands, Widgets, Ask AI", () => {
    renderPalette();
    expect(screen.getByRole("tab", { name: /symbols/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /commands/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /widgets/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /ask ai/i })).toBeInTheDocument();
  });

  it("defaults to Symbols tab", () => {
    renderPalette();
    expect(screen.getByRole("tab", { name: /symbols/i })).toHaveAttribute("aria-selected", "true");
  });

  it("switches to Commands tab when / is typed", () => {
    renderPalette();
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "/" } });
    expect(screen.getByRole("tab", { name: /commands/i })).toHaveAttribute("aria-selected", "true");
  });

  it("switches to Widgets tab when # is typed", () => {
    renderPalette();
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "#" } });
    expect(screen.getByRole("tab", { name: /widgets/i })).toHaveAttribute("aria-selected", "true");
  });

  it("shows widget results when # routes the query to Widgets", () => {
    renderPalette();
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "#chart" } });

    expect(screen.getByRole("tab", { name: /widgets/i })).toHaveAttribute("aria-selected", "true");
    const visiblePanel = screen.getByRole("tabpanel");
    expect(within(visiblePanel).getByRole("option", { name: /Add Chart/i })).toBeInTheDocument();
    expect(within(visiblePanel).queryByText(/type to search stocks/i)).not.toBeInTheDocument();
  });

  it("switches to AI tab when @ai is typed", () => {
    renderPalette();
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "@ai " } });
    expect(screen.getByRole("tab", { name: /ask ai/i })).toHaveAttribute("aria-selected", "true");
  });

  it("returns null when not open", () => {
    const { container } = renderPalette(false);
    expect(container.innerHTML).toBe("");
  });

  it("closes on Escape key", () => {
    const { onClose } = renderPalette();
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("shows search input with placeholder", () => {
    renderPalette();
    expect(screen.getByPlaceholderText(/search symbols/i)).toBeInTheDocument();
  });

  it("shows footer with keyboard hints", () => {
    renderPalette();
    expect(screen.getByText("Navigate")).toBeInTheDocument();
    expect(screen.getByText("Select")).toBeInTheDocument();
    expect(screen.getByText("Switch tab")).toBeInTheDocument();
    expect(screen.getByText("Close")).toBeInTheDocument();
  });

  it("selects the active command when Enter is pressed", async () => {
    const { onClose } = renderPalette();
    const input = screen.getByRole("combobox");
    let detail: unknown;
    const listener = vi.fn((event: Event) => {
      detail = (event as CustomEvent).detail;
    });
    window.addEventListener("flinttrade:navigate", listener);

    fireEvent.change(input, { target: { value: "/go to settings" } });
    await waitFor(() => {
      expect(screen.getByRole("option", { name: /go to settings/i })).toBeInTheDocument();
    });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(listener).toHaveBeenCalledOnce();
    expect(detail).toEqual({ path: "/settings" });
    expect(onClose).toHaveBeenCalledOnce();

    window.removeEventListener("flinttrade:navigate", listener);
  });

  it("selects the active widget when Enter is pressed", async () => {
    const { onClose } = renderPalette();
    const input = screen.getByRole("combobox");
    let detail: unknown;
    const listener = vi.fn((event: Event) => {
      detail = (event as CustomEvent).detail;
    });
    window.addEventListener("flinttrade:addWidget", listener);

    fireEvent.change(input, { target: { value: "#chart" } });
    await waitFor(() => {
      expect(screen.getByRole("option", { name: /add chart/i })).toBeInTheDocument();
    });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(listener).toHaveBeenCalledOnce();
    expect(detail).toEqual({ widgetId: "chart" });
    expect(onClose).toHaveBeenCalledOnce();

    window.removeEventListener("flinttrade:addWidget", listener);
  });

  it("selects the active docs result when Enter is pressed", async () => {
    const { onClose } = renderPalette();
    const input = screen.getByRole("combobox");
    mockSearchDocs.mockResolvedValue([
      {
        path: "USER_GUIDE.md",
        title: "User Guide",
        snippet: "Workspace setup",
        score: 0.8,
      },
    ]);
    let detail: unknown;
    const listener = vi.fn((event: Event) => {
      detail = (event as CustomEvent).detail;
    });
    window.addEventListener("flinttrade:openDoc", listener);

    fireEvent.change(input, { target: { value: "?user guide" } });
    await waitFor(() => {
      expect(screen.getByRole("option", { name: /user guide/i })).toBeInTheDocument();
    });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(listener).toHaveBeenCalledOnce();
    expect(detail).toEqual({ path: "USER_GUIDE.md" });
    expect(onClose).toHaveBeenCalledOnce();

    window.removeEventListener("flinttrade:openDoc", listener);
  });

  it("opens the active symbol chart when Enter is pressed", async () => {
    const { onClose } = renderPalette();
    const input = screen.getByRole("combobox");
    vi.mocked(searchSymbol).mockResolvedValue([{ symbol: "RELIANCE", exchange: "NSE" }]);
    let detail: unknown;
    const listener = vi.fn((event: Event) => {
      detail = (event as CustomEvent).detail;
    });
    window.addEventListener("flinttrade:addWidget", listener);

    fireEvent.change(input, { target: { value: "RELIANCE" } });
    await waitFor(() => {
      expect(screen.getByRole("option", { name: /reliance/i })).toBeInTheDocument();
    });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(listener).toHaveBeenCalledOnce();
    expect(detail).toEqual({
      widgetId: "chart",
      props: { symbol: "RELIANCE", exchange: "NSE" },
    });
    expect(onClose).toHaveBeenCalledOnce();

    window.removeEventListener("flinttrade:addWidget", listener);
  });
});
