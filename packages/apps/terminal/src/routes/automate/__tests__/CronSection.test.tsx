/**
 * CronSection.test.tsx
 *
 * Schedules tab (FT-AUTO-004) — Explore seeded jobs must not look
 * production-Active, and Pause stays gated. Practice/Live keep Pause/Resume.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

const mockMode = vi.hoisted(() => ({ mode: "explore" }));
const mockGetCronJobs = vi.hoisted(() =>
  vi.fn().mockResolvedValue({ jobs: [] }),
);
const mockPauseCronJob = vi.hoisted(() =>
  vi.fn().mockResolvedValue({ status: "ok" }),
);
const mockResumeCronJob = vi.hoisted(() =>
  vi.fn().mockResolvedValue({ status: "ok" }),
);

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
      <div {...props}>{children}</div>
    ),
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

vi.mock("@/components/motion/StaggeredList", () => ({
  StaggeredList: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
    <div {...props}>{children}</div>
  ),
  default: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
    <div {...props}>{children}</div>
  ),
}));

vi.mock("@/components/ui/GlassCard", () => ({
  GlassCard: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
    <div {...props}>{children}</div>
  ),
  default: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
    <div {...props}>{children}</div>
  ),
}));

vi.mock("@/services/ftApi", () => ({
  getCronJobs: (...args: unknown[]) => mockGetCronJobs(...args),
  pauseCronJob: (...args: unknown[]) => mockPauseCronJob(...args),
  resumeCronJob: (...args: unknown[]) => mockResumeCronJob(...args),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: vi.fn((selector: (state: { mode: string }) => unknown) =>
    selector({ mode: mockMode.mode }),
  ),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SAMPLE_SCHEDULE_PAUSE_UNAVAILABLE =
  "Sample schedule — control unavailable in Explore";

const ACTIVE_JOB = {
  name: "health_check_job",
  description: "Verify OpenAlgo session at 9:10 AM IST",
  trigger_type: "cron",
  status: "ACTIVE",
  last_run: "2026-09-19T03:40:00+00:00",
  run_count: 12,
  error_count: 0,
};

const PAUSED_JOB = {
  ...ACTIVE_JOB,
  name: "square_off_warning_job",
  status: "PAUSED",
};

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children);
}

function expectNoExtraSampleChip(): void {
  expect(screen.queryByTestId("provenance-badge")).not.toBeInTheDocument();
  expect(screen.queryByTestId("provenance-badge-inline")).not.toBeInTheDocument();
}

async function findPauseControl(): Promise<HTMLElement> {
  const buttons = await screen.findAllByRole("button", { name: /pause/i });
  return buttons[0]!;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

import CronSection from "../CronSection";

describe("CronSection", () => {
  beforeEach(() => {
    mockMode.mode = "explore";
    mockGetCronJobs.mockReset();
    mockPauseCronJob.mockReset();
    mockResumeCronJob.mockReset();
    mockGetCronJobs.mockResolvedValue({ jobs: [] });
    mockPauseCronJob.mockResolvedValue({ status: "ok" });
    mockResumeCronJob.mockResolvedValue({ status: "ok" });
  });

  it("renders without crashing and shows heading", () => {
    render(<CronSection />, { wrapper: createWrapper() });
    expect(screen.getByText("Cron Scheduler")).toBeInTheDocument();
  });

  it("shows the description text", () => {
    render(<CronSection />, { wrapper: createWrapper() });
    expect(
      screen.getByText(/All registered automation schedules/),
    ).toBeInTheDocument();
  });

  it("shows Sample status and a gated Pause on seeded Explore jobs", async () => {
    render(<CronSection />, { wrapper: createWrapper() });

    const pause = await findPauseControl();
    expect(pause).toBeDisabled();
    expect(pause).toHaveAttribute("title", SAMPLE_SCHEDULE_PAUSE_UNAVAILABLE);
    expect(screen.getAllByText("Sample").length).toBeGreaterThan(0);
    expect(screen.queryByText("Active")).not.toBeInTheDocument();
    expectNoExtraSampleChip();

    await userEvent.click(pause);
    expect(mockPauseCronJob).not.toHaveBeenCalled();
    expect(mockResumeCronJob).not.toHaveBeenCalled();
  });

  it("remints a leaked Active Explore job so Pause cannot look live", async () => {
    mockGetCronJobs.mockResolvedValue({ jobs: [ACTIVE_JOB] });

    render(<CronSection />, { wrapper: createWrapper() });

    expect(await screen.findByText("health_check_job")).toBeInTheDocument();
    const pause = await findPauseControl();
    expect(pause).toBeDisabled();
    expect(pause).toHaveAttribute("title", SAMPLE_SCHEDULE_PAUSE_UNAVAILABLE);
    expect(screen.getByText("Sample")).toBeInTheDocument();
    expect(screen.queryByText("Active")).not.toBeInTheDocument();
    expectNoExtraSampleChip();

    await userEvent.click(pause);
    expect(mockPauseCronJob).not.toHaveBeenCalled();
  });

  it("keeps Pause armed on a Practice Active job", async () => {
    mockMode.mode = "practice";
    mockGetCronJobs.mockResolvedValue({ jobs: [ACTIVE_JOB] });

    render(<CronSection />, { wrapper: createWrapper() });

    const pause = await findPauseControl();
    expect(pause).toBeEnabled();
    expect(pause).not.toHaveAttribute("title", SAMPLE_SCHEDULE_PAUSE_UNAVAILABLE);
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.queryByText("Sample")).not.toBeInTheDocument();

    await userEvent.click(pause);
    await waitFor(() => {
      expect(mockPauseCronJob).toHaveBeenCalledWith("health_check_job");
    });
  });

  it("keeps Pause armed on a Live Active job", async () => {
    mockMode.mode = "live";
    mockGetCronJobs.mockResolvedValue({ jobs: [ACTIVE_JOB] });

    render(<CronSection />, { wrapper: createWrapper() });

    const pause = await findPauseControl();
    expect(pause).toBeEnabled();
    expect(pause).not.toHaveAttribute("title", SAMPLE_SCHEDULE_PAUSE_UNAVAILABLE);
    expect(screen.getByText("Active")).toBeInTheDocument();

    await userEvent.click(pause);
    await waitFor(() => {
      expect(mockPauseCronJob).toHaveBeenCalledWith("health_check_job");
    });
  });

  it("shows Demo status and a gated control on a paused Explore job", async () => {
    mockGetCronJobs.mockResolvedValue({ jobs: [PAUSED_JOB] });

    render(<CronSection />, { wrapper: createWrapper() });

    expect(await screen.findByText("square_off_warning_job")).toBeInTheDocument();
    const resume = await screen.findByRole("button", { name: /resume/i });
    expect(resume).toBeDisabled();
    expect(resume).toHaveAttribute("title", SAMPLE_SCHEDULE_PAUSE_UNAVAILABLE);
    expect(screen.getByText("Demo")).toBeInTheDocument();
    expect(screen.queryByText("Active")).not.toBeInTheDocument();
    expect(screen.queryByText("Paused")).not.toBeInTheDocument();

    await userEvent.click(resume);
    expect(mockResumeCronJob).not.toHaveBeenCalled();
  });

  it("keeps Resume armed on a Practice paused job", async () => {
    mockMode.mode = "practice";
    mockGetCronJobs.mockResolvedValue({ jobs: [PAUSED_JOB] });

    render(<CronSection />, { wrapper: createWrapper() });

    const resume = await screen.findByRole("button", { name: /resume/i });
    expect(resume).toBeEnabled();
    expect(resume).not.toHaveAttribute("title", SAMPLE_SCHEDULE_PAUSE_UNAVAILABLE);

    await userEvent.click(resume);
    await waitFor(() => {
      expect(mockResumeCronJob).toHaveBeenCalledWith("square_off_warning_job");
    });
  });
});
