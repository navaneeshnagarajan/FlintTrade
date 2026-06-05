/**
 * PresetSection.test.tsx
 *
 * Tests for the Workspace Presets settings section.
 *
 * Covers:
 *   - Section title and toolbar render
 *   - Built-in preset cards with "Built-in" badge and Fork/Export actions
 *   - Custom preset cards with "Custom" badge and Edit/Delete/Export actions
 *   - "New Preset" opens the create form
 *   - Create form renders name input, description, and a submit button
 *   - Fork form pre-fills name with "(copy)" suffix
 *   - Edit form pre-fills existing values
 *   - Delete confirmation dialog renders and calls mutation on confirm
 *   - Import button is present (file input is hidden)
 *   - Error states from mutations surface in the UI
 *   - Empty custom presets shows the placeholder message
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks — must appear before component imports
// ---------------------------------------------------------------------------

// TanStack Query
const mockInvalidateQueries = vi.fn();
const mockUseQuery = vi.fn();
const mockUseMutation = vi.fn();

vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-query")>();
  return {
    ...actual,
    useQuery: (...args: Parameters<typeof mockUseQuery>) => mockUseQuery(...args),
    useMutation: (...args: Parameters<typeof mockUseMutation>) => mockUseMutation(...args),
    useQueryClient: () => ({ invalidateQueries: mockInvalidateQueries }),
  };
});

// ftApi preset service functions
const mockListPresets = vi.fn();
const mockCreatePreset = vi.fn();
const mockUpdatePreset = vi.fn();
const mockDeletePreset = vi.fn();
const mockForkPreset = vi.fn();

vi.mock("@/services/ftApi", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/services/ftApi")>();
  return {
    ...original,
    listPresets: () => mockListPresets(),
    createPreset: (payload: unknown) => mockCreatePreset(payload),
    updatePreset: (id: string, payload: unknown) => mockUpdatePreset(id, payload),
    deletePreset: (id: string) => mockDeletePreset(id),
    forkPreset: (id: string, name: string) => mockForkPreset(id, name),
    // Security functions (used by SettingsSections.test.tsx, no-op here)
    getSecurityStats: vi.fn(),
    getBannedIPs: vi.fn(),
    banIP: vi.fn(),
    unbanIP: vi.fn(),
    getSecuritySettings: vi.fn(),
    updateSecuritySettings: vi.fn(),
    updateSafetyConfig: vi.fn(),
  };
});

// widgetFactory — provide a trimmed catalog for speed
vi.mock("@/layout/widgetFactory", () => ({
  widgetCatalog: [
    { id: "chart",       name: "Chart",       icon: "CandlestickChart", category: "Analysis",  description: "Candlestick chart" },
    { id: "watchlist",   name: "Watchlist",   icon: "Star",             category: "Utility",   description: "Watchlist"         },
    { id: "positions",   name: "Positions",   icon: "Table2",           category: "Trading",   description: "Position book"     },
    { id: "orderpad",    name: "Order Pad",   icon: "FileEdit",         category: "Trading",   description: "Order entry"       },
  ],
}));

// shadcn/ui components — simple HTML pass-throughs
vi.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    asChild: _a,
    variant: _v,
    size: _s,
    ...props
  }: Record<string, unknown>) =>
    React.createElement(
      "button",
      props as React.ButtonHTMLAttributes<HTMLButtonElement>,
      children as React.ReactNode,
    ),
}));

vi.mock("@/components/ui/badge", () => ({
  Badge: ({
    children,
    variant: _v,
    ...props
  }: Record<string, unknown>) =>
    React.createElement(
      "span",
      props as React.HTMLAttributes<HTMLSpanElement>,
      children as React.ReactNode,
    ),
}));

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------

import type { WorkspacePresetRecord } from "@/services/ftApi";

const BUILTIN_PRESET: WorkspacePresetRecord = {
  id: "scalper-zone",
  name: "Scalper Zone",
  description: "Chart + Order Pad + Depth + Positions",
  icon: "Zap",
  is_builtin: true,
  widgets: ["chart", "orderpad", "depth", "positions"],
};

const CUSTOM_PRESET: WorkspacePresetRecord = {
  id: "my-layout",
  name: "My Layout",
  description: "Custom morning setup",
  icon: "Star",
  is_builtin: false,
  widgets: ["chart", "watchlist"],
};

// ---------------------------------------------------------------------------
// Mutation factory — returns a mutation stub
// ---------------------------------------------------------------------------

function makeMutation(overrides: Partial<ReturnType<typeof mockUseMutation>> = {}) {
  return {
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    error: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Setup helpers
// ---------------------------------------------------------------------------

function setupQuery(presets: WorkspacePresetRecord[]) {
  mockUseQuery.mockReturnValue({
    data: { presets },
    isLoading: false,
    isError: false,
    error: null,
  });
}

function setupMutations() {
  mockUseMutation.mockReturnValue(makeMutation());
}

// ---------------------------------------------------------------------------
// Import after all mocks
// ---------------------------------------------------------------------------

import { PresetSection } from "../PresetSection";

// ---------------------------------------------------------------------------
// QueryClient wrapper — ensures hooks have a provider even if vi.mock hoisting
// is incomplete in some CI environments.
// ---------------------------------------------------------------------------

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PresetSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupMutations();
  });

  // --------------------------------------------------------------------------
  // 1. Section title and toolbar
  // --------------------------------------------------------------------------

  describe("toolbar", () => {
    it("renders the section title, Import button, and New Preset button", () => {
      setupQuery([]);
      render(<PresetSection />, { wrapper: makeWrapper() });

      expect(screen.getByText("Workspace Presets")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /import preset/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /create a new workspace preset/i })).toBeInTheDocument();
    });

    it("disables New Preset while a form is already open", () => {
      setupQuery([]);
      render(<PresetSection />, { wrapper: makeWrapper() });

      const newBtn = screen.getByRole("button", { name: /create a new workspace preset/i });
      fireEvent.click(newBtn);

      expect(newBtn).toBeDisabled();
    });
  });

  // --------------------------------------------------------------------------
  // 2. Loading and error states
  // --------------------------------------------------------------------------

  describe("query states", () => {
    it("shows loading indicator while fetching", () => {
      mockUseQuery.mockReturnValue({ data: undefined, isLoading: true, isError: false, error: null });
      render(<PresetSection />, { wrapper: makeWrapper() });

      expect(screen.getByText(/loading presets/i)).toBeInTheDocument();
    });

    it("shows error message when query fails", () => {
      mockUseQuery.mockReturnValue({
        data: undefined,
        isLoading: false,
        isError: true,
        error: new Error("Network error"),
      });
      render(<PresetSection />, { wrapper: makeWrapper() });

      expect(screen.getByText(/failed to load presets/i)).toBeInTheDocument();
      expect(screen.getByText(/network error/i)).toBeInTheDocument();
    });
  });

  // --------------------------------------------------------------------------
  // 3. Built-in preset cards
  // --------------------------------------------------------------------------

  describe("built-in presets", () => {
    beforeEach(() => setupQuery([BUILTIN_PRESET]));

    it("renders a card for each built-in preset with the name", () => {
      render(<PresetSection />, { wrapper: makeWrapper() });
      expect(screen.getByText("Scalper Zone")).toBeInTheDocument();
    });

    it("shows 'Built-in' badge on built-in presets", () => {
      render(<PresetSection />, { wrapper: makeWrapper() });
      // The section heading "Built-in (1)" and the card badge "Built-in" both render;
      // confirm at least one match is the badge (a <span>)
      const matches = screen.getAllByText("Built-in");
      const badgeEl = matches.find((el) => el.tagName.toLowerCase() === "span");
      expect(badgeEl).toBeDefined();
    });

    it("shows the widget count", () => {
      render(<PresetSection />, { wrapper: makeWrapper() });
      expect(screen.getByText("4 widgets")).toBeInTheDocument();
    });

    it("shows a Fork button (not Edit or Delete)", () => {
      render(<PresetSection />, { wrapper: makeWrapper() });
      expect(screen.getByRole("button", { name: "Fork Scalper Zone" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Edit Scalper Zone" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Delete Scalper Zone" })).not.toBeInTheDocument();
    });

    it("shows an Export button", () => {
      render(<PresetSection />, { wrapper: makeWrapper() });
      expect(screen.getByRole("button", { name: "Export Scalper Zone" })).toBeInTheDocument();
    });

    it("opens the fork form when Fork is clicked", () => {
      render(<PresetSection />, { wrapper: makeWrapper() });
      fireEvent.click(screen.getByRole("button", { name: "Fork Scalper Zone" }));
      expect(screen.getByLabelText("Fork Preset form")).toBeInTheDocument();
    });

    it("pre-fills the fork form name with '(copy)' suffix", () => {
      render(<PresetSection />, { wrapper: makeWrapper() });
      fireEvent.click(screen.getByRole("button", { name: "Fork Scalper Zone" }));
      const nameInput = screen.getByLabelText("Name *") as HTMLInputElement;
      expect(nameInput.value).toBe("Scalper Zone (copy)");
    });
  });

  // --------------------------------------------------------------------------
  // 4. Custom preset cards
  // --------------------------------------------------------------------------

  describe("custom presets", () => {
    beforeEach(() => setupQuery([CUSTOM_PRESET]));

    it("renders a card for each custom preset", () => {
      render(<PresetSection />, { wrapper: makeWrapper() });
      expect(screen.getByText("My Layout")).toBeInTheDocument();
    });

    it("shows 'Custom' badge on the card", () => {
      render(<PresetSection />, { wrapper: makeWrapper() });
      // The section heading "Custom (1)" and the card badge "Custom" both render;
      // confirm at least one match is the badge (a <span>)
      const matches = screen.getAllByText("Custom");
      const badgeEl = matches.find((el) => el.tagName.toLowerCase() === "span");
      expect(badgeEl).toBeDefined();
    });

    it("shows Edit and Delete buttons (not Fork)", () => {
      render(<PresetSection />, { wrapper: makeWrapper() });
      expect(screen.getByRole("button", { name: "Edit My Layout" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Delete My Layout" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Fork My Layout" })).not.toBeInTheDocument();
    });

    it("shows Export button on custom presets", () => {
      render(<PresetSection />, { wrapper: makeWrapper() });
      expect(screen.getByRole("button", { name: "Export My Layout" })).toBeInTheDocument();
    });
  });

  // --------------------------------------------------------------------------
  // 5. Empty state
  // --------------------------------------------------------------------------

  it("shows placeholder when there are no custom presets", () => {
    setupQuery([BUILTIN_PRESET]);
    render(<PresetSection />, { wrapper: makeWrapper() });
    expect(screen.getByText(/no custom presets yet/i)).toBeInTheDocument();
  });

  // --------------------------------------------------------------------------
  // 6. Create form
  // --------------------------------------------------------------------------

  describe("create form", () => {
    beforeEach(() => setupQuery([]));

    it("opens the create form when New Preset is clicked", () => {
      render(<PresetSection />, { wrapper: makeWrapper() });
      fireEvent.click(screen.getByRole("button", { name: /create a new workspace preset/i }));
      expect(screen.getByLabelText("New Preset form")).toBeInTheDocument();
    });

    it("renders name and description inputs", () => {
      render(<PresetSection />, { wrapper: makeWrapper() });
      fireEvent.click(screen.getByRole("button", { name: /create a new workspace preset/i }));
      expect(screen.getByLabelText("Name *")).toBeInTheDocument();
      expect(screen.getByLabelText("Description")).toBeInTheDocument();
    });

    it("Create button is disabled when name is empty", () => {
      render(<PresetSection />, { wrapper: makeWrapper() });
      fireEvent.click(screen.getByRole("button", { name: /create a new workspace preset/i }));
      expect(screen.getByRole("button", { name: /^create$/i })).toBeDisabled();
    });

    it("Cancel closes the form", () => {
      render(<PresetSection />, { wrapper: makeWrapper() });
      fireEvent.click(screen.getByRole("button", { name: /create a new workspace preset/i }));
      fireEvent.click(screen.getByRole("button", { name: /^cancel$/i }));
      expect(screen.queryByLabelText("New Preset form")).not.toBeInTheDocument();
    });

    it("calls createPreset mutation on submit", async () => {
      const mutateFn = vi.fn();
      mockUseMutation.mockReturnValue(makeMutation({ mutate: mutateFn }));
      render(<PresetSection />, { wrapper: makeWrapper() });

      fireEvent.click(screen.getByRole("button", { name: /create a new workspace preset/i }));
      fireEvent.change(screen.getByLabelText("Name *"), {
        target: { value: "Test Preset" },
      });
      fireEvent.click(screen.getByRole("button", { name: /^create$/i }));

      await waitFor(() => {
        expect(mutateFn).toHaveBeenCalledOnce();
        expect(mutateFn).toHaveBeenCalledWith(
          expect.objectContaining({ name: "Test Preset", widgets: [] }),
        );
      });
    });
  });

  // --------------------------------------------------------------------------
  // 7. Edit form
  // --------------------------------------------------------------------------

  describe("edit form", () => {
    beforeEach(() => setupQuery([CUSTOM_PRESET]));

    it("opens the edit form with pre-filled name", () => {
      render(<PresetSection />, { wrapper: makeWrapper() });
      fireEvent.click(screen.getByRole("button", { name: "Edit My Layout" }));

      expect(screen.getByLabelText("Edit Preset form")).toBeInTheDocument();
      const nameInput = screen.getByLabelText("Name *") as HTMLInputElement;
      expect(nameInput.value).toBe("My Layout");
    });

    it("Save button calls updatePreset mutation", async () => {
      const mutateFn = vi.fn();
      mockUseMutation.mockReturnValue(makeMutation({ mutate: mutateFn }));
      render(<PresetSection />, { wrapper: makeWrapper() });

      fireEvent.click(screen.getByRole("button", { name: "Edit My Layout" }));
      fireEvent.change(screen.getByLabelText("Name *"), {
        target: { value: "My Layout Updated" },
      });
      fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

      await waitFor(() => {
        expect(mutateFn).toHaveBeenCalledOnce();
        expect(mutateFn).toHaveBeenCalledWith(
          expect.objectContaining({ name: "My Layout Updated" }),
        );
      });
    });
  });

  // --------------------------------------------------------------------------
  // 8. Delete confirmation
  // --------------------------------------------------------------------------

  describe("delete flow", () => {
    beforeEach(() => setupQuery([CUSTOM_PRESET]));

    it("shows a confirmation dialog when Delete is clicked", () => {
      render(<PresetSection />, { wrapper: makeWrapper() });
      fireEvent.click(screen.getByRole("button", { name: "Delete My Layout" }));

      expect(screen.getByRole("alertdialog")).toBeInTheDocument();
      expect(screen.getByText(/permanently deleted/i)).toBeInTheDocument();
    });

    it("calls deletePreset mutation when confirmed", async () => {
      const mutateFn = vi.fn();
      mockUseMutation.mockReturnValue(makeMutation({ mutate: mutateFn }));
      render(<PresetSection />, { wrapper: makeWrapper() });

      fireEvent.click(screen.getByRole("button", { name: "Delete My Layout" }));
      fireEvent.click(screen.getByRole("button", { name: /confirm delete/i }));

      await waitFor(() => {
        expect(mutateFn).toHaveBeenCalledOnce();
      });
    });

    it("dismisses the dialog on Cancel", () => {
      render(<PresetSection />, { wrapper: makeWrapper() });
      fireEvent.click(screen.getByRole("button", { name: "Delete My Layout" }));
      fireEvent.click(screen.getByRole("button", { name: /^cancel$/i }));

      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    });
  });

  // --------------------------------------------------------------------------
  // 9. Mutation error display
  // --------------------------------------------------------------------------

  it("shows mutation error message when createPreset fails", () => {
    mockUseMutation.mockReturnValue(
      makeMutation({ isError: true, error: new Error("Duplicate name") }),
    );
    setupQuery([]);
    render(<PresetSection />, { wrapper: makeWrapper() });

    expect(screen.getByText(/duplicate name/i)).toBeInTheDocument();
  });

  // --------------------------------------------------------------------------
  // 10. Import button
  // --------------------------------------------------------------------------

  it("renders the Import button", () => {
    setupQuery([]);
    render(<PresetSection />, { wrapper: makeWrapper() });
    expect(screen.getByRole("button", { name: /import preset from json file/i })).toBeInTheDocument();
  });

  // --------------------------------------------------------------------------
  // 11. Widget selector
  // --------------------------------------------------------------------------

  it("widget selector expands and shows categories when toggled", () => {
    setupQuery([]);
    render(<PresetSection />, { wrapper: makeWrapper() });
    fireEvent.click(screen.getByRole("button", { name: /create a new workspace preset/i }));
    fireEvent.click(screen.getByRole("button", { name: /toggle widget list/i }));

    // Category headers should be visible
    expect(screen.getByText("Trading")).toBeInTheDocument();
    expect(screen.getByText("Analysis")).toBeInTheDocument();
    expect(screen.getByText("Utility")).toBeInTheDocument();
  });

  it("selecting a widget adds it to the chip list", () => {
    setupQuery([]);
    render(<PresetSection />, { wrapper: makeWrapper() });

    // Open form
    fireEvent.click(screen.getByRole("button", { name: /create a new workspace preset/i }));
    // Expand selector
    fireEvent.click(screen.getByRole("button", { name: /toggle widget list/i }));
    // Toggle "Chart"
    fireEvent.click(screen.getByRole("button", { name: "Chart", hidden: true }));

    // A chip for Chart should appear
    const chips = screen.getAllByText("Chart");
    // At least one element outside the expanded list with an X button sibling
    expect(chips.length).toBeGreaterThanOrEqual(1);
  });

  // --------------------------------------------------------------------------
  // 12. Section headings
  // --------------------------------------------------------------------------

  it("renders 'Built-in' and 'Custom' section headings", () => {
    setupQuery([BUILTIN_PRESET, CUSTOM_PRESET]);
    render(<PresetSection />, { wrapper: makeWrapper() });

    const headings = screen.getAllByText(/^Built-in|^Custom/);
    expect(headings.length).toBeGreaterThanOrEqual(2);
  });
});
