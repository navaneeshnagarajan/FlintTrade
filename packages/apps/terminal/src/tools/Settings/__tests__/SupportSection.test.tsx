import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

const getSupportDiagnostics = vi.hoisted(() => vi.fn());
const openExternalUrl = vi.hoisted(() => vi.fn());

vi.mock("@/services/ftApi.support", () => ({ getSupportDiagnostics }));
vi.mock("@/lib/desktopShell", () => ({ openExternalUrl }));

import {
  GITHUB_NEW_ISSUE_URL,
  ISSUE_URL_BUDGET,
  SECURITY_ADVISORY_URL,
  SupportSection,
  buildIssueBody,
  buildIssueLaunch,
  safeClientRoute,
} from "../SupportSection";

const diagnostics = {
  schema_version: 1 as const,
  generated_at: "2026-07-14T09:30:00+00:00",
  app: { name: "FlintTrade" as const, version: "v0.6.0-beta.1" },
  runtime: {
    os: "Darwin",
    os_release: "25.5.0",
    architecture: "arm64",
    python: "3.12.10",
  },
  errors: {
    available: true,
    total: 3,
    sampled: 3,
    groups: [{
      route: "/v1/example",
      method: "GET",
      status_code: 500,
      error_class: "RuntimeError",
      occurrences: 3,
      first_seen: "2026-07-14T09:00:00+00:00",
      last_seen: "2026-07-14T09:30:00+00:00",
    }],
  },
};

beforeEach(() => {
  getSupportDiagnostics.mockResolvedValue(diagnostics);
  openExternalUrl.mockResolvedValue(undefined);
  vi.spyOn(window.navigator, "userAgent", "get").mockReturnValue("Test Browser 1.0");
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1280 });
  Object.defineProperty(window, "innerHeight", { configurable: true, value: 720 });
  window.history.replaceState(null, "", "/settings#support");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("SupportSection", () => {
  it("loads safe diagnostics and requires a bug description before opening GitHub", async () => {
    render(<SupportSection />);

    expect(await screen.findByText("v0.6.0-beta.1")).toBeInTheDocument();
    expect(screen.getByText(/3 recorded errors/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /open github issue/i })).toBeDisabled();
  });

  it("opens a reviewed prefilled issue through the desktop-aware external opener", async () => {
    const user = userEvent.setup();
    render(<SupportSection />);
    await screen.findByText("v0.6.0-beta.1");

    await user.type(screen.getByLabelText(/bug summary/i), "Chart freezes after reconnect");
    await user.type(screen.getByLabelText(/affected area/i), "Trade chart");
    await user.type(screen.getByLabelText(/what happened/i), "The chart stopped repainting.");
    await user.click(screen.getByRole("button", { name: /open github issue/i }));

    expect(openExternalUrl).toHaveBeenCalledTimes(1);
    const [url] = openExternalUrl.mock.calls[0] ?? [];
    expect(String(url)).toContain(GITHUB_NEW_ISSUE_URL);
    const parsed = new URL(String(url));
    expect(parsed.searchParams.get("title")).toContain("Chart freezes after reconnect");
    expect(parsed.searchParams.get("body")).toContain("The chart stopped repainting.");
    expect(parsed.searchParams.get("body")).toContain("Trade chart");
    expect(parsed.searchParams.get("body")).toContain("Not included in this GitHub draft");
    expect(parsed.searchParams.has("labels")).toBe(false);
  });

  it("downloads the exact local diagnostics bundle", async () => {
    const createObjectURL = vi.fn(() => "blob:diagnostics");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    const click = vi.fn();
    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tagName: string) => {
      const element = originalCreateElement(tagName);
      if (tagName === "a") element.click = click;
      return element;
    });
    const user = userEvent.setup();
    render(<SupportSection />);
    await screen.findByText("v0.6.0-beta.1");

    await user.click(screen.getByRole("button", { name: /download diagnostics/i }));

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:diagnostics");
  });

  it("copies the locally prepared report without uploading it", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(window.navigator.clipboard, "writeText");
    render(<SupportSection />);
    await screen.findByText("v0.6.0-beta.1");
    await user.type(screen.getByLabelText(/what happened/i), "The chart stopped repainting.");
    await user.click(screen.getByRole("switch", { name: /include diagnostic summary/i }));

    await user.click(screen.getByRole("button", { name: /copy report/i }));

    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText.mock.calls[0]?.[0]).toContain("The chart stopped repainting.");
    expect(writeText.mock.calls[0]?.[0]).toContain("RuntimeError");
    expect(screen.getByRole("button", { name: /copied/i })).toBeInTheDocument();
  });

  it("shows the exact GitHub draft including every opted-in diagnostic field", async () => {
    const user = userEvent.setup();
    render(<SupportSection />);
    await screen.findByText("v0.6.0-beta.1");

    await user.type(screen.getByLabelText(/what happened/i), "The chart stopped repainting.");
    await user.click(screen.getByText("Include diagnostic summary in GitHub draft"));

    const preview = screen.getByLabelText("GitHub draft preview");
    expect(preview).toHaveTextContent("The chart stopped repainting.");
    expect(preview).toHaveTextContent("Test Browser 1.0");
    expect(preview).toHaveTextContent("RuntimeError on GET /v1/example (500) x3");
    expect(screen.getByRole("switch", { name: /include diagnostic summary/i })).toBeChecked();
  });

  it("surfaces diagnostics loading failures without blocking a report", async () => {
    getSupportDiagnostics.mockRejectedValueOnce(new Error("Backend unavailable"));
    render(<SupportSection />);

    expect(await screen.findByText("Backend unavailable")).toBeInTheDocument();
    expect(screen.getByLabelText(/bug summary/i)).toBeEnabled();
  });

  it("uses the private security-advisory route for vulnerability reports", async () => {
    const user = userEvent.setup();
    render(<SupportSection />);
    await screen.findByText("v0.6.0-beta.1");

    await user.click(screen.getByRole("button", { name: /report security issue privately/i }));

    expect(openExternalUrl).toHaveBeenCalledWith(SECURITY_ADVISORY_URL);
  });
});

describe("buildIssueBody", () => {
  it("normalises client paths before they enter a public report", () => {
    expect(safeClientRoute("/settings/private-account-id", "#support")).toBe("/settings#support");
    expect(safeClientRoute("/admin/observability/private-entry", "#ignored")).toBe("/admin/observability");
    expect(safeClientRoute("/private-account-id", "#secret-token")).toBe("/unknown");
  });

  it("includes safe environment and grouped error metadata only", () => {
    const body = buildIssueBody({
      affectedArea: "Trade chart",
      description: "Stopped repainting",
      steps: "Reconnect the feed",
      expected: "Chart resumes",
      includeDiagnostics: true,
      diagnostics,
      mode: "practice",
      userAgent: "Test Browser 1.0",
      viewport: "1280x720",
    });

    expect(body).toContain("## Describe the bug");
    expect(body).toContain("Trade chart");
    expect(body).toContain("v0.6.0-beta.1");
    expect(body).toContain("RuntimeError on GET /v1/example (500) x3");
    expect(body).not.toContain("traceback");
    expect(body).not.toContain("request_body");
  });

  it("omits diagnostics from a public draft unless the operator opts in", () => {
    const body = buildIssueBody({
      affectedArea: "Trade chart",
      description: "Stopped repainting",
      steps: "Reconnect the feed",
      expected: "Chart resumes",
      includeDiagnostics: false,
      diagnostics,
      mode: "practice",
      userAgent: "Test Browser 1.0",
      viewport: "1280x720",
    });

    expect(body).toContain("Not included in this GitHub draft");
    expect(body).not.toContain("RuntimeError");
    expect(body).not.toContain("Darwin");
  });

  it("falls back to a copied body before an encoded issue URL can become excessive", () => {
    const launch = buildIssueLaunch("Large report", "x".repeat(ISSUE_URL_BUDGET));

    expect(launch.copyBody).toBe(true);
    expect(launch.url).toContain("template=bug_report.md");
    expect(launch.url).not.toContain("body=");
    expect(launch.url.length).toBeLessThan(ISSUE_URL_BUDGET);
  });
});
