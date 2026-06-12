/**
 * ReconciliationWidget.test.tsx
 *
 * Verifies the honest empty state (dormant natives), the per-target status
 * table (clean badge / severity counts / last run), the expandable
 * latest-report diffs, and the "Reconcile now" operator trigger.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";
import type {
  ReconciliationReport,
  ReconciliationStatus,
  ReconciliationTargetStatus,
} from "@/lib/reconciliationApi";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockUseReconciliationStatus = vi.fn();
const mockUseReconciliationReports = vi.fn();
const mockUseRunReconciliation = vi.fn();
const mockMutate = vi.fn();

vi.mock("@/lib/reconciliationApi", () => ({
  useReconciliationStatus: (...args: unknown[]) => mockUseReconciliationStatus(...args),
  useReconciliationReports: (...args: unknown[]) => mockUseReconciliationReports(...args),
  useRunReconciliation: (...args: unknown[]) => mockUseRunReconciliation(...args),
}));

const mockEmitNotification = vi.fn();
vi.mock("@/components/NotificationCentre/useNotificationFeed", () => ({
  emitNotification: (...args: unknown[]) => mockEmitNotification(...args),
}));

// ---------------------------------------------------------------------------
// Import component under test
// ---------------------------------------------------------------------------

import ReconciliationWidget from "./ReconciliationWidget";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultProps = makeDockviewPanelProps();

function queryResult(overrides = {}) {
  return {
    data: undefined,
    isLoading: false,
    isPending: false,
    isError: false,
    error: null,
    isFetching: false,
    refetch: vi.fn(),
    ...overrides,
  };
}

function makeTarget(overrides: Partial<ReconciliationTargetStatus> = {}): ReconciliationTargetStatus {
  return {
    broker: "dhan",
    account_id: "ACC1",
    last_report_at: "2026-06-12T09:15:00+00:00",
    clean: true,
    severity: "",
    severity_counts: { info: 0, warning: 0, critical: 0 },
    error: "",
    ...overrides,
  };
}

function makeStatus(overrides: Partial<ReconciliationStatus> = {}): ReconciliationStatus {
  return { targets: [], runner_active: false, ...overrides };
}

function makeReport(overrides: Partial<ReconciliationReport> = {}): ReconciliationReport {
  return {
    adapter_id: "dhan",
    account_id: "ACC1",
    generated_at: "2026-06-12T09:15:00+00:00",
    orders_diff: [],
    positions_diff: [],
    holdings_diff: [],
    error: "",
    clean: true,
    severity: "",
    severity_counts: { info: 0, warning: 0, critical: 0 },
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ReconciliationWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseReconciliationStatus.mockReturnValue(queryResult({ data: makeStatus() }));
    mockUseReconciliationReports.mockReturnValue(queryResult({ data: [] }));
    mockUseRunReconciliation.mockReturnValue({ mutate: mockMutate, isPending: false });
  });

  it("renders the honest empty state when no native sessions are active", () => {
    render(<ReconciliationWidget {...defaultProps} />);

    expect(screen.getByText("No reconciliation reports yet")).toBeInTheDocument();
    expect(
      screen.getByText(
        "No native broker sessions active — reconciliation runs once a native adapter is live",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Runner dormant")).toBeInTheDocument();
  });

  it("shows a waiting message instead when the runner is active but has no reports", () => {
    mockUseReconciliationStatus.mockReturnValue(
      queryResult({ data: makeStatus({ runner_active: true }) }),
    );
    render(<ReconciliationWidget {...defaultProps} />);

    expect(screen.getByText("Runner active")).toBeInTheDocument();
    expect(
      screen.getByText("The runner is active — the first cycle will appear here shortly."),
    ).toBeInTheDocument();
  });

  it("renders one row per target with clean badge and severity counts", () => {
    mockUseReconciliationStatus.mockReturnValue(
      queryResult({
        data: makeStatus({
          runner_active: true,
          targets: [
            makeTarget(),
            makeTarget({
              broker: "upstox",
              account_id: "U99",
              clean: false,
              severity: "critical",
              severity_counts: { info: 0, warning: 2, critical: 1 },
            }),
          ],
        }),
      }),
    );
    render(<ReconciliationWidget {...defaultProps} />);

    expect(screen.getByText("dhan")).toBeInTheDocument();
    expect(screen.getByText("ACC1")).toBeInTheDocument();
    expect(screen.getByText("Clean")).toBeInTheDocument();
    expect(screen.getByText("upstox")).toBeInTheDocument();
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByText("1 critical")).toBeInTheDocument();
    expect(screen.getByText("2 warning")).toBeInTheDocument();
  });

  it("expands a row to show the latest report's diffs", () => {
    mockUseReconciliationStatus.mockReturnValue(
      queryResult({
        data: makeStatus({
          runner_active: true,
          targets: [makeTarget({ clean: false, severity: "critical" })],
        }),
      }),
    );
    mockUseReconciliationReports.mockReturnValue(
      queryResult({
        data: [
          makeReport({
            clean: false,
            severity: "critical",
            positions_diff: [
              {
                symbol: "NIFTY24JUNFUT",
                exchange: "NFO",
                product: "NRML",
                flinttrade_qty: 0,
                broker_qty: 50,
                discrepancy: "exists_only_on_broker",
                severity: "critical",
              },
            ],
          }),
        ],
      }),
    );
    render(<ReconciliationWidget {...defaultProps} />);

    fireEvent.click(
      screen.getByRole("button", { name: /show latest report for dhan ACC1/i }),
    );

    // The lazy reports hook is asked for the expanded target's latest report.
    expect(mockUseReconciliationReports).toHaveBeenCalledWith("dhan", "ACC1", 1, true);
    expect(screen.getByText("NIFTY24JUNFUT")).toBeInTheDocument();
    expect(screen.getByText(/exists_only_on_broker/)).toBeInTheDocument();
    expect(screen.getByText(/flinttrade 0 vs broker 50/)).toBeInTheDocument();
  });

  it("shows the broker fetch error honestly in the expanded report", () => {
    mockUseReconciliationStatus.mockReturnValue(
      queryResult({
        data: makeStatus({
          runner_active: true,
          targets: [makeTarget({ clean: false, severity: "critical", error: "timeout" })],
        }),
      }),
    );
    mockUseReconciliationReports.mockReturnValue(
      queryResult({ data: [makeReport({ clean: false, severity: "critical", error: "HTTP 502 from broker" })] }),
    );
    render(<ReconciliationWidget {...defaultProps} />);

    fireEvent.click(
      screen.getByRole("button", { name: /show latest report for dhan ACC1/i }),
    );

    expect(
      screen.getByText(/Broker fetch failed — broker state unknown: HTTP 502 from broker/),
    ).toBeInTheDocument();
  });

  it("triggers the run mutation when 'Reconcile now' is clicked", () => {
    render(<ReconciliationWidget {...defaultProps} />);

    fireEvent.click(screen.getByRole("button", { name: "Reconcile now" }));

    expect(mockMutate).toHaveBeenCalledTimes(1);
  });

  it("disables the button and shows progress while the run is pending", () => {
    mockUseRunReconciliation.mockReturnValue({ mutate: mockMutate, isPending: true });
    render(<ReconciliationWidget {...defaultProps} />);

    const button = screen.getByRole("button", { name: "Reconcile now" });
    expect(button).toBeDisabled();
    expect(screen.getByText("Reconciling…")).toBeInTheDocument();
  });

  it("emits an honest alert notification when the run fails", () => {
    mockMutate.mockImplementation(
      (_vars: unknown, options?: { onError?: (err: Error) => void }) => {
        options?.onError?.(new Error("Reconciliation runner not active — no native broker sessions to reconcile"));
      },
    );
    render(<ReconciliationWidget {...defaultProps} />);

    fireEvent.click(screen.getByRole("button", { name: "Reconcile now" }));

    expect(mockEmitNotification).toHaveBeenCalledWith(
      expect.objectContaining({
        category: "alert",
        title: "Reconciliation failed",
        body: "Reconciliation runner not active — no native broker sessions to reconcile",
      }),
    );
  });

  it("shows an error banner with Retry when the status query fails", () => {
    const mockRefetch = vi.fn();
    mockUseReconciliationStatus.mockReturnValue(
      queryResult({ isError: true, error: new Error("backend down"), refetch: mockRefetch }),
    );
    render(<ReconciliationWidget {...defaultProps} />);

    expect(screen.getByText(/failed to load reconciliation status/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(mockRefetch).toHaveBeenCalledTimes(1);
  });
});
