/**
 * placeholderCardBadges.test — every home Bento card that renders fabricated
 * placeholder data (no live source wired yet) MUST carry a visible Demo/Sample
 * affordance, per the no-mock-data house rule. These cards previously rendered
 * fake world-index prices / sector moves / "NSE" breadth / an AI thesis / SIPs /
 * news headlines indistinguishable from the live cards beside them.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

import { GlobalCard } from "../GlobalCard";
import { SectorCard } from "../SectorCard";
import { BreadthCard } from "../BreadthCard";
import { AIPulseCard } from "../AIPulseCard";
import { SIPCard } from "../SIPCard";
import { NewsCard } from "../NewsCard";

const CARDS: Array<{ name: string; Card: () => React.JSX.Element; badgeTestId: string }> = [
  { name: "GlobalCard", Card: GlobalCard, badgeTestId: "global-demo-badge" },
  { name: "SectorCard", Card: SectorCard, badgeTestId: "sector-demo-badge" },
  { name: "BreadthCard", Card: BreadthCard, badgeTestId: "breadth-demo-badge" },
  { name: "AIPulseCard", Card: AIPulseCard, badgeTestId: "ai-pulse-demo-badge" },
  { name: "SIPCard", Card: SIPCard, badgeTestId: "sip-demo-badge" },
  { name: "NewsCard", Card: NewsCard, badgeTestId: "news-demo-badge" },
];

describe("home placeholder cards carry a Demo/Sample affordance", () => {
  it.each(CARDS)("$name renders a placeholder badge with an explanatory title", ({ Card, badgeTestId }) => {
    render(<Card />);
    const badge = screen.getByTestId(badgeTestId);
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute("role", "status");
    expect(badge.getAttribute("title")).toBeTruthy();
  });

  it("BreadthCard no longer claims its fabricated numbers are live NSE data", () => {
    render(<BreadthCard />);
    // The "NSE · total" footer (which presented invented numbers as live NSE
    // breadth) is replaced with a neutral "Sample" provenance.
    expect(screen.queryByText(/NSE ·/)).not.toBeInTheDocument();
    expect(screen.getByText(/Sample ·/)).toBeInTheDocument();
  });

  it("AIPulseCard no longer fabricates a specific live trade level or FII claim", () => {
    render(<AIPulseCard />);
    expect(screen.queryByText(/22,500/)).not.toBeInTheDocument();
    expect(screen.queryByText(/FII net flows are neutral/i)).not.toBeInTheDocument();
  });
});
