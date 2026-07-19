/**
 * SkillDraftReview.test.tsx — the AI1 draft-review card inside SkillSection
 * (real TanStack Query; the draft client mocked).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import "@testing-library/jest-dom";

const mockList = vi.fn();
const mockRead = vi.fn();
const mockApprove = vi.fn();
const mockReject = vi.fn();
vi.mock("@/services/ftApi.skillDrafts", () => ({
  listSkillDrafts: () => mockList() as Promise<unknown>,
  readSkillDraft: (name: string) => mockRead(name) as Promise<unknown>,
  approveSkillDraft: (name: string) => mockApprove(name) as Promise<unknown>,
  rejectSkillDraft: (name: string) => mockReject(name) as Promise<unknown>,
}));

// SkillSection's other dependencies (store + tour) — minimal stubs.
vi.mock("@/stores/skillStore", () => {
  const state = {
    globalLevel: "intermediate",
    routeOverrides: {},
    helpPrefs: {},
    metrics: {
      trade: { ordersPlaced: 0, widgetsUsed: 0, daysActive: 0, lastActiveDate: "" },
      invest: { holdingsViewed: 0, sipsCreated: 0, goalsSet: 0 },
      learn: { lessonsCompleted: 0, quizzesPassed: 0, articlesRead: 0 },
      lab: { backtestsRun: 0, strategiesCreated: 0, optimizationsRun: 0 },
      automate: { flowsCreated: 0, alertsSet: 0, strategiesUploaded: 0 },
      ai: { queriesRun: 0, agentsDeployed: 0 },
    },
    getEffectiveLevel: () => "intermediate",
    setGlobalLevel: vi.fn(),
    setRouteOverride: vi.fn(),
    clearRouteOverride: vi.fn(),
    setHelpPref: vi.fn(),
    resetToDefaults: vi.fn(),
  };
  return {
    useSkillStore: (selector?: (s: typeof state) => unknown) =>
      typeof selector === "function" ? selector(state) : state,
  };
});

import { SkillSection } from "../SkillSection";

function Providers({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("SkillDraftReviewSection", () => {
  beforeEach(() => {
    mockList.mockReset();
    mockRead.mockReset();
    mockApprove.mockReset();
    mockReject.mockReset();
    mockList.mockResolvedValue([
      {
        name: "session-lessons-2026-07-19",
        description: "Session lessons from 2026-07-19 (4 trades, 50% win rate)",
        modified_at: 1789000000,
      },
    ]);
  });

  it("lists pending drafts with the approval explainer", async () => {
    render(<SkillSection />, { wrapper: Providers });
    expect(
      await screen.findByText("session-lessons-2026-07-19"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Drafts influence nothing until you approve them/i),
    ).toBeInTheDocument();
  });

  it("views a draft's markdown inline", async () => {
    mockRead.mockResolvedValue({
      name: "session-lessons-2026-07-19",
      content: "---\nstatus: draft\n---\n## Recommendations\n- Wait for the range",
    });
    render(<SkillSection />, { wrapper: Providers });
    await screen.findByText("session-lessons-2026-07-19");
    fireEvent.click(screen.getByRole("button", { name: /^view$/i }));
    expect(await screen.findByText(/Wait for the range/)).toBeInTheDocument();
  });

  it("approves and rejects through the guarded client", async () => {
    mockApprove.mockResolvedValue(undefined);
    mockReject.mockResolvedValue(undefined);
    render(<SkillSection />, { wrapper: Providers });
    await screen.findByText("session-lessons-2026-07-19");

    fireEvent.click(screen.getByRole("button", { name: /^approve$/i }));
    await waitFor(() =>
      expect(mockApprove).toHaveBeenCalledWith("session-lessons-2026-07-19"),
    );
  });

  it("surfaces a guard denial honestly", async () => {
    mockApprove.mockRejectedValue(new Error("operator session required"));
    render(<SkillSection />, { wrapper: Providers });
    await screen.findByText("session-lessons-2026-07-19");
    fireEvent.click(screen.getByRole("button", { name: /^approve$/i }));
    expect(
      await screen.findByText(/operator session required/i),
    ).toBeInTheDocument();
  });
});
