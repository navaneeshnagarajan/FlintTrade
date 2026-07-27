/**
 * ReconciliationWidget.test.tsx
 *
 * Verifies the honest empty state (dormant natives), the per-target status
 * table (clean badge / severity counts / last run), the expandable
 * latest-report diffs, and the "Reconcile now" operator trigger.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@testing-library/jest-dom";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";
import { reconciliationKeys } from "@/lib/reconciliationApi";
import type {
  ReconciliationOutcomesResult,
  ReconciliationOutcome,
  ReconciliationOutcomeItem,
  ReconciliationErrorResolution,
  ReconciliationPendingResolution,
  ReconciliationReport,
  ReconciliationResolutionOutcome,
  ReconciliationStatus,
  ReconciliationTargetStatus,
  ResolveReconciliationOutcomeCallbacks,
  ResolveReconciliationOutcomeResult,
  ResolveReconciliationOutcomeVariables,
} from "@/lib/reconciliationApi";
import { useAuthStore } from "@/stores/authStore";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockUseReconciliationStatus = vi.fn();
const mockUseReconciliationReports = vi.fn();
const mockUseRunReconciliation = vi.fn();
const mockUseReconciliationOutcomes = vi.fn();
const mockUseResolveReconciliationOutcome = vi.fn();
const mockMutate = vi.fn();
const mockResolveMutate = vi.fn();
const mockResolveReset = vi.fn();
const mockEmitOrdersChanged = vi.fn();
const reconciliationHookMode = vi.hoisted(() => ({
  realOutcomes: false,
  realResolve: false,
}));

let currentMode: "explore" | "practice" | "live" = "explore";

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (state: { mode: typeof currentMode }) => unknown) =>
    selector({ mode: currentMode }),
}));

vi.mock("@/lib/reconciliationApi", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/reconciliationApi")>();
  return {
    ...actual,
    useReconciliationStatus: (...args: unknown[]) =>
      mockUseReconciliationStatus(...args),
    useReconciliationReports: (...args: unknown[]) =>
      mockUseReconciliationReports(...args),
    useRunReconciliation: (...args: unknown[]) =>
      mockUseRunReconciliation(...args),
    useReconciliationOutcomes: () =>
      reconciliationHookMode.realOutcomes
        ? actual.useReconciliationOutcomes()
        : mockUseReconciliationOutcomes(),
    useResolveReconciliationOutcome: (
      callbacks?: ResolveReconciliationOutcomeCallbacks,
    ) =>
      reconciliationHookMode.realResolve
        ? actual.useResolveReconciliationOutcome(callbacks)
        : mockUseResolveReconciliationOutcome(callbacks),
  };
});

const mockEmitNotification = vi.fn();
vi.mock("@/components/NotificationCentre/useNotificationFeed", () => ({
  emitNotification: (...args: unknown[]) => mockEmitNotification(...args),
}));

vi.mock("@/hooks/useOrders", () => ({
  emitOrdersChanged: (...args: unknown[]) => mockEmitOrdersChanged(...args),
}));

// ---------------------------------------------------------------------------
// Import component under test
// ---------------------------------------------------------------------------

import ReconciliationWidget from "./ReconciliationWidget";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultProps = makeWidgetPanelProps();

function makeJsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

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

function makeTarget(
  overrides: Partial<ReconciliationTargetStatus> = {},
): ReconciliationTargetStatus {
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

function makeStatus(
  overrides: Partial<ReconciliationStatus> = {},
): ReconciliationStatus {
  return { targets: [], runner_active: false, ...overrides };
}

function makeReport(
  overrides: Partial<ReconciliationReport> = {},
): ReconciliationReport {
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

function makeOutcome(
  overrides: Partial<ReconciliationOutcome> = {},
): ReconciliationOutcome {
  return {
    attempt_id: "attempt-123",
    adapter_id: "dhan",
    account_id: "ACC1",
    business_date: "2026-07-15",
    operation: "place_order",
    dispatch_state: "OUTCOME_UNKNOWN",
    intent_source: "manual",
    symbol: "RELIANCE",
    exchange: "NSE",
    product: "MIS",
    action: "BUY",
    quantity: 1,
    price: 1500,
    trigger_price: 0,
    price_type: "MARKET",
    variety: "regular",
    validity: "DAY",
    strategy: "",
    prepared_at: "2026-07-15T09:30:00+00:00",
    invoked_at: "2026-07-15T09:30:01+00:00",
    unknown_at: "2026-07-15T09:30:02+00:00",
    error_kind: "TimeoutError",
    recovery_supported_outcomes: [
      "confirmed_applied",
      "confirmed_not_applied",
      "confirmed_partial",
    ],
    recovery_blocked_reason: "",
    items: [],
    resolution: null,
    ...overrides,
  };
}

function makeOutcomeItem(
  index: number,
  symbol: string,
  overrides: Partial<ReconciliationOutcomeItem> = {},
): ReconciliationOutcomeItem {
  return {
    item_index: index,
    symbol,
    exchange: "NSE",
    product: "MIS",
    action: "BUY",
    quantity: 1,
    price: 1500,
    trigger_price: 0,
    price_type: "MARKET",
    variety: "regular",
    validity: "DAY",
    strategy: "",
    ...overrides,
  };
}

function makePendingResolution(
  overrides: Partial<ReconciliationPendingResolution> = {},
): ReconciliationPendingResolution {
  return {
    resolution_id: "resolution-1",
    outcome: "confirmed_partial",
    broker_order_ids: ["ORDER-2"],
    broker_order_item_indexes: [1],
    not_applied_item_indexes: [0],
    note: "Verified the split result in the broker order book",
    evidence_digest: "digest-1",
    status: "PENDING_AUDIT",
    prepared_at: "2026-07-15T09:35:00+00:00",
    ...overrides,
  };
}

function makeResolutionResult(
  outcome: ReconciliationResolutionOutcome,
  overrides: Partial<ResolveReconciliationOutcomeResult> = {},
): ResolveReconciliationOutcomeResult {
  return {
    resolution_id: "resolution-1",
    attempt_id: "attempt-123",
    outcome,
    status: "COMMITTED",
    evidence_digest: "digest-1",
    router_fault_cleared: true,
    writes_unblocked: true,
    remaining_outcomes: 0,
    ...overrides,
  };
}

function makeResolutionHttpError(
  status: "PENDING_AUDIT" | "PENDING_ROUTER_CLEAR" | "COMMITTED",
  outcome: ReconciliationResolutionOutcome,
): Error {
  const resolution = makePendingResolution({ status, outcome });
  return Object.assign(new Error(`Outcome finalisation remains ${status}`), {
    status: 503,
    data: {
      attempt_id: "attempt-123",
      resolution_id: resolution.resolution_id,
      status,
      resolution,
    },
  });
}

function makePendingHttpError(
  status: "PENDING_AUDIT" | "PENDING_ROUTER_CLEAR",
  outcome: ReconciliationResolutionOutcome,
): Error {
  return makeResolutionHttpError(status, outcome);
}

function makeCommittedHttpError(
  outcome: ReconciliationResolutionOutcome,
): Error {
  return makeResolutionHttpError("COMMITTED", outcome);
}

function resolutionFromTestError(
  error: Error,
  expectedAttemptId: string,
): ReconciliationErrorResolution | null {
  if (!("data" in error)) return null;
  const data = (error as Error & { data?: unknown }).data;
  if (data === null || typeof data !== "object") return null;
  const record = data as { attempt_id?: unknown; resolution?: unknown };
  if (
    record.attempt_id !== expectedAttemptId ||
    record.resolution === null ||
    typeof record.resolution !== "object"
  )
    return null;
  return {
    attempt_id: expectedAttemptId,
    resolution: record.resolution as ReconciliationPendingResolution,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ReconciliationWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMutate.mockReset();
    mockResolveMutate.mockReset();
    reconciliationHookMode.realOutcomes = false;
    reconciliationHookMode.realResolve = false;
    currentMode = "explore";
    useAuthStore.setState({
      status: "logged-in",
      username: "operator-1",
      token: "test-token",
      sessionGeneration: 1,
    });
    mockUseReconciliationStatus.mockReturnValue(
      queryResult({ data: makeStatus() }),
    );
    mockUseReconciliationReports.mockReturnValue(queryResult({ data: [] }));
    mockUseRunReconciliation.mockReturnValue({
      mutate: mockMutate,
      isPending: false,
    });
    mockUseReconciliationOutcomes.mockReturnValue(
      queryResult({ data: { count: 0, outcomes: [] } }),
    );
    mockUseResolveReconciliationOutcome.mockImplementation(
      (callbacks: ResolveReconciliationOutcomeCallbacks = {}) => ({
        mutate: (variables: ResolveReconciliationOutcomeVariables) =>
          mockResolveMutate(variables, {
            onSuccess: (result: ResolveReconciliationOutcomeResult) =>
              callbacks.onSuccess?.(result, variables),
            onError: (error: Error) =>
              callbacks.onError?.(
                error,
                variables,
                resolutionFromTestError(error, variables.attemptId),
              ),
          }),
        isPending: false,
        error: null,
        reset: mockResolveReset,
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists unresolved attempts and blocks resolution outside Live mode", () => {
    mockUseReconciliationOutcomes.mockReturnValue(
      queryResult({ data: { count: 1, outcomes: [makeOutcome()] } }),
    );

    render(<ReconciliationWidget {...defaultProps} />);

    expect(screen.getByText("Unknown order outcomes")).toBeInTheDocument();
    expect(screen.getByText("attempt-123")).toBeInTheDocument();
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    const resolveButton = screen.getByRole("button", {
      name: "Resolve attempt attempt-123",
    });
    expect(resolveButton).toBeDisabled();
    fireEvent.click(resolveButton);
    expect(mockResolveMutate).not.toHaveBeenCalled();
  });

  it("derives an open resolution target from live query data by attempt ID", () => {
    currentMode = "live";
    let liveOutcomes = [makeOutcome()];
    mockUseReconciliationOutcomes.mockImplementation(() =>
      queryResult({
        data: { count: liveOutcomes.length, outcomes: liveOutcomes },
      }),
    );
    const { rerender } = render(<ReconciliationWidget {...defaultProps} />);

    fireEvent.click(
      screen.getByRole("button", { name: "Resolve attempt attempt-123" }),
    );
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "dhan account ACC1",
    );

    liveOutcomes = [makeOutcome({ adapter_id: "upstox", account_id: "ACC2" })];
    rerender(
      <ReconciliationWidget
        {...makeWidgetPanelProps({ params: { revision: 1 } })}
      />,
    );
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "upstox account ACC2",
    );

    liveOutcomes = [];
    rerender(
      <ReconciliationWidget
        {...makeWidgetPanelProps({ params: { revision: 2 } })}
      />,
    );
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("keeps unsupported operation evidence visibly fail-closed", () => {
    currentMode = "live";
    mockUseReconciliationOutcomes.mockReturnValue(
      queryResult({
        data: {
          count: 1,
          outcomes: [
            makeOutcome({
              operation: "place_conditional_trigger",
              recovery_supported_outcomes: [],
              recovery_blocked_reason:
                "No operation-specific broker evidence is recorded for this write type; the outcome remains fail-closed.",
            }),
          ],
        },
      }),
    );

    render(<ReconciliationWidget {...defaultProps} />);

    expect(screen.getByText("Evidence unavailable")).toBeInTheDocument();
    const blocked = screen.getByRole("button", {
      name: "Resolve attempt attempt-123",
    });
    expect(blocked).toBeDisabled();
    expect(blocked).toHaveTextContent("Blocked");
  });

  it("keeps migrated recovery positive-only and communicates the restriction", () => {
    currentMode = "live";
    const reason =
      "Broker identity history is incomplete after ledger migration; " +
      "negative and partial-negative recovery remain fail-closed.";
    mockUseReconciliationOutcomes.mockReturnValue(
      queryResult({
        data: {
          count: 1,
          outcomes: [
            makeOutcome({
              recovery_supported_outcomes: ["confirmed_applied"],
              recovery_blocked_reason: reason,
            }),
          ],
        },
      }),
    );

    render(<ReconciliationWidget {...defaultProps} />);

    expect(screen.getByText("Recovery restricted")).toHaveAttribute(
      "title",
      reason,
    );
    const resolve = screen.getByRole("button", {
      name: "Resolve attempt attempt-123",
    });
    expect(resolve).toBeEnabled();
    expect(resolve).toHaveAttribute("title", reason);
    fireEvent.click(resolve);

    expect(screen.getByRole("status")).toHaveTextContent(reason);
    expect(
      screen.getByRole("button", { name: "Confirmed applied" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Confirmed not applied" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Confirmed partial" }),
    ).toBeDisabled();
  });

  it("requires full applied child evidence, exact selector confirmation, and refreshes orders", () => {
    currentMode = "live";
    mockUseReconciliationOutcomes.mockReturnValue(
      queryResult({
        data: {
          count: 1,
          outcomes: [
            makeOutcome({
              operation: "place_multi_order",
              items: [
                makeOutcomeItem(0, "RELIANCE", {
                  variety: "amo",
                  validity: "IOC",
                  strategy: "momentum",
                }),
                makeOutcomeItem(1, "TCS"),
              ],
            }),
          ],
        },
      }),
    );
    mockResolveMutate.mockImplementation(
      (
        variables: { body: { outcome: ReconciliationResolutionOutcome } },
        options?: {
          onSuccess?: (result: ResolveReconciliationOutcomeResult) => void;
        },
      ) => options?.onSuccess?.(makeResolutionResult(variables.body.outcome)),
    );

    render(<ReconciliationWidget {...defaultProps} />);

    fireEvent.click(
      screen.getByRole("button", { name: "Resolve attempt attempt-123" }),
    );
    expect(mockUseResolveReconciliationOutcome).toHaveBeenCalledWith(
      expect.objectContaining({
        onError: expect.any(Function),
        onSuccess: expect.any(Function),
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirmed applied" }));

    const submit = screen.getByRole("button", {
      name: "Confirm resolution for attempt attempt-123",
    });
    expect(screen.getAllByLabelText(/Broker order ID \d/)).toHaveLength(2);
    expect(
      screen.getByText(
        "RELIANCE · NSE · MIS · BUY 1 · price 1500 · MARKET · trigger 0 · variety amo · validity IOC · strategy momentum",
      ),
    ).toBeInTheDocument();
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Broker order ID 1"), {
      target: { value: "ORDER-1" },
    });
    fireEvent.change(screen.getByLabelText("Broker order ID 2"), {
      target: { value: "ORDER-2" },
    });
    const confirmation = screen.getByLabelText(
      "Type CONFIRM APPLIED dhan:ACC1:attempt-123 to resolve",
    );
    fireEvent.change(confirmation, {
      target: { value: "CONFIRM APPLIED dhan:ACC1:another-attempt" },
    });
    expect(submit).toBeDisabled();

    fireEvent.change(confirmation, {
      target: { value: "CONFIRM APPLIED dhan:ACC1:attempt-123" },
    });
    fireEvent.change(screen.getByLabelText("Operator note (optional)"), {
      target: { value: "Verified both child orders in the broker order book" },
    });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    expect(mockResolveMutate).toHaveBeenCalledWith(
      {
        attemptId: "attempt-123",
        body: {
          broker: "dhan",
          account_id: "ACC1",
          business_date: "2026-07-15",
          outcome: "confirmed_applied",
          broker_order_ids: ["ORDER-1", "ORDER-2"],
          broker_order_item_indexes: [0, 1],
          not_applied_item_indexes: [],
          confirmation: "CONFIRM APPLIED dhan:ACC1:attempt-123",
          note: "Verified both child orders in the broker order book",
        },
      },
      expect.objectContaining({
        onError: expect.any(Function),
        onSuccess: expect.any(Function),
      }),
    );
    expect(mockEmitOrdersChanged).toHaveBeenCalledTimes(1);
  });

  it("refreshes orders when an applied resolution settles as PENDING_AUDIT via HTTP 503", () => {
    currentMode = "live";
    mockUseReconciliationOutcomes.mockReturnValue(
      queryResult({ data: { count: 1, outcomes: [makeOutcome()] } }),
    );
    mockResolveMutate.mockImplementation(
      (_variables: unknown, options?: { onError?: (error: Error) => void }) =>
        options?.onError?.(
          makePendingHttpError("PENDING_AUDIT", "confirmed_applied"),
        ),
    );
    render(<ReconciliationWidget {...defaultProps} />);

    fireEvent.click(
      screen.getByRole("button", { name: "Resolve attempt attempt-123" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirmed applied" }));
    fireEvent.change(screen.getByLabelText("Broker order ID 1"), {
      target: { value: "ORDER-1" },
    });
    fireEvent.change(
      screen.getByLabelText(
        "Type CONFIRM APPLIED dhan:ACC1:attempt-123 to resolve",
      ),
      { target: { value: "CONFIRM APPLIED dhan:ACC1:attempt-123" } },
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Confirm resolution for attempt attempt-123",
      }),
    );

    expect(mockEmitOrdersChanged).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alert")).toHaveTextContent("PENDING_AUDIT");
  });

  it("keeps a pending-resolution error visible across the real outcomes-cache remount", async () => {
    currentMode = "live";
    reconciliationHookMode.realOutcomes = true;
    reconciliationHookMode.realResolve = true;
    const initialOutcome = makeOutcome({
      recovery_supported_outcomes: [
        "confirmed_applied",
        "confirmed_not_applied",
      ],
    });
    const pendingResolution = makePendingResolution({
      outcome: "confirmed_applied",
      broker_order_ids: ["ORDER-1"],
      broker_order_item_indexes: [],
      not_applied_item_indexes: [],
      note: "",
      status: "PENDING_AUDIT",
    });
    const pendingOutcome = makeOutcome({
      recovery_supported_outcomes: [
        "confirmed_applied",
        "confirmed_not_applied",
      ],
      resolution: pendingResolution,
    });
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (
        init?.method === "POST" &&
        url.includes("/reconciliation/outcomes/attempt-123/resolve")
      ) {
        return Promise.resolve(
          makeJsonResponse(
            {
              status: "error",
              message: "Outcome finalisation remains PENDING_AUDIT",
              data: {
                attempt_id: "attempt-123",
                resolution_id: pendingResolution.resolution_id,
                status: pendingResolution.status,
                resolution: pendingResolution,
              },
            },
            503,
          ),
        );
      }
      if (url.includes("/reconciliation/outcomes")) {
        return Promise.resolve(
          makeJsonResponse({
            status: "success",
            data: { count: 1, outcomes: [pendingOutcome] },
          }),
        );
      }
      return Promise.reject(new Error(`Unexpected request: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);
    const queryClient = makeQueryClient();
    queryClient.setQueryData<ReconciliationOutcomesResult>(
      reconciliationKeys.outcomes("operator-1"),
      { count: 1, outcomes: [initialOutcome] },
    );

    render(
      <QueryClientProvider client={queryClient}>
        <ReconciliationWidget {...defaultProps} />
      </QueryClientProvider>,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Resolve attempt attempt-123" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirmed applied" }));
    fireEvent.change(screen.getByLabelText("Broker order ID 1"), {
      target: { value: "ORDER-1" },
    });
    fireEvent.change(
      screen.getByLabelText(
        "Type CONFIRM APPLIED dhan:ACC1:attempt-123 to resolve",
      ),
      { target: { value: "CONFIRM APPLIED dhan:ACC1:attempt-123" } },
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Confirm resolution for attempt attempt-123",
      }),
    );

    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Retry outcome finalisation" }),
      ).toBeInTheDocument();
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Outcome finalisation remains PENDING_AUDIT",
    );
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/reconciliation/outcomes/attempt-123/resolve"),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("does not render Resolve for negative placement evidence from the real query path", async () => {
    currentMode = "live";
    reconciliationHookMode.realOutcomes = true;
    const malformedOutcome = makeOutcome({
      price: -1,
      recovery_supported_outcomes: [
        "confirmed_applied",
        "confirmed_not_applied",
      ],
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          makeJsonResponse({
            status: "success",
            data: { count: 1, outcomes: [malformedOutcome] },
          }),
        ),
      ),
    );

    render(
      <QueryClientProvider client={makeQueryClient()}>
        <ReconciliationWidget {...defaultProps} />
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText(
        "Failed to load unknown outcomes: Reconciliation outcomes response is malformed",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Resolve attempt attempt-123" }),
    ).not.toBeInTheDocument();
  });

  it("submits an explicit applied/not-applied child partition for a partial basket", () => {
    currentMode = "live";
    mockUseReconciliationOutcomes.mockReturnValue(
      queryResult({
        data: {
          count: 1,
          outcomes: [
            makeOutcome({
              operation: "place_multi_order",
              items: [
                makeOutcomeItem(0, "RELIANCE"),
                makeOutcomeItem(1, "TCS", {
                  exchange: "BSE",
                  product: "CNC",
                  action: "SELL",
                  quantity: 2,
                  price: 3500,
                  price_type: "SL-LMT",
                  trigger_price: 3450,
                  variety: "iceberg",
                  validity: "IOC",
                  strategy: "pairs",
                }),
                makeOutcomeItem(2, "INFY"),
              ],
            }),
          ],
        },
      }),
    );
    mockResolveMutate.mockImplementation(
      (
        variables: { body: { outcome: ReconciliationResolutionOutcome } },
        options?: {
          onSuccess?: (result: ResolveReconciliationOutcomeResult) => void;
        },
      ) => options?.onSuccess?.(makeResolutionResult(variables.body.outcome)),
    );

    render(<ReconciliationWidget {...defaultProps} />);
    fireEvent.click(
      screen.getByRole("button", { name: "Resolve attempt attempt-123" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirmed partial" }));

    expect(
      screen.getByText(
        "TCS · BSE · CNC · SELL 2 · price 3500 · SL-LMT · trigger 3450 · variety iceberg · validity IOC · strategy pairs",
      ),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Mark child 1 applied" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Mark child 2 not applied" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Mark child 3 applied" }),
    );
    fireEvent.change(screen.getByLabelText("Broker order ID 1"), {
      target: { value: "ORDER-1" },
    });
    fireEvent.change(screen.getByLabelText("Broker order ID 3"), {
      target: { value: "ORDER-3" },
    });
    expect(
      screen.queryByLabelText("Broker order ID 2"),
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Operator note (required)"), {
      target: {
        value: "Verified one rejected child and two accepted children",
      },
    });
    fireEvent.change(
      screen.getByLabelText(
        "Type CONFIRM PARTIAL dhan:ACC1:attempt-123 to resolve",
      ),
      { target: { value: "CONFIRM PARTIAL dhan:ACC1:attempt-123" } },
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Confirm resolution for attempt attempt-123",
      }),
    );

    expect(mockResolveMutate).toHaveBeenCalledWith(
      {
        attemptId: "attempt-123",
        body: {
          broker: "dhan",
          account_id: "ACC1",
          business_date: "2026-07-15",
          outcome: "confirmed_partial",
          broker_order_ids: ["ORDER-1", "ORDER-3"],
          broker_order_item_indexes: [0, 2],
          not_applied_item_indexes: [1],
          confirmation: "CONFIRM PARTIAL dhan:ACC1:attempt-123",
          note: "Verified one rejected child and two accepted children",
        },
      },
      expect.any(Object),
    );
    expect(mockEmitOrdersChanged).toHaveBeenCalledTimes(1);
  });

  it("refreshes orders when a partial resolution settles as PENDING_ROUTER_CLEAR via HTTP 503", () => {
    currentMode = "live";
    mockUseReconciliationOutcomes.mockReturnValue(
      queryResult({
        data: {
          count: 1,
          outcomes: [
            makeOutcome({
              operation: "place_multi_order",
              items: [
                makeOutcomeItem(0, "RELIANCE"),
                makeOutcomeItem(1, "TCS"),
              ],
            }),
          ],
        },
      }),
    );
    mockResolveMutate.mockImplementation(
      (_variables: unknown, options?: { onError?: (error: Error) => void }) =>
        options?.onError?.(
          makePendingHttpError("PENDING_ROUTER_CLEAR", "confirmed_partial"),
        ),
    );
    render(<ReconciliationWidget {...defaultProps} />);

    fireEvent.click(
      screen.getByRole("button", { name: "Resolve attempt attempt-123" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirmed partial" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Mark child 1 applied" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Mark child 2 not applied" }),
    );
    fireEvent.change(screen.getByLabelText("Broker order ID 1"), {
      target: { value: "ORDER-1" },
    });
    fireEvent.change(screen.getByLabelText("Operator note (required)"), {
      target: { value: "Verified the split result at the broker" },
    });
    fireEvent.change(
      screen.getByLabelText(
        "Type CONFIRM PARTIAL dhan:ACC1:attempt-123 to resolve",
      ),
      { target: { value: "CONFIRM PARTIAL dhan:ACC1:attempt-123" } },
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Confirm resolution for attempt attempt-123",
      }),
    );

    expect(mockEmitOrdersChanged).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alert")).toHaveTextContent("PENDING_ROUTER_CLEAR");
  });

  it("refreshes from the canonical pending outcome when another tab recorded a different decision", () => {
    currentMode = "live";
    mockUseReconciliationOutcomes.mockReturnValue(
      queryResult({ data: { count: 1, outcomes: [makeOutcome()] } }),
    );
    mockResolveMutate.mockImplementation(
      (_variables: unknown, options?: { onError?: (error: Error) => void }) =>
        options?.onError?.(
          makePendingHttpError("PENDING_ROUTER_CLEAR", "confirmed_applied"),
        ),
    );
    render(<ReconciliationWidget {...defaultProps} />);

    fireEvent.click(
      screen.getByRole("button", { name: "Resolve attempt attempt-123" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Confirmed not applied" }),
    );
    fireEvent.change(screen.getByLabelText("Operator note (required)"), {
      target: { value: "No order was visible in this tab" },
    });
    fireEvent.change(
      screen.getByLabelText(
        "Type CONFIRM NOT_APPLIED dhan:ACC1:attempt-123 to resolve",
      ),
      { target: { value: "CONFIRM NOT_APPLIED dhan:ACC1:attempt-123" } },
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Confirm resolution for attempt attempt-123",
      }),
    );

    expect(mockEmitOrdersChanged).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alert")).toHaveTextContent("PENDING_ROUTER_CLEAR");
  });

  it("clears confirmation on decision change and sends every rejected child index", () => {
    currentMode = "live";
    mockUseReconciliationOutcomes.mockReturnValue(
      queryResult({
        data: {
          count: 1,
          outcomes: [
            makeOutcome({
              operation: "place_multi_order",
              items: [
                makeOutcomeItem(0, "RELIANCE"),
                makeOutcomeItem(1, "TCS"),
              ],
            }),
          ],
        },
      }),
    );
    render(<ReconciliationWidget {...defaultProps} />);

    fireEvent.click(
      screen.getByRole("button", { name: "Resolve attempt attempt-123" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirmed applied" }));
    fireEvent.change(
      screen.getByLabelText(
        "Type CONFIRM APPLIED dhan:ACC1:attempt-123 to resolve",
      ),
      { target: { value: "CONFIRM APPLIED dhan:ACC1:attempt-123" } },
    );
    fireEvent.change(screen.getByLabelText("Broker order ID 1"), {
      target: { value: "STALE-1" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Confirmed not applied" }),
    );

    const confirmation = screen.getByLabelText(
      "Type CONFIRM NOT_APPLIED dhan:ACC1:attempt-123 to resolve",
    );
    expect(confirmation).toHaveValue("");
    expect(
      screen.queryByLabelText("Broker order ID 1"),
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Operator note (required)"), {
      target: { value: "Verified neither child exists at the broker" },
    });
    fireEvent.change(confirmation, {
      target: { value: "CONFIRM NOT_APPLIED dhan:ACC1:attempt-123" },
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: "Confirm resolution for attempt attempt-123",
      }),
    );

    expect(mockResolveMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.objectContaining({
          outcome: "confirmed_not_applied",
          broker_order_ids: [],
          broker_order_item_indexes: [],
          not_applied_item_indexes: [0, 1],
          confirmation: "CONFIRM NOT_APPLIED dhan:ACC1:attempt-123",
        }),
      }),
      expect.any(Object),
    );
    expect(mockEmitOrdersChanged).not.toHaveBeenCalled();
  });

  it.each(["PENDING_AUDIT", "PENDING_ROUTER_CLEAR"] as const)(
    "locks %s evidence and exposes only retry finalisation",
    (status) => {
      currentMode = "live";
      const resolution = makePendingResolution({ status });
      mockUseReconciliationOutcomes.mockReturnValue(
        queryResult({
          data: {
            count: 1,
            outcomes: [
              makeOutcome({
                operation: "place_multi_order",
                items: [
                  makeOutcomeItem(0, "RELIANCE"),
                  makeOutcomeItem(1, "TCS"),
                ],
                resolution,
              }),
            ],
          },
        }),
      );
      render(<ReconciliationWidget {...defaultProps} />);

      fireEvent.click(
        screen.getByRole("button", {
          name: "Retry finalisation for attempt attempt-123",
        }),
      );

      expect(
        screen.getByText(
          `Finalisation is ${status}. The recorded decision and evidence are locked; ` +
            "this action only retries audit/finalisation and router clearance.",
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Confirmed partial" }),
      ).toBeDisabled();
      expect(
        screen.getByRole("button", { name: "Mark child 1 not applied" }),
      ).toBeDisabled();
      expect(
        screen.getByRole("button", { name: "Mark child 2 applied" }),
      ).toBeDisabled();
      expect(screen.getByLabelText("Broker order ID 2")).toBeDisabled();
      expect(screen.getByLabelText("Broker order ID 2")).toHaveValue("ORDER-2");
      expect(screen.getByLabelText("Operator note (optional)")).toBeDisabled();

      fireEvent.change(
        screen.getByLabelText(
          "Type CONFIRM PARTIAL dhan:ACC1:attempt-123 to retry finalisation",
        ),
        { target: { value: "CONFIRM PARTIAL dhan:ACC1:attempt-123" } },
      );
      fireEvent.click(
        screen.getByRole("button", {
          name: "Confirm retry finalisation for attempt attempt-123",
        }),
      );

      expect(mockResolveMutate).toHaveBeenCalledWith(
        {
          attemptId: "attempt-123",
          body: {
            broker: "dhan",
            account_id: "ACC1",
            business_date: "2026-07-15",
            outcome: "confirmed_partial",
            broker_order_ids: ["ORDER-2"],
            broker_order_item_indexes: [1],
            not_applied_item_indexes: [0],
            confirmation: "CONFIRM PARTIAL dhan:ACC1:attempt-123",
            note: "Verified the split result in the broker order book",
          },
        },
        expect.any(Object),
      );
    },
  );

  it("adopts a newly pending immutable decision while the dialog is open", () => {
    currentMode = "live";
    let liveOutcome = makeOutcome({
      operation: "place_multi_order",
      items: [makeOutcomeItem(0, "RELIANCE"), makeOutcomeItem(1, "TCS")],
    });
    mockUseReconciliationOutcomes.mockImplementation(() =>
      queryResult({ data: { count: 1, outcomes: [liveOutcome] } }),
    );
    const { rerender } = render(<ReconciliationWidget {...defaultProps} />);

    fireEvent.click(
      screen.getByRole("button", { name: "Resolve attempt attempt-123" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirmed applied" }));
    fireEvent.change(screen.getByLabelText("Broker order ID 1"), {
      target: { value: "STALE-DRAFT" },
    });

    liveOutcome = {
      ...liveOutcome,
      resolution: makePendingResolution({ status: "PENDING_AUDIT" }),
    };
    rerender(
      <ReconciliationWidget
        {...makeWidgetPanelProps({ params: { refreshGeneration: 1 } })}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Retry outcome finalisation" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Confirmed partial" }),
    ).toBeDisabled();
    expect(screen.getByLabelText("Broker order ID 2")).toHaveValue("ORDER-2");
    expect(screen.queryByDisplayValue("STALE-DRAFT")).not.toBeInTheDocument();
  });

  it("treats a committed HTTP error as a completed state-changing resolution", () => {
    currentMode = "live";
    mockUseReconciliationOutcomes.mockReturnValue(
      queryResult({ data: { count: 1, outcomes: [makeOutcome()] } }),
    );
    mockResolveMutate.mockImplementation(
      (_variables: unknown, options?: { onError?: (error: Error) => void }) =>
        options?.onError?.(makeCommittedHttpError("confirmed_applied")),
    );
    render(<ReconciliationWidget {...defaultProps} />);

    fireEvent.click(
      screen.getByRole("button", { name: "Resolve attempt attempt-123" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirmed applied" }));
    fireEvent.change(screen.getByLabelText("Broker order ID 1"), {
      target: { value: "BROKER-1" },
    });
    fireEvent.change(
      screen.getByLabelText(
        "Type CONFIRM APPLIED dhan:ACC1:attempt-123 to resolve",
      ),
      { target: { value: "CONFIRM APPLIED dhan:ACC1:attempt-123" } },
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Confirm resolution for attempt attempt-123",
      }),
    );

    expect(mockEmitOrdersChanged).toHaveBeenCalledTimes(1);
    expect(mockEmitNotification).toHaveBeenCalledWith({
      category: "system",
      title: "Order outcome resolved",
      body: "The durable decision was committed. Reconciliation status is refreshing.",
    });
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("does not offer applied recovery for a multi-order with no persisted children", () => {
    currentMode = "live";
    mockUseReconciliationOutcomes.mockReturnValue(
      queryResult({
        data: {
          count: 1,
          outcomes: [
            makeOutcome({ operation: "place_multi_order", items: [] }),
          ],
        },
      }),
    );
    render(<ReconciliationWidget {...defaultProps} />);

    fireEvent.click(
      screen.getByRole("button", { name: "Resolve attempt attempt-123" }),
    );

    expect(
      screen.getByRole("button", { name: "Confirmed applied" }),
    ).toBeDisabled();
    expect(
      screen.getByText(
        "Applied recovery is unavailable without persisted child intents.",
      ),
    ).toBeInTheDocument();
  });

  it("keeps the dialog open and displays backend refusal text verbatim", () => {
    const refusal =
      "Live mode is locked — verify your PIN to unlock live trading";
    currentMode = "live";
    mockUseReconciliationOutcomes.mockReturnValue(
      queryResult({ data: { count: 1, outcomes: [makeOutcome()] } }),
    );
    mockResolveMutate.mockImplementation(
      (_variables: unknown, options?: { onError?: (error: Error) => void }) =>
        options?.onError?.(new Error(refusal)),
    );
    render(<ReconciliationWidget {...defaultProps} />);

    fireEvent.click(
      screen.getByRole("button", { name: "Resolve attempt attempt-123" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Confirmed not applied" }),
    );
    fireEvent.change(screen.getByLabelText("Operator note (required)"), {
      target: { value: "Verified no matching broker order" },
    });
    fireEvent.change(
      screen.getByLabelText(
        "Type CONFIRM NOT_APPLIED dhan:ACC1:attempt-123 to resolve",
      ),
      {
        target: { value: "CONFIRM NOT_APPLIED dhan:ACC1:attempt-123" },
      },
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Confirm resolution for attempt attempt-123",
      }),
    );

    expect(screen.getByRole("alert")).toHaveTextContent(refusal);
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });

  it("reports a committed resolution without claiming writes are unblocked", () => {
    currentMode = "live";
    mockUseReconciliationOutcomes.mockReturnValue(
      queryResult({ data: { count: 1, outcomes: [makeOutcome()] } }),
    );
    mockResolveMutate.mockImplementation(
      (
        _variables: unknown,
        options?: {
          onSuccess?: (result: ResolveReconciliationOutcomeResult) => void;
        },
      ) =>
        options?.onSuccess?.(
          makeResolutionResult("confirmed_not_applied", {
            writes_unblocked: false,
            remaining_outcomes: 1,
          }),
        ),
    );
    render(<ReconciliationWidget {...defaultProps} />);

    fireEvent.click(
      screen.getByRole("button", { name: "Resolve attempt attempt-123" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Confirmed not applied" }),
    );
    fireEvent.change(screen.getByLabelText("Operator note (required)"), {
      target: { value: "Verified no matching broker order" },
    });
    fireEvent.change(
      screen.getByLabelText(
        "Type CONFIRM NOT_APPLIED dhan:ACC1:attempt-123 to resolve",
      ),
      { target: { value: "CONFIRM NOT_APPLIED dhan:ACC1:attempt-123" } },
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Confirm resolution for attempt attempt-123",
      }),
    );

    expect(mockEmitNotification).toHaveBeenCalledWith({
      category: "alert",
      title: "Order outcome resolved",
      body: "The resolution was committed. Normal writes remain blocked by 1 unresolved outcome.",
    });
  });

  it("renders the honest empty state when no native sessions are active", () => {
    render(<ReconciliationWidget {...defaultProps} />);

    expect(
      screen.getByText("No reconciliation reports yet"),
    ).toBeInTheDocument();
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
      screen.getByText(
        "The runner is active — the first cycle will appear here shortly.",
      ),
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
    expect(mockUseReconciliationReports).toHaveBeenCalledWith(
      "dhan",
      "ACC1",
      1,
      true,
    );
    expect(screen.getByText("NIFTY24JUNFUT")).toBeInTheDocument();
    expect(screen.getByText(/exists_only_on_broker/)).toBeInTheDocument();
    expect(screen.getByText(/flinttrade 0 vs broker 50/)).toBeInTheDocument();
  });

  it("shows the broker fetch error honestly in the expanded report", () => {
    mockUseReconciliationStatus.mockReturnValue(
      queryResult({
        data: makeStatus({
          runner_active: true,
          targets: [
            makeTarget({
              clean: false,
              severity: "critical",
              error: "timeout",
            }),
          ],
        }),
      }),
    );
    mockUseReconciliationReports.mockReturnValue(
      queryResult({
        data: [
          makeReport({
            clean: false,
            severity: "critical",
            error: "HTTP 502 from broker",
          }),
        ],
      }),
    );
    render(<ReconciliationWidget {...defaultProps} />);

    fireEvent.click(
      screen.getByRole("button", { name: /show latest report for dhan ACC1/i }),
    );

    expect(
      screen.getByText(
        /Broker fetch failed — broker state unknown: HTTP 502 from broker/,
      ),
    ).toBeInTheDocument();
  });

  it("triggers the run mutation when 'Reconcile now' is clicked", () => {
    render(<ReconciliationWidget {...defaultProps} />);

    fireEvent.click(screen.getByRole("button", { name: "Reconcile now" }));

    expect(mockMutate).toHaveBeenCalledTimes(1);
  });

  it("disables the button and shows progress while the run is pending", () => {
    mockUseRunReconciliation.mockReturnValue({
      mutate: mockMutate,
      isPending: true,
    });
    render(<ReconciliationWidget {...defaultProps} />);

    const button = screen.getByRole("button", { name: "Reconcile now" });
    expect(button).toBeDisabled();
    expect(screen.getByText("Reconciling…")).toBeInTheDocument();
  });

  it("emits an honest alert notification when the run fails", () => {
    mockMutate.mockImplementation(
      (_vars: unknown, options?: { onError?: (err: Error) => void }) => {
        options?.onError?.(
          new Error(
            "Reconciliation runner not active — no native broker sessions to reconcile",
          ),
        );
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
      queryResult({
        isError: true,
        error: new Error("backend down"),
        refetch: mockRefetch,
      }),
    );
    render(<ReconciliationWidget {...defaultProps} />);

    expect(
      screen.getByText(/failed to load reconciliation status/i),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(mockRefetch).toHaveBeenCalledTimes(1);
  });
});
