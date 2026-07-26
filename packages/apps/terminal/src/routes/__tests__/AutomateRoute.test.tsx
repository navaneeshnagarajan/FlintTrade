import { beforeEach, describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

// Mock framer-motion to avoid animation issues in tests
vi.mock("framer-motion", () => ({
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  motion: {
    div: ({ children, ...props }: Record<string, unknown>) => (
      <div {...props}>{children as React.ReactNode}</div>
    ),
  },
}));

vi.mock("@/lib/motion", () => ({
  motionConfig: {
    prefersReducedMotion: () => true,
    transitions: { tab: { duration: 0 } },
  },
  EASE_ENTER: [0.22, 1, 0.36, 1],
  EASE_EXIT: [0.0, 0.0, 0.58, 1.0],
  EASE_MOVE: [0.0, 0.0, 0.58, 1.0],
  DURATION: { fast: 0.15, normal: 0.3, slow: 0.5 },
}));

vi.mock("@/components/help/SpotlightTour", () => ({
  SpotlightTour: () => null,
}));

vi.mock("@/lib/tourDefinitions", () => ({
  TOUR_DEFINITIONS: {},
}));

// Mock hooks that depend on stores
const mockSkill = vi.hoisted(() => ({ level: "advanced" }));

vi.mock("@/hooks/useSkillLevel", () => ({
  useSkillLevel: () => mockSkill.level,
}));

vi.mock("@/stores/skillStore", () => ({
  useSkillStore: Object.assign(() => ({}), {
    getState: () => ({ trackAction: vi.fn() }),
  }),
}));

// Mock ftApi calls used by AutomateRoute
const mockGetSafetyConfig = vi.hoisted(() => vi.fn());
const mockGetRunningStrategies = vi.hoisted(() => vi.fn());
const mockGetUploadedStrategies = vi.hoisted(() => vi.fn());

vi.mock("@/services/ftApi", () => ({
  getSafetyConfig: () => mockGetSafetyConfig(),
  getRunningStrategies: () => mockGetRunningStrategies(),
  getUploadedStrategies: () => mockGetUploadedStrategies(),
}));

// Mock the section components to avoid deep dependency trees
vi.mock("../automate/FlowsSection", () => ({ default: () => <div data-testid="flows-section">Flows</div> }));
vi.mock("../automate/CronSection", () => ({ default: () => <div data-testid="cron-section">Cron</div> }));
vi.mock("../automate/MonitorsSection", () => ({ default: () => <div data-testid="monitors-section">Monitors</div> }));
vi.mock("../automate/LogsSection", () => ({ default: () => <div data-testid="logs-section">Logs</div> }));
vi.mock("../automate/StrategiesSection", () => ({ default: () => <div data-testid="strategies-section">Strategies</div> }));
vi.mock("../automate/SettingsSection", () => ({ default: () => <div data-testid="settings-section">Settings</div> }));
vi.mock("../automate/WebhooksSection", () => ({ default: () => <div data-testid="webhooks-section">Webhooks</div> }));

// Mock the sidebar to render a simple version
vi.mock("../automate/AutomateSidebar", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("../automate/AutomateSidebar");
  return {
    ...actual,
    default: ({ sections, activeSection, onSelect, runningCount, uploadedRunningCount }: {
      sections: Array<{ id: string; label: string }>;
      activeSection: string;
      onSelect: (id: string) => void;
      runningCount: number;
      uploadedRunningCount: number;
    }) => (
      <nav data-testid="automate-sidebar">
        <span data-testid="registered-running-count">{runningCount}</span>
        <span data-testid="uploaded-running-count">{uploadedRunningCount}</span>
        {sections.map((s) => (
          <button
            key={s.id}
            role="tab"
            aria-selected={activeSection === s.id}
            onClick={() => onSelect(s.id)}
          >
            {s.label}
          </button>
        ))}
      </nav>
    ),
  };
});

import AutomateRoute from "../AutomateRoute";

function createWrapper() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
    },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={qc}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  };
}

describe("AutomateRoute", () => {
  beforeEach(() => {
    mockSkill.level = "advanced";
    mockGetSafetyConfig.mockReset().mockResolvedValue({ kill_switch_active: false });
    mockGetRunningStrategies.mockReset().mockResolvedValue([]);
    mockGetUploadedStrategies.mockReset().mockResolvedValue([]);
  });

  it("renders the Automation Hub heading", () => {
    render(<AutomateRoute />, { wrapper: createWrapper() });
    expect(screen.getByText("Automation Hub")).toBeInTheDocument();
  });

  it("has section tabs for all sections at advanced level", () => {
    render(<AutomateRoute />, { wrapper: createWrapper() });
    expect(screen.getByText("Flow Builder")).toBeInTheDocument();
    expect(screen.getByText("Schedules")).toBeInTheDocument();
    expect(screen.getByText("Monitors")).toBeInTheDocument();
    expect(screen.getByText("Strategies")).toBeInTheDocument();
    expect(screen.getByText("Webhooks")).toBeInTheDocument();
    expect(screen.getByText("Execution Logs")).toBeInTheDocument();
  });

  it("renders the sidebar navigation", () => {
    render(<AutomateRoute />, { wrapper: createWrapper() });
    expect(screen.getByTestId("automate-sidebar")).toBeInTheDocument();
  });

  it("keeps emergency settings reachable at intermediate level", () => {
    mockSkill.level = "intermediate";
    render(<AutomateRoute />, { wrapper: createWrapper() });

    const settingsTab = screen.getByRole("tab", { name: "Automation Settings" });
    expect(settingsTab).toBeInTheDocument();
    fireEvent.click(settingsTab);
    expect(screen.getByTestId("settings-section")).toBeInTheDocument();
  });

  it("counts non-empty normalised strategy payloads without unsafe status access", async () => {
    mockGetRunningStrategies.mockResolvedValue([
      {
        name: "ema-crossover",
        symbol: "—",
        exchange: "NSE",
        status: "running",
        tick_count: 42,
        started_at: "",
      },
    ]);
    mockGetUploadedStrategies.mockResolvedValue([
      {
        id: "mean-reversion",
        name: "Mean Reversion",
        filename: "mean-reversion.py",
        status: "running",
        uploaded_at: "",
        started_at: null,
        error_message: null,
      },
    ]);

    render(<AutomateRoute />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByTestId("registered-running-count")).toHaveTextContent("1");
      expect(screen.getByTestId("uploaded-running-count")).toHaveTextContent("1");
    });
  });
});
