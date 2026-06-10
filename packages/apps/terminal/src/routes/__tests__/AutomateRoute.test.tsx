import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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
vi.mock("@/hooks/useSkillLevel", () => ({
  useSkillLevel: () => "advanced",
}));

vi.mock("@/stores/skillStore", () => ({
  useSkillStore: Object.assign(() => ({}), {
    getState: () => ({ trackAction: vi.fn() }),
  }),
}));

// Mock ftApi calls used by AutomateRoute
vi.mock("@/services/ftApi", () => ({
  getSafetyConfig: vi.fn().mockResolvedValue({ kill_switch_active: false }),
  getRunningStrategies: vi.fn().mockResolvedValue([]),
  getUploadedStrategies: vi.fn().mockResolvedValue([]),
}));

// Mock the section components to avoid deep dependency trees
vi.mock("../automate/FlowsSection", () => ({ default: () => <div data-testid="flows-section">Flows</div> }));
vi.mock("../automate/CronSection", () => ({ default: () => <div data-testid="cron-section">Cron</div> }));
vi.mock("../automate/MonitorsSection", () => ({ default: () => <div data-testid="monitors-section">Monitors</div> }));
vi.mock("../automate/LogsSection", () => ({ default: () => <div data-testid="logs-section">Logs</div> }));
vi.mock("../automate/StrategiesSection", () => ({ default: () => <div data-testid="strategies-section">Strategies</div> }));
vi.mock("../automate/SettingsSection", () => ({ default: () => <div data-testid="settings-section">Settings</div> }));
vi.mock("../automate/WebhooksSection", () => ({ default: () => <div data-testid="webhooks-section">Webhooks</div> }));
vi.mock("../automate/N8nSection", () => ({ default: () => <div data-testid="n8n-section">N8n</div> }));

// Mock the sidebar to render a simple version
vi.mock("../automate/AutomateSidebar", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("../automate/AutomateSidebar");
  return {
    ...actual,
    default: ({ sections, activeSection, onSelect }: {
      sections: Array<{ id: string; label: string }>;
      activeSection: string;
      onSelect: (id: string) => void;
    }) => (
      <nav data-testid="automate-sidebar">
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
    expect(screen.getByText("n8n Bridge")).toBeInTheDocument();
    expect(screen.getByText("Execution Logs")).toBeInTheDocument();
  });

  it("renders the sidebar navigation", () => {
    render(<AutomateRoute />, { wrapper: createWrapper() });
    expect(screen.getByTestId("automate-sidebar")).toBeInTheDocument();
  });
});
