/**
 * QuickAccessPanel.test.tsx
 *
 * Tests for the QuickAccessPanel glass morphism settings dropdown.
 * Verifies ARIA roles, keyboard navigation, store integration, and close behaviour.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import QuickAccessPanel from "../QuickAccessPanel";

// ---------------------------------------------------------------------------
// Mock framer-motion — avoids JSDOM animation issues
// ---------------------------------------------------------------------------
vi.mock("framer-motion", () => ({
  motion: {
    div: ({
      children,
      onKeyDown,
      ...props
    }: React.HTMLAttributes<HTMLDivElement> & { onKeyDown?: (e: React.KeyboardEvent<HTMLDivElement>) => void }) => (
      <div {...props} onKeyDown={onKeyDown}>
        {children}
      </div>
    ),
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// ---------------------------------------------------------------------------
// Mock react-router-dom
// ---------------------------------------------------------------------------
const mockNavigate = vi.fn();
vi.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
}));

// ---------------------------------------------------------------------------
// Mock stores
// ---------------------------------------------------------------------------
vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: vi.fn((selector: (s: unknown) => unknown) =>
    selector({ status: "connected" }),
  ),
}));

vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: vi.fn((selector: (s: unknown) => unknown) =>
    selector({
      density: "compact",
      setDensity: vi.fn(),
      sandboxMode: false,
      setSandboxMode: vi.fn(),
    }),
  ),
}));

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: vi.fn((selector: (s: unknown) => unknown) =>
    selector({
      activeThemeId: "midnight",
      setTheme: vi.fn(),
      // mode/setMode intentionally absent — tests the Phase B fallback
    }),
  ),
}));

// ---------------------------------------------------------------------------
// Silence matchMedia (JSDOM does not implement it)
// ---------------------------------------------------------------------------
beforeEach(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  });
  mockNavigate.mockClear();
});

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------
function renderPanel(onClose = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <QuickAccessPanel onClose={onClose} />
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("QuickAccessPanel", () => {
  it("renders with dialog role and correct aria-label", () => {
    renderPanel();
    const dialog = screen.getByRole("dialog", { name: /quick settings/i });
    expect(dialog).toBeInTheDocument();
  });

  it("shows connection status text when connected", () => {
    renderPanel();
    expect(screen.getByText("Connected")).toBeInTheDocument();
  });

  it("has theme radiogroup with 6 radio buttons", () => {
    renderPanel();
    const group = screen.getByRole("radiogroup", { name: /theme/i });
    expect(group).toBeInTheDocument();
    const themeRadios = group.querySelectorAll("[role='radio']");
    expect(themeRadios).toHaveLength(6);
  });

  it("has density radiogroup with compact and comfortable options", () => {
    renderPanel();
    const densityGroup = screen.getByRole("radiogroup", { name: /density/i });
    expect(densityGroup).toBeInTheDocument();
    const options = densityGroup.querySelectorAll("[role='radio']");
    expect(options).toHaveLength(2);
    expect(densityGroup.textContent).toContain("compact");
    expect(densityGroup.textContent).toContain("comfortable");
  });

  it("closes on Escape key", () => {
    const onClose = vi.fn();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <QuickAccessPanel onClose={onClose} />
      </QueryClientProvider>,
    );
    const dialog = container.querySelector("[role='dialog']") as HTMLElement;
    expect(dialog).not.toBeNull();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('has "Open Full Settings" button', () => {
    renderPanel();
    const btn = screen.getByRole("button", { name: /open full settings/i });
    expect(btn).toBeInTheDocument();
  });

  it('navigates to /settings when "Open Full Settings" is clicked', () => {
    const onClose = vi.fn();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <QuickAccessPanel onClose={onClose} />
      </QueryClientProvider>,
    );
    const btn = screen.getByRole("button", { name: /open full settings/i });
    fireEvent.click(btn);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(mockNavigate).toHaveBeenCalledWith("/settings");
  });

  it("calls onClose when close button is clicked", () => {
    const onClose = vi.fn();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <QuickAccessPanel onClose={onClose} />
      </QueryClientProvider>,
    );
    const closeBtn = screen.getByRole("button", { name: /close quick settings/i });
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("theme dots have correct aria-label attributes", () => {
    renderPanel();
    const expectedLabels = [
      "Graphite",
      "Midnight",
      "Light",
      "Arctic Frost",
      "Monochrome",
      "Solarized Dark",
    ];
    for (const label of expectedLabels) {
      expect(screen.getByRole("radio", { name: label })).toBeInTheDocument();
    }
  });
});
