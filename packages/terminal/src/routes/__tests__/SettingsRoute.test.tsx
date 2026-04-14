/**
 * SettingsRoute.test.tsx
 *
 * Smoke tests for the /settings full-page settings route.
 * Mocks stores, hooks, settings sections, and CinematicLayout.
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

vi.mock("@/components/brand/Logo", () => ({
  LogoIcon: ({ size }: { size: number }) => (
    <svg data-testid="logo-icon" width={size} height={size} />
  ),
}));

vi.mock("@/components/layout/CinematicLayout", () => ({
  CinematicLayout: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/tools/Settings/shared", () => ({
  InlineToast: () => null,
}));

// Mock all section components to simple stubs
vi.mock("@/tools/Settings/GeneralSection", () => ({
  GeneralSection: () => <div data-testid="general-section">General</div>,
}));
vi.mock("@/tools/Settings/AppearanceSection", () => ({
  AppearanceSection: () => <div data-testid="appearance-section">Appearance</div>,
}));
vi.mock("@/tools/Settings/ConnectionSection", () => ({
  ConnectionSection: () => <div data-testid="connection-section">Connection</div>,
}));
vi.mock("@/tools/Settings/TradingSection", () => ({
  TradingSection: () => <div data-testid="trading-section">Trading</div>,
}));
vi.mock("@/tools/Settings/RiskSection", () => ({
  RiskSection: () => <div data-testid="risk-section">Risk</div>,
}));
vi.mock("@/tools/Settings/KeyboardSection", () => ({
  KeyboardSection: () => <div data-testid="keyboard-section">Keyboard</div>,
}));
vi.mock("@/tools/Settings/LLMSection", () => ({
  LLMSection: () => <div data-testid="llm-section">LLM</div>,
}));
vi.mock("@/tools/Settings/TelegramSection", () => ({
  TelegramSection: () => <div data-testid="telegram-section">Telegram</div>,
}));
vi.mock("@/tools/Settings/DataSection", () => ({
  DataSection: () => <div data-testid="data-section">Data</div>,
}));
vi.mock("@/tools/Settings/AboutSection", () => ({
  AboutSection: () => <div data-testid="about-section">About</div>,
}));
vi.mock("@/tools/Settings/LeverageSection", () => ({
  LeverageSection: () => <div data-testid="leverage-section">Leverage</div>,
}));
vi.mock("@/tools/Settings/PracticeSection", () => ({
  PracticeSection: () => <div data-testid="practice-section">Practice</div>,
}));
vi.mock("@/tools/Settings/SecuritySection", () => ({
  SecuritySection: () => <div data-testid="security-section">Security</div>,
}));
vi.mock("@/tools/Settings/MonitoringSection", () => ({
  MonitoringSection: () => <div data-testid="monitoring-section">Monitoring</div>,
}));
vi.mock("@/tools/Settings/SkillSection", () => ({
  SkillSection: () => <div data-testid="skill-section">Skill Level</div>,
}));

vi.mock("@/hooks/useSettingsState", () => ({
  useSettingsState: () => ({
    general: {},
    trading: {},
    risk: {},
    llm: {},
    telegram: {},
    dataPaths: {},
    connection: {},
    restarting: false,
    updateGeneral: vi.fn(),
    updateTradingDefaults: vi.fn(),
    updateRiskLimits: vi.fn(),
    updateLLM: vi.fn(),
    updateTelegram: vi.fn(),
    updateDataPaths: vi.fn(),
    updateConnection: vi.fn(),
    handleRestart: vi.fn(),
  }),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import SettingsRoute from "../SettingsRoute";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SettingsRoute", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the Settings heading", () => {
    render(<SettingsRoute />);

    expect(screen.getByText("Settings")).toBeInTheDocument();
  });

  it("shows settings sections sidebar navigation", () => {
    render(<SettingsRoute />);

    const tablist = screen.getByRole("tablist", { name: /settings sections/i });
    expect(tablist).toBeInTheDocument();
    // Check a sample of section labels exist in the sidebar
    // Use getAllByText since "General" appears in both sidebar and content panel
    expect(screen.getAllByText("General").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Appearance").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("About").length).toBeGreaterThanOrEqual(1);
  });
});
