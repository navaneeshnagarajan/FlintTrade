/**
 * MarketOverviewWidget.test — shell, tab identity and deep-linking.
 *
 * The seven retired widget ids resolve into this widget with a `tab` (and
 * sometimes `view`) param; these tests pin that every retired id's params
 * land on the tab that reproduces its presentation, that unknown params
 * fail safe to Breadth, and that tab choices persist into the panel params.
 *
 * Tab bodies are mocked — their behaviour has its own co-located suites.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("../tabs/BreadthTab", () => ({ default: () => <div data-testid="tab-breadth" /> }));
vi.mock("../tabs/SectorsTab", () => ({
  default: ({ initialView }: { initialView?: string }) => (
    <div data-testid="tab-sectors" data-view={initialView} />
  ),
}));
vi.mock("../tabs/RotationTab", () => ({
  default: ({ initialView }: { initialView?: string }) => (
    <div data-testid="tab-rotation" data-view={initialView} />
  ),
}));
vi.mock("../tabs/FlowsTab", () => ({ default: () => <div data-testid="tab-flows" /> }));
vi.mock("../tabs/IndicesTab", () => ({ default: () => <div data-testid="tab-indices" /> }));
vi.mock("../tabs/ContributionTab", () => ({ default: () => <div data-testid="tab-contribution" /> }));

import MarketOverviewWidget, {
  resolveMarketOverviewTab,
  resolveRotationView,
  resolveSectorView,
} from "../MarketOverviewWidget";

function renderWidget(params?: Record<string, unknown>, apiOverrides?: { updateParameters?: ReturnType<typeof vi.fn> }) {
  const props = makeWidgetPanelProps<Record<string, unknown>>({ params: params ?? {} });
  const api = apiOverrides
    ? ({ ...props.api, ...apiOverrides } as typeof props.api)
    : props.api;
  return render(<MarketOverviewWidget {...props} api={api} />);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("MarketOverviewWidget shell", () => {
  it("renders the header and all six tab triggers", () => {
    renderWidget();
    expect(screen.getByText("Market Overview")).toBeInTheDocument();
    for (const label of ["Breadth", "Sectors", "Rotation", "Flows", "Indices", "Contribution"]) {
      expect(screen.getByRole("tab", { name: new RegExp(label, "i") })).toBeInTheDocument();
    }
  });

  it("opens on the Breadth tab by default", () => {
    renderWidget();
    expect(screen.getByTestId("tab-breadth")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Breadth/i })).toHaveAttribute("aria-selected", "true");
  });

  it("persists a tab change into the panel params", async () => {
    const updateParameters = vi.fn();
    renderWidget({}, { updateParameters });
    await userEvent.click(screen.getByRole("tab", { name: /Flows/i }));
    expect(updateParameters).toHaveBeenCalledWith({ tab: "flows" });
    expect(screen.getByTestId("tab-flows")).toBeInTheDocument();
  });
});

describe("retired-id deep links", () => {
  // One case per retired widget id: the params its RETIRED_WIDGET_IDS entry
  // carries must open the tab (and view) that reproduces its presentation.
  const CASES: Array<{
    retiredId: string;
    params: Record<string, unknown>;
    tab: string;
    testId: string;
    view?: string;
  }> = [
    { retiredId: "marketbreadth", params: { tab: "breadth" }, tab: "Breadth", testId: "tab-breadth" },
    { retiredId: "marketsummary", params: { tab: "breadth" }, tab: "Breadth", testId: "tab-breadth" },
    { retiredId: "sectormap", params: { tab: "sectors" }, tab: "Sectors", testId: "tab-sectors", view: "treemap" },
    { retiredId: "sectorperformance", params: { tab: "sectors", view: "bars" }, tab: "Sectors", testId: "tab-sectors", view: "bars" },
    { retiredId: "globalindices", params: { tab: "indices" }, tab: "Indices", testId: "tab-indices" },
    { retiredId: "fiilongshort", params: { tab: "flows" }, tab: "Flows", testId: "tab-flows" },
    { retiredId: "indexcontribution", params: { tab: "contribution" }, tab: "Contribution", testId: "tab-contribution" },
  ];

  for (const { retiredId, params, tab, testId, view } of CASES) {
    it(`opens the ${tab} tab for a saved ${retiredId} panel`, () => {
      renderWidget(params);
      expect(screen.getByRole("tab", { name: new RegExp(tab, "i") })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      const body = screen.getByTestId(testId);
      expect(body).toBeInTheDocument();
      if (view) {
        expect(body).toHaveAttribute("data-view", view);
      }
    });
  }

  it("falls back to Breadth for unknown tab params instead of blanking the panel", () => {
    renderWidget({ tab: "does-not-exist" });
    expect(screen.getByTestId("tab-breadth")).toBeInTheDocument();
  });
});

describe("param resolvers", () => {
  it("resolves every known tab and rejects everything else", () => {
    for (const tab of ["breadth", "sectors", "rotation", "flows", "indices", "contribution"]) {
      expect(resolveMarketOverviewTab(tab)).toBe(tab);
    }
    expect(resolveMarketOverviewTab(undefined)).toBe("breadth");
    expect(resolveMarketOverviewTab(42)).toBe("breadth");
    expect(resolveMarketOverviewTab("map")).toBe("breadth");
  });

  it("resolves sector views with a treemap default", () => {
    for (const view of ["treemap", "grid", "table", "bars"]) {
      expect(resolveSectorView(view)).toBe(view);
    }
    expect(resolveSectorView(undefined)).toBe("treemap");
    expect(resolveSectorView("rrg")).toBe("treemap");
  });

  it("resolves rotation views with a sectors default", () => {
    expect(resolveRotationView("portfolio")).toBe("portfolio");
    expect(resolveRotationView(undefined)).toBe("sectors");
    expect(resolveRotationView("bars")).toBe("sectors");
  });
});
