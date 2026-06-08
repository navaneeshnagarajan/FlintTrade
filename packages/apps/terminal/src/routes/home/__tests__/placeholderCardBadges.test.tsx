/**
 * placeholderCardBadges.test — every home Bento card that renders fabricated
 * placeholder data (no live source wired yet) MUST carry a visible Demo/Sample
 * affordance, per the no-mock-data house rule. These cards previously rendered
 * fake world-index prices / sector moves / "NSE" breadth / an AI thesis / SIPs /
 * news headlines indistinguishable from the live cards beside them.
 *
 * BreadthCard is now LIVE-capable (it fetches /ft-api/v1/breadth/current and
 * drops the badge when the backend returns genuine non-sample data), so it is
 * exercised in both its disconnected (sample) and connected (live) states.
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

describe("home placeholder cards carry a Demo/Sample affordance", () => {
  it.each(CARDS)("$name renders a placeholder badge with an explanatory title (disconnected)", ({ node, badgeTestId }) => {
    renderCard(node);
    const badge = screen.getByTestId(badgeTestId);
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute("role", "status");
    expect(badge.getAttribute("title")).toBeTruthy();
  });

  it("BreadthCard (disconnected) labels its fabricated numbers Sample, not live NSE data", () => {
    renderCard(<BreadthCard />);
    expect(screen.queryByText(/NSE ·/)).not.toBeInTheDocument();
    expect(screen.getByText(/Sample ·/)).toBeInTheDocument();
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
      expect(screen.getByTestId("breadth-demo-badge")).toBeInTheDocument();
      expect(screen.getByText(/Sample ·/)).toBeInTheDocument();
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
