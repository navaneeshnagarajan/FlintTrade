/**
 * placeholderCardBadges.test — home Bento cards that still render fabricated
 * numbers stay quiet. The Mode honesty bar owns the Explore disclaimer, so
 * these cards no longer carry a per-card Sample chip.
 *
 * BreadthCard is LIVE-capable (it fetches /ft-api/v1/breadth/current and
 * labels the footer NSE only for genuine non-sample data).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@testing-library/jest-dom";

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { GlobalCard } from "../GlobalCard";
import { SectorCard } from "../SectorCard";
import { BreadthCard } from "../BreadthCard";
import { AIPulseCard } from "../AIPulseCard";
import { SIPCard } from "../SIPCard";
import { NewsCard } from "../NewsCard";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

function renderCard(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const CARDS: Array<{ name: string; node: React.ReactNode; badgeTestId: string }> = [
  { name: "GlobalCard", node: <GlobalCard />, badgeTestId: "global-demo-badge" },
  { name: "SectorCard", node: <SectorCard />, badgeTestId: "sector-demo-badge" },
  { name: "BreadthCard", node: <BreadthCard />, badgeTestId: "breadth-demo-badge" },
  { name: "AIPulseCard", node: <AIPulseCard />, badgeTestId: "ai-pulse-demo-badge" },
  { name: "SIPCard", node: <SIPCard />, badgeTestId: "sip-demo-badge" },
  { name: "NewsCard", node: <NewsCard />, badgeTestId: "news-demo-badge" },
];

beforeEach(() => {
  vi.clearAllMocks();
  mockConnected.mockReturnValue(false);
});

describe("home placeholder cards stay quiet — the Mode honesty bar owns Explore", () => {
  it.each(CARDS)("$name does not render a per-card Sample badge", ({ node, badgeTestId }) => {
      renderCard(node);
      expect(screen.queryByTestId(badgeTestId)).not.toBeInTheDocument();
    });

  it("BreadthCard (disconnected) shows the placeholder totals without a Sample chip or live NSE label", () => {
    renderCard(<BreadthCard />);
    expect(screen.queryByText(/NSE ·/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Sample ·/)).not.toBeInTheDocument();
    expect(screen.getByText("1,320")).toBeInTheDocument();
  });

  it("BreadthCard flips to live NSE breadth (no Demo badge) when the backend returns non-sample data", async () => {
    mockConnected.mockReturnValue(true);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        status: "success",
        is_sample_data: false,
        data: { advances: 1111, declines: 999, unchanged: 111 },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    try {
      renderCard(<BreadthCard />);
      await waitFor(() => expect(screen.getByText(/NSE ·/)).toBeInTheDocument());
      expect(screen.queryByTestId("breadth-demo-badge")).not.toBeInTheDocument();
      expect(screen.getByText("1,111")).toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("BreadthCard stays on sample+badge when connected but the backend serves its own sample fallback", async () => {
    mockConnected.mockReturnValue(true);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        status: "success",
        is_sample_data: true,
        data: { advances: 5, declines: 5, unchanged: 5 },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    try {
      renderCard(<BreadthCard />);
      await waitFor(() => expect(fetchMock).toHaveBeenCalled());
      expect(screen.queryByTestId("breadth-demo-badge")).not.toBeInTheDocument();
      expect(screen.queryByText(/Sample ·/)).not.toBeInTheDocument();
      expect(screen.queryByText(/NSE ·/)).not.toBeInTheDocument();
      expect(screen.getByText("1,320")).toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("AIPulseCard no longer fabricates a specific live trade level or FII claim", () => {
    renderCard(<AIPulseCard />);
    expect(screen.queryByText(/22,500/)).not.toBeInTheDocument();
    expect(screen.queryByText(/FII net flows are neutral/i)).not.toBeInTheDocument();
  });
});
