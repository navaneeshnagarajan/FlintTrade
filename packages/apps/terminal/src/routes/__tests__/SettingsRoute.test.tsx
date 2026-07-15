/**
 * SettingsRoute.test.tsx
 *
 * Smoke tests for the /settings full-page settings route.
 * Mocks stores, hooks, settings sections, and CinematicLayout.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn();
const llmRouteMocks = vi.hoisted(() => ({
  props: null as null | Record<string, unknown>,
  saveState: "saved" as "saved" | "pending" | "saving" | "error",
  hydrationState: "ready" as "loading" | "ready" | "error",
  setupPending: false,
  updateLLM: vi.fn(),
  updateLLMProvider: vi.fn(),
  removeLLMCredential: vi.fn(),
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
}));

vi.mock("@/components/brand/Logo", () => ({
  LogoIcon: ({ size }: { size: number }) => (
    <svg data-testid="logo-icon" width={size} height={size} />
  ),
}));

vi.mock("@/components/layout/CinematicLayout", () => ({
  CinematicLayout: ({
    children,
    className,
  }: {
    children: React.ReactNode;
    className?: string;
  }) => <div className={className} data-testid="settings-layout">{children}</div>,
}));

vi.mock("@/tools/Settings/shared", () => ({
  InlineToast: () => null,
}));

// Mock all section components to simple stubs
vi.mock("@/tools/Settings/ProfileSection", () => ({
  ProfileSection: () => <div data-testid="profile-section">Profile</div>,
}));
vi.mock("@/routes/settings/TickerSettings", () => ({
  TickerSettings: () => <div data-testid="ticker-section">Ticker Bar</div>,
}));
vi.mock("@/tools/Settings/GeneralSection", () => ({
  GeneralSection: () => <div data-testid="general-section">General</div>,
}));
vi.mock("@/tools/Settings/AppearanceSection", () => ({
  AppearanceSection: () => <div data-testid="appearance-section">Appearance</div>,
}));
vi.mock("@/tools/Settings/ConnectionSection", () => ({
  ConnectionSection: () => <div data-testid="connection-section">Connection</div>,
}));
vi.mock("@/components/account/BrokerConnect", () => ({
  BrokerConnect: () => <div data-testid="brokers-section">Brokers</div>,
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
  LLMSection: (props: Record<string, unknown>) => {
    llmRouteMocks.props = props;
    return <div data-testid="llm-section">LLM</div>;
  },
}));
vi.mock("@/tools/Settings/TelegramSection", () => ({
  TelegramSection: () => <div data-testid="telegram-section">Telegram</div>,
}));
vi.mock("@/tools/Settings/WhatsAppSection", () => ({
  WhatsAppSection: () => <div data-testid="whatsapp-section">WhatsApp</div>,
}));
vi.mock("@/tools/Settings/DataSection", () => ({
  DataSection: () => <div data-testid="data-section">Data</div>,
}));
vi.mock("@/tools/Settings/AboutSection", () => ({
  AboutSection: () => <div data-testid="about-section">About</div>,
}));
vi.mock("@/tools/Settings/SupportSection", () => ({
  SupportSection: () => <div data-testid="support-section">Report Bug</div>,
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
vi.mock("@/tools/Settings/PresetSection", () => ({
  PresetSection: () => <div data-testid="preset-section">Workspace Presets</div>,
}));

vi.mock("@/hooks/useSettingsState", () => ({
  useSettingsState: () => ({
    general: {},
    trading: {},
    risk: {},
    llm: {},
    llmSetupPending: llmRouteMocks.setupPending,
    llmSaveState: llmRouteMocks.saveState,
    llmHydrationState: llmRouteMocks.hydrationState,
    llmCredentialConfigured: true,
    llmCredentialLast4: "live",
    telegram: {},
    whatsapp: {},
    dataPaths: {},
    connection: {},
    restarting: false,
    updateGeneral: vi.fn(),
    updateTradingDefaults: vi.fn(),
    updateRiskLimits: vi.fn(),
    updateLLM: llmRouteMocks.updateLLM,
    updateLLMProvider: llmRouteMocks.updateLLMProvider,
    removeLLMCredential: llmRouteMocks.removeLLMCredential,
    updateTelegram: vi.fn(),
    updateWhatsApp: vi.fn(),
    updateDataPaths: vi.fn(),
    acceptConnection: vi.fn(),
    handleRestart: vi.fn(),
  }),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import SettingsRoute from "../SettingsRoute";
import { SECTIONS } from "@/tools/Settings/settingsConfig";

function mockSettingsBreakpoint(initialDesktop: boolean) {
  let matches = initialDesktop;
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  const media = "(min-width: 768px)";
  const mediaQueryList = {
    get matches() {
      return matches;
    },
    media,
    onchange: null,
    addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
      listeners.add(listener);
    },
    removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
      listeners.delete(listener);
    },
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  } as unknown as MediaQueryList;
  vi.spyOn(window, "matchMedia").mockReturnValue(mediaQueryList);

  return {
    setDesktop(nextDesktop: boolean) {
      matches = nextDesktop;
      const event = { matches, media } as MediaQueryListEvent;
      listeners.forEach((listener) => listener(event));
    },
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SettingsRoute", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    llmRouteMocks.props = null;
    llmRouteMocks.saveState = "saved";
    llmRouteMocks.hydrationState = "ready";
    llmRouteMocks.setupPending = false;
    window.history.replaceState(null, "", "/settings");
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

  it("fits inside the shared app chrome instead of covering the full viewport", () => {
    render(<SettingsRoute />);

    expect(screen.getByRole("region", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByTestId("settings-layout")).toHaveClass("h-full");
    expect(screen.getByTestId("settings-layout")).not.toHaveClass("fixed");
  });

  it("syncs the active section when the settings hash changes", () => {
    window.history.replaceState(null, "", "/settings#about");

    render(<SettingsRoute />);

    expect(screen.getByTestId("about-section")).toBeInTheDocument();

    act(() => {
      window.location.hash = "#monitoring";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    expect(screen.getByTestId("monitoring-section")).toBeInTheDocument();
  });

  it("scrolls the deep-linked mobile tab into view", () => {
    mockSettingsBreakpoint(false);
    const scrollIntoView = vi.spyOn(Element.prototype, "scrollIntoView")
      .mockImplementation(() => undefined);
    window.history.replaceState(null, "", "/settings#llm");

    render(<SettingsRoute />);

    const llmTab = document.getElementById("settings-tab-llm");
    expect(llmTab).toHaveAttribute("aria-selected", "true");
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest", inline: "nearest" });
    expect(scrollIntoView.mock.instances).toContain(llmTab);
  });

  it("re-scrolls the selected tab when the settings navigation becomes horizontal", () => {
    const breakpoint = mockSettingsBreakpoint(true);
    const scrollIntoView = vi.spyOn(Element.prototype, "scrollIntoView")
      .mockImplementation(() => undefined);
    window.history.replaceState(null, "", "/settings#llm");

    render(<SettingsRoute />);

    const tablist = screen.getByRole("tablist", { name: /settings sections/i });
    const llmTab = document.getElementById("settings-tab-llm");
    expect(tablist).toHaveAttribute("aria-orientation", "vertical");
    scrollIntoView.mockClear();

    act(() => breakpoint.setDesktop(false));

    expect(tablist).toHaveAttribute("aria-orientation", "horizontal");
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest", inline: "nearest" });
    expect(scrollIntoView.mock.instances).toContain(llmTab);
  });

  it("uses Left and Right Arrow navigation for the horizontal mobile tablist", () => {
    mockSettingsBreakpoint(false);
    window.history.replaceState(null, "", "/settings#general");

    render(<SettingsRoute />);

    const tablist = screen.getByRole("tablist", { name: /settings sections/i });
    const generalTab = document.getElementById("settings-tab-general");
    const appearanceTab = document.getElementById("settings-tab-appearance");
    expect(tablist).toHaveAttribute("aria-orientation", "horizontal");

    generalTab?.focus();
    fireEvent.keyDown(generalTab as HTMLElement, { key: "ArrowRight" });
    expect(appearanceTab).toHaveAttribute("aria-selected", "true");
    expect(appearanceTab).toHaveFocus();

    fireEvent.keyDown(appearanceTab as HTMLElement, { key: "ArrowLeft" });
    expect(generalTab).toHaveAttribute("aria-selected", "true");
    expect(generalTab).toHaveFocus();
  });

  it("passes the atomic provider transaction separately from debounced field edits", () => {
    llmRouteMocks.setupPending = true;
    window.history.replaceState(null, "", "/settings#llm");

    render(<SettingsRoute />);

    expect(llmRouteMocks.props).toEqual(expect.objectContaining({
      onChange: llmRouteMocks.updateLLM,
      onProviderChange: llmRouteMocks.updateLLMProvider,
      onCredentialRemove: llmRouteMocks.removeLLMCredential,
      credentialConfigured: true,
      credentialLast4: "live",
      hydrationState: "ready",
      providerActivationRequired: true,
    }));
  });

  it("only links the selected tab to the single mounted tab panel", () => {
    window.history.replaceState(null, "", "/settings#llm");
    render(<SettingsRoute />);

    const panel = screen.getByRole("tabpanel");
    const selectedTab = screen.getByRole("tab", { name: "LLM Config" });
    expect(selectedTab).toHaveAttribute("aria-controls", panel.id);
    for (const tab of screen.getAllByRole("tab")) {
      if (tab !== selectedTab) expect(tab).not.toHaveAttribute("aria-controls");
    }
  });

  it("keeps the LLM surface mounted while another settings tab is visible", () => {
    window.history.replaceState(null, "", "/settings#llm");
    render(<SettingsRoute />);
    const llmSurface = screen.getByTestId("llm-section");

    fireEvent.click(screen.getByRole("tab", { name: "General" }));
    expect(llmSurface).toBeInTheDocument();
    expect(llmSurface).not.toBeVisible();

    fireEvent.click(screen.getByRole("tab", { name: "LLM Config" }));
    expect(screen.getByTestId("llm-section")).toBe(llmSurface);
    expect(llmSurface).toBeVisible();
  });

  it.each([
    ["saved", "No pending LLM changes"],
    ["pending", "LLM changes pending"],
    ["saving", "Saving LLM changes"],
    ["error", "LLM changes not saved"],
  ] as const)("reports the truthful %s persistence state", (saveState, copy) => {
    llmRouteMocks.saveState = saveState;
    render(<SettingsRoute />);

    expect(screen.getByRole("status", { name: "Settings save status" })).toHaveTextContent(copy);
  });

  it.each([
    ["loading", "Loading LLM settings"],
    ["error", "LLM settings unavailable"],
  ] as const)("reports the truthful %s hydration state", (hydrationState, copy) => {
    llmRouteMocks.hydrationState = hydrationState;
    render(<SettingsRoute />);

    expect(screen.getByRole("status", { name: "Settings save status" })).toHaveTextContent(copy);
  });

  it("reports an unapplied provider draft instead of claiming it is saved", () => {
    window.history.replaceState(null, "", "/settings#llm");
    render(<SettingsRoute />);

    const onDraftStateChange = llmRouteMocks.props?.onDraftStateChange as ((pending: boolean) => void);
    act(() => onDraftStateChange(true));

    expect(screen.getByRole("status", { name: "Settings save status" }))
      .toHaveTextContent("LLM provider changes not applied");
  });

  // -------------------------------------------------------------------------
  // Unified Settings — EVERY section must be reachable + render.
  //
  // The mission requires the unified Settings page to expose all of its
  // sections, each reachable by deep-link. These two tests drive straight
  // from the SECTIONS registry so a section can never be added to the nav
  // yet (a) miss a renderContent() switch case, or (b) fail to activate from
  // its #hash — both silent, content-empty failures the old smoke test (only
  // #about + #monitoring) could not catch.
  // -------------------------------------------------------------------------
  it.each(SECTIONS.map((s) => [s.id, s.label] as const))(
    "deep-links #%s to its tab and renders that section's panel",
    (id, label) => {
      window.history.replaceState(null, "", `/settings#${id}`);
      render(<SettingsRoute />);

      // The matching sidebar tab is the selected one and carries its label.
      const tab = document.getElementById(`settings-tab-${id}`);
      expect(tab, `tab for section "${id}" is missing`).not.toBeNull();
      expect(tab).toHaveAttribute("aria-selected", "true");
      expect(tab?.textContent).toContain(label);

      // Exactly this section's content panel is rendered (one panel at a time).
      const panel = screen.getByRole("tabpanel");
      expect(panel).toHaveAttribute("id", `settings-tabpanel-${id}`);
    },
  );

  it("renders non-empty content for every section (no missing switch case)", () => {
    // A dropped renderContent() case returns undefined → an empty panel. With
    // every section mocked to emit text, an empty panel can only mean the
    // switch lost a case.
    for (const { id } of SECTIONS) {
      window.history.replaceState(null, "", `/settings#${id}`);
      const { unmount } = render(<SettingsRoute />);
      const panel = screen.getByRole("tabpanel");
      expect(
        (panel.textContent ?? "").trim().length,
        `section "${id}" rendered an empty panel`,
      ).toBeGreaterThan(0);
      unmount();
    }
  });
});
