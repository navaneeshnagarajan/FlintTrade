import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";

// Mock framer-motion to avoid animation issues in tests
vi.mock("framer-motion", () => ({
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  motion: {
    div: ({ children, ...props }: Record<string, unknown>) => (
      <div {...props}>{children as React.ReactNode}</div>
    ),
    span: ({ children, ...props }: Record<string, unknown>) => (
      <span {...props}>{children as React.ReactNode}</span>
    ),
  },
}));

vi.mock("@/lib/motion", () => ({
  motionConfig: {
    prefersReducedMotion: () => true,
    duration: { fast: 0, normal: 0, slow: 0 },
    ease: { enter: [0, 0, 1, 1] },
    transitions: { scale: { duration: 0 }, tab: { duration: 0 } },
  },
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

vi.mock("@/components/help/SpotlightTour", () => ({
  SpotlightTour: () => null,
}));

vi.mock("@/lib/tourDefinitions", () => ({
  TOUR_DEFINITIONS: {},
}));

import LearnRoute from "../LearnRoute";

function renderLearnRoute(initialEntries: Parameters<typeof MemoryRouter>[0]["initialEntries"] = ["/learn"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <LearnRoute />
    </MemoryRouter>,
  );
}

// Locked FT-LEARN-003 copy (USER_GUIDE Learn → Resource Hub).
const DOC_LOADING = "Loading document…";
const DOC_SOFT_FAIL = "Document isn’t ready yet.";
const DOC_HARD_FAIL = "Couldn’t load this document from the local backend.";
const DOC_LEGACY_HARD_FAIL = "Could not load this document from the local backend.";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((settle, fail) => {
    resolve = settle;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function docsResponse(title: string, content: string): Response {
  return new Response(JSON.stringify({ title, content }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function openUserGuideCard() {
  fireEvent.click(screen.getByRole("tab", { name: "Resource Hub" }));
  fireEvent.click(screen.getByRole("button", { name: /User Guide/ }));
}

function expectNoHardFail() {
  expect(screen.queryByText(DOC_HARD_FAIL)).not.toBeInTheDocument();
  expect(screen.queryByText(DOC_LEGACY_HARD_FAIL)).not.toBeInTheDocument();
}

describe("LearnRoute", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the Learning Center heading", () => {
    renderLearnRoute();
    expect(screen.getByText("Learning Center")).toBeInTheDocument();
  });

  it("has sidebar sections for all tabs at advanced level", () => {
    renderLearnRoute();
    expect(screen.getByText("Market Basics")).toBeInTheDocument();
    expect(screen.getByText("Glossary")).toBeInTheDocument();
    expect(screen.getByText("Strategy Library")).toBeInTheDocument();
    expect(screen.getByText("Practice Trading")).toBeInTheDocument();
    expect(screen.getByText("Resource Hub")).toBeInTheDocument();
  });

  it("shows Market Basics content by default", () => {
    renderLearnRoute();
    // Market Basics tab content includes the first section title
    expect(screen.getByText("What are Stocks?")).toBeInTheDocument();
  });

  it("loads and renders a selected documentation result", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          title: "User Guide",
          content: "# User Guide\n\n- Configure your workspace\n\nRead the setup flow.",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    renderLearnRoute([
      {
        pathname: "/learn",
        state: {
          selectedDoc: {
            path: "USER_GUIDE.md",
            title: "User Guide",
            snippet: "Selected from search",
          },
        },
      },
    ]);

    await waitFor(() => expect(screen.getByText("Configure your workspace")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith(
      "/ft-api/v1/docs/document?path=USER_GUIDE.md",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("offers a Settings Broker Gateway CTA from Practice Trading", () => {
    renderLearnRoute();
    fireEvent.click(screen.getByRole("tab", { name: "Practice Trading" }));

    const cta = screen.getByRole("link", { name: /open settings.*broker gateway/i });
    expect(cta).toHaveAttribute("href", "/settings#api");
    expect(screen.getByText(/configure openalgo in settings/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /settings\s*→\s*brokers/i })).not.toBeInTheDocument();
    expect(document.querySelector('a[href="/settings#brokers"]')).toBeNull();
  });

  it("wraps Practice Trading sandbox rows so a ~390px viewport does not clip", () => {
    renderLearnRoute();
    fireEvent.click(screen.getByRole("tab", { name: "Practice Trading" }));

    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveClass("min-w-0");

    const dhanRow = screen.getByText("Dhan Sandbox").closest("[data-testid='practice-sandbox-row']");
    expect(dhanRow).toHaveClass("flex-wrap", "min-w-0");

    const kotakRow = screen.getByText("Kotak Neo Sandbox").closest("[data-testid='practice-sandbox-row']");
    expect(kotakRow).toHaveClass("flex-wrap", "min-w-0");
  });

  it("stacks the Learn shell and wraps Practice Trading so a ~390px column cannot clip", () => {
    renderLearnRoute();
    fireEvent.click(screen.getByRole("tab", { name: "Practice Trading" }));

    const body = screen.getByTestId("learn-body");
    expect(body).toHaveClass("flex-col", "min-w-0");
    expect(body.className).toMatch(/md:flex-row/);

    const sidebar = screen.getByTestId("learn-sidebar");
    expect(sidebar).toHaveClass("w-full", "min-w-0");

    const tablist = screen.getByRole("tablist");
    expect(tablist).toHaveClass("flex-wrap", "min-w-0");

    const practice = screen.getByTestId("practice-trading");
    expect(practice).toHaveClass("min-w-0", "max-w-full");

    const cta = screen.getByRole("link", { name: /open settings.*broker gateway/i });
    expect(cta).toHaveAttribute("href", "/settings#api");
    expect(cta).toHaveClass("whitespace-normal");
    expect(cta.className).not.toMatch(/(?:^|\s)whitespace-nowrap(?:\s|$)/);

    const nowrapLeftovers = [...practice.querySelectorAll("[class]")].filter((el) => {
      if (el.closest('[data-slot="badge"]')) return false;
      const cls = el.getAttribute("class") ?? "";
      return /(?:^|\s)whitespace-nowrap(?:\s|$)/.test(cls) && !cls.includes("whitespace-normal");
    });
    expect(nowrapLeftovers).toEqual([]);
  });

  it("teaches dated Jan 2026 NSE-cycle index lots, not retired NIFTY=25 / BANKNIFTY=15", () => {
    renderLearnRoute();
    fireEvent.click(screen.getByRole("tab", { name: "Glossary" }));

    const lotSize = screen.getByText("Lot Size");
    fireEvent.click(lotSize);

    expect(screen.getAllByText(/NIFTY 65/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/BANKNIFTY 30/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/FINNIFTY 60/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/MIDCPNIFTY 120/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/as of Jan 2026 NSE cycle/i).length).toBeGreaterThan(0);
    expect(screen.queryAllByText(/NIFTY\s*=\s*25/)).toHaveLength(0);
    expect(screen.queryAllByText(/BANKNIFTY\s*=\s*15/)).toHaveLength(0);
    expect(screen.queryAllByText(/\bNIFTY\s+25\b/)).toHaveLength(0);
    expect(screen.queryAllByText(/\bBANKNIFTY\s+15\b/)).toHaveLength(0);

    const verify = screen.getByRole("link", { name: /verify on nse/i });
    expect(verify).toHaveAttribute(
      "href",
      "https://nsearchives.nseindia.com/content/circulars/FAOP70616.pdf",
    );
    expect(verify).toHaveAttribute("target", "_blank");
    expect(verify).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(verify.closest("button")).toBeNull();
  });

  it("does not clip the glossary toggle focus ring with overflow-hidden", () => {
    renderLearnRoute();
    fireEvent.click(screen.getByRole("tab", { name: "Glossary" }));

    const toggle = screen.getByText("Lot Size").closest("button");
    expect(toggle).not.toBeNull();
    const card = toggle!.closest("[data-slot='card']");
    expect(card).not.toBeNull();
    expect(card!.className).not.toMatch(/(?:^|\s)overflow-hidden(?:\s|$)/);
  });

  it("keeps Lot Size source dated so NIFTY=25 / BANKNIFTY=15 cannot regress", () => {
    const src = readFileSync(join(process.cwd(), "src/routes/LearnRoute.tsx"), "utf8");
    expect(src).not.toMatch(/NIFTY\s*=\s*25/);
    expect(src).not.toMatch(/BANKNIFTY\s*=\s*15/);
    expect(src).not.toMatch(/\bNIFTY\s+25\b/);
    expect(src).not.toMatch(/\bBANKNIFTY\s+15\b/);
    expect(src).toMatch(/NIFTY 65/);
    expect(src).toMatch(/BANKNIFTY 30/);
    expect(src).toMatch(/FINNIFTY 60/);
    expect(src).toMatch(/MIDCPNIFTY 120/);
    expect(src).toMatch(/as of Jan 2026 NSE cycle/);
    expect(src).toMatch(/Verify on NSE/);
    expect(src).toMatch(/nsearchives\.nseindia\.com\/content\/circulars\/FAOP70616\.pdf/);
  });

  it("shows Loading document… on first-open User Guide and never a red backend error while pending", async () => {
    const pending = deferred<Response>();
    vi.spyOn(globalThis, "fetch").mockReturnValue(pending.promise);

    renderLearnRoute();
    openUserGuideCard();

    expect(await screen.findByText(DOC_LOADING)).toBeInTheDocument();
    expectNoHardFail();
    expect(screen.queryByText(DOC_SOFT_FAIL)).not.toBeInTheDocument();

    pending.resolve(docsResponse("User Guide", "Configure your workspace"));
    expect(await screen.findByText("Configure your workspace")).toBeInTheDocument();
    expect(screen.queryByText(DOC_LOADING)).not.toBeInTheDocument();
    expectNoHardFail();
  });

  it("treats a first-open timeout/race as a muted soft fail with Retry, not a hard backend death", async () => {
    const autoRetry = deferred<Response>();
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new Error("Failed to fetch"))
      .mockReturnValueOnce(autoRetry.promise);

    renderLearnRoute();
    openUserGuideCard();

    expect(await screen.findByText(DOC_SOFT_FAIL)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expectNoHardFail();
    expect(screen.queryByText(DOC_LOADING)).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalled();

    autoRetry.resolve(docsResponse("User Guide", "Configure your workspace"));
    expect(await screen.findByText("Configure your workspace")).toBeInTheDocument();
    expect(screen.queryByText(DOC_SOFT_FAIL)).not.toBeInTheDocument();
    expectNoHardFail();
  });

  it("auto-retries once and recovers a cold-start User Guide without a hard fail", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new Error("Failed to fetch"))
      .mockResolvedValueOnce(docsResponse("User Guide", "Configure your workspace"));

    renderLearnRoute();
    openUserGuideCard();

    expect(await screen.findByText("Configure your workspace")).toBeInTheDocument();
    expectNoHardFail();
    expect(screen.queryByText(DOC_SOFT_FAIL)).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("shows hard-fail copy plus Retry only after retry is exhausted", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new Error("Failed to fetch"))
      .mockRejectedValueOnce(new Error("Failed to fetch"));

    renderLearnRoute();
    openUserGuideCard();

    expect(await screen.findByText(DOC_HARD_FAIL)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByText(DOC_SOFT_FAIL)).not.toBeInTheDocument();
    expect(screen.queryByText(DOC_LEGACY_HARD_FAIL)).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("recovers from hard fail when Retry succeeds", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new Error("Failed to fetch"))
      .mockRejectedValueOnce(new Error("Failed to fetch"))
      .mockResolvedValueOnce(docsResponse("User Guide", "Configure your workspace"));

    renderLearnRoute();
    openUserGuideCard();

    expect(await screen.findByText(DOC_HARD_FAIL)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Configure your workspace")).toBeInTheDocument();
    expect(screen.queryByText(DOC_HARD_FAIL)).not.toBeInTheDocument();
  });

  it("does not mark User Guide permanently broken after Order Safety Notes loads in the same session", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("ORDER_SAFETY")) {
        return Promise.resolve(docsResponse("Order Safety Notes", "Gate every live order."));
      }
      const guideAttempts = fetchMock.mock.calls.filter((call) =>
        String(call[0]).includes("USER_GUIDE"),
      ).length;
      if (guideAttempts <= 2) {
        return Promise.reject(new Error("Failed to fetch"));
      }
      return Promise.resolve(docsResponse("User Guide", "Configure your workspace"));
    });

    renderLearnRoute();
    fireEvent.click(screen.getByRole("tab", { name: "Resource Hub" }));
    fireEvent.click(screen.getByRole("button", { name: /User Guide/ }));
    expect(await screen.findByText(DOC_HARD_FAIL)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Order Safety Notes/ }));
    expect(await screen.findByText("Gate every live order.")).toBeInTheDocument();
    expect(screen.queryByText(DOC_HARD_FAIL)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /User Guide/ }));
    expect(await screen.findByText("Configure your workspace")).toBeInTheDocument();
    expectNoHardFail();
  });
});
