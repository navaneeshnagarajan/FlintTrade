/**
 * AdminRoute.test.tsx
 *
 * Smoke tests for the /admin dev dashboard.
 * Mocks fetch and react-router-dom to keep tests lightweight.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn();

vi.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
}));

// Mock global fetch — AdminRoute fetches /ft-api/v1/admin/introspect on mount
const mockFetch = vi.fn().mockRejectedValue(new Error("not connected"));
vi.stubGlobal("fetch", mockFetch);

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { widgetCatalog } from "@/layout/widgetFactory";
import AdminRoute, { ADMIN_WIDGET_SHOWCASE } from "../AdminRoute";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
const Wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
);

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AdminRoute", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("not connected")));
  });

  it("renders the admin dashboard heading", () => {
    render(<AdminRoute />, { wrapper: Wrapper });

    expect(screen.getByText("Admin Dashboard")).toBeInTheDocument();
  });

  it("shows all navigation tabs", () => {
    render(<AdminRoute />, { wrapper: Wrapper });

    expect(screen.getByRole("tab", { name: /packages/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /widgets/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /endpoints/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /features/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /absorption/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /dependencies/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /logs/i })).toBeInTheDocument();
  });

  it("shows DEV badge", () => {
    render(<AdminRoute />, { wrapper: Wrapper });

    expect(screen.getByText("DEV")).toBeInTheDocument();
  });

  it("only showcases widget ids the catalogue still carries", () => {
    // This panel used to hand-copy id, name AND category, so it drifted into a
    // third parallel widget list: it advertised the retired `oiprofile` id as
    // live, and named three merged widgets by their pre-merge titles. Names and
    // categories now come from `widgetCatalog`; a retired id would silently
    // drop its row instead, so pin the ids here.
    const catalogIds = new Set(widgetCatalog.map((widget) => widget.id));
    const retired = ADMIN_WIDGET_SHOWCASE
      .map((widget) => widget.id)
      .filter((id) => !catalogIds.has(id));

    expect(retired).toEqual([]);
    // Deriving from the catalogue is pointless if the shortlist empties out.
    expect(ADMIN_WIDGET_SHOWCASE.length).toBeGreaterThan(20);
  });
});
