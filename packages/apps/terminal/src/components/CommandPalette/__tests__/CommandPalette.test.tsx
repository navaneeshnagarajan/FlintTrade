import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";

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

vi.mock("jotai", () => ({
  useAtomValue: vi.fn().mockReturnValue(null),
}));

vi.mock("@/atoms/marketAtoms", () => ({
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
  beforeEach(() => vi.clearAllMocks());

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
});
