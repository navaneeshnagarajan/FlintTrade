/** Independent presentation tests. Read/write hooks are mocked; readiness is unverified. */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import type { BrokerOrderRow } from "@/lib/brokerOrdersApi";

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

const state = vi.hoisted(() => ({
  mode: "live",
  target: { broker: "dhan", account_id: "A" } as { broker: string; account_id: string } | null,
  list: {} as Record<string, unknown>,
  place: {} as Record<string, unknown>,
  modify: {} as Record<string, unknown>,
  cancel: {} as Record<string, unknown>,
  cancelRequest: vi.fn(),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (value: { mode: string }) => unknown) => selector({ mode: state.mode }),
}));
vi.mock("@/lib/brokerOrdersApi", () => ({
  useForeverOrders: () => state.list,
  usePlaceForeverOrder: () => state.place,
  useModifyForeverOrder: () => state.modify,
  useCancelForeverOrder: () => state.cancel,
}));
vi.mock("./OrdersManagerShared", async () => {
  const guards = await import("@/lib/orderGuards");
  const pickField = (row: BrokerOrderRow, keys: string[]) => {
    const key = keys.find((candidate) => row[candidate] !== undefined && row[candidate] !== null);
    return key ? String(row[key]) : "—";
  };
  return {
    parsePriceValue: guards.parsePriceValue,
    parseWholeNumber: guards.parseWholeNumber,
    pickField,
    extractRowId: (row: BrokerOrderRow, keys: string[]) => {
      const value = pickField(row, keys);
      return value === "—" ? null : value;
    },
    useResolvedLotSize: () => ({ lotSize: 75, verified: true }),
    useSupportedNativeBrokerOrderTarget: () => [state.target, vi.fn()],
    BrokerTargetSelect: () => null,
    LiveModeNotice: () => <p>Live-broker constructs</p>,
    BrokerOrdersErrorNotice: ({ error }: { error: unknown }) =>
      <p role="alert">{error instanceof Error ? error.message : "Broker refusal"}</p>,
    BrokerRowsTable: ({ rows, columns, renderActions, emptyMessage }: {
      rows: BrokerOrderRow[];
      columns: Array<{ header: string; keys: string[] }>;
      renderActions: (row: BrokerOrderRow) => ReactNode;
      emptyMessage: string;
    }) => <table aria-label="Forever orders"><tbody>
      {rows.length === 0 ? <tr><td>{emptyMessage}</td></tr> : rows.map((row, index) => <tr key={index}>
        {columns.map((column) => <td key={column.header}>{pickField(row, column.keys)}</td>)}
        <td>{renderActions(row)}</td>
      </tr>)}
    </tbody></table>,
  };
});

import ForeverOrdersWidget from "./ForeverOrdersWidget";

const ROW = {
  order_id: "TRIGGER-1", symbol: "NIFTY26OCT24000CE", exchange: "NFO", product: "NRML",
  action: "SELL", quantity: 75, status: "ACTIVE", trigger_price: 100, price: 100,
};
const OFFLINE_WARNING = "Your broker may execute this GTT while FlintTrade is offline. It could open or reverse a position if your position changes.";

beforeEach(() => {
  vi.spyOn(Date, "now").mockReturnValue(1000);
  state.mode = "live";
  state.target = { broker: "dhan", account_id: "A" };
  state.list = { data: [ROW], isSuccess: true, isLoading: false, isError: false, isFetching: false, fetchStatus: "idle", dataUpdatedAt: 100, refetch: vi.fn() };
  state.place = { isPending: false, isError: false, isSuccess: false, mutate: vi.fn() };
  state.modify = { isPending: false, isError: false, isSuccess: false, mutate: vi.fn() };
  state.cancelRequest.mockReset();
  state.cancel = { isPending: false, isError: false, isSuccess: false, mutate: state.cancelRequest };
});

afterEach(() => { vi.restoreAllMocks(); });

describe("ForeverOrdersWidget truthful presentation", () => {
  it("shows the exact offline-GTT warning without claiming external provenance", () => {
    render(<ForeverOrdersWidget />);
    expect(screen.getByText(OFFLINE_WARNING)).toBeInTheDocument();
    expect(screen.queryByText(/externally placed|external order/i)).not.toBeInTheDocument();
  });

  it("keeps returned non-equity rows visible", () => {
    render(<ForeverOrdersWidget />);
    expect(screen.getByText(ROW.symbol)).toBeInTheDocument();
  });

  it("cancellation acknowledgement alone does not remove a row", () => {
    const { rerender } = render(<ForeverOrdersWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(state.cancelRequest).toHaveBeenCalledWith({ broker: "dhan", account_id: "A", order_id: ROW.order_id });
    state.cancel = { ...state.cancel, isSuccess: true, variables: { broker: "dhan", account_id: "A", order_id: ROW.order_id } };
    rerender(<ForeverOrdersWidget />);
    const row = screen.getByText(ROW.symbol).closest("tr")!;
    expect(within(row).getByText("Cancel pending. This order may still fill.")).toBeInTheDocument();
    expect(within(row).getByText("ACTIVE")).toBeInTheDocument();
  });

  describe("cancellation ACK reconciliation", () => {
    function acknowledge() {
      state.cancel = {
        ...state.cancel, isSuccess: true, submittedAt: 500,
        variables: { broker: state.target!.broker, account_id: "A", order_id: ROW.order_id },
      };
    }

    it.each([
      { data: [] },
      { data: [{ ...ROW, order_id: "UNRELATED", status: "CANCELLED" }] },
      { data: undefined, isSuccess: false, isError: true, error: new Error("Listing unavailable") },
      { data: undefined, isSuccess: false, isLoading: true },
      { data: undefined, fetchStatus: "paused" },
    ])("retains a visible scoped cancellation warning when the row is absent: %j", (query) => {
      const { rerender } = render(<ForeverOrdersWidget />);
      acknowledge();
      rerender(<ForeverOrdersWidget />);
      state.list = { ...state.list, dataUpdatedAt: 2000, ...query };
      rerender(<ForeverOrdersWidget />);
      expect(screen.getByText("Cancel pending. This order may still fill.")).toBeInTheDocument();
      expect(screen.getByRole("alert", { name: `Cancellation for ${ROW.order_id}` })).toHaveTextContent(ROW.order_id);
      expect(screen.getByText("Trigger status does not confirm the outcome of any spawned order. Check broker positions and orders."))
        .toBeInTheDocument();
      expect(state.cancelRequest).not.toHaveBeenCalled();
      state.list = { ...state.list, data: [{ ...ROW, status: "CANCELLED", child_status: "UNKNOWN" }],
        isSuccess: true, isError: false, isLoading: false, fetchStatus: "idle", dataUpdatedAt: 3000 };
      rerender(<ForeverOrdersWidget />);
      expect(screen.queryByText("Cancel pending. This order may still fill.")).not.toBeInTheDocument();
      expect(screen.queryByText(/child closed|child filled|child cancelled/i)).not.toBeInTheDocument();
    });

    it.each(["dhan", "upstox"])("reconciles a fresh terminal trigger listing for %s", (broker) => {
      state.target = { broker, account_id: "A" };
      const { rerender } = render(<ForeverOrdersWidget />);
      acknowledge();
      rerender(<ForeverOrdersWidget />);
      expect(screen.getByText("Cancel pending. This order may still fill.")).toBeInTheDocument();
      state.list = { ...state.list, data: [{ ...ROW, status: "CANCELLED" }], dataUpdatedAt: 2000 };
      rerender(<ForeverOrdersWidget />);
      expect(screen.getByText("CANCELLED")).toBeInTheDocument();
      expect(screen.queryByText("Cancel pending. This order may still fill.")).not.toBeInTheDocument();
      expect(state.cancelRequest).not.toHaveBeenCalled();
    });

    it("does not erase the first unresolved cancellation when another trigger is acknowledged", () => {
      const { rerender } = render(<ForeverOrdersWidget />);
      acknowledge();
      rerender(<ForeverOrdersWidget />);
      state.cancel = { ...state.cancel, submittedAt: 600,
        variables: { broker: "dhan", account_id: "A", order_id: "TRIGGER-2" } };
      state.list = { ...state.list, data: [], dataUpdatedAt: 2000 };
      rerender(<ForeverOrdersWidget />);
      expect(screen.getByRole("alert", { name: `Cancellation for ${ROW.order_id}` })).toHaveTextContent("Cancel pending. This order may still fill.");
      expect(screen.getByRole("alert", { name: "Cancellation for TRIGGER-2" })).toHaveTextContent("Cancel pending. This order may still fill.");
      state.list = { ...state.list, data: [{ ...ROW, status: "CANCELLED" }], dataUpdatedAt: 3000 };
      rerender(<ForeverOrdersWidget />);
      expect(screen.queryByRole("alert", { name: `Cancellation for ${ROW.order_id}` })).not.toBeInTheDocument();
      expect(screen.getByRole("alert", { name: "Cancellation for TRIGGER-2" })).toBeInTheDocument();
    });

    it("contradictory trigger identities cannot reconcile a matching cancellation ACK", () => {
      const { rerender } = render(<ForeverOrdersWidget />);
      acknowledge();
      rerender(<ForeverOrdersWidget />);
      state.list = { ...state.list, data: [{ ...ROW, gtt_order_id: "OTHER-ID", status: "CANCELLED" }], dataUpdatedAt: 2000 };
      rerender(<ForeverOrdersWidget />);
      expect(screen.getByText("Cancel pending. This order may still fill.")).toBeInTheDocument();
    });

    it.each(["CANCELLED", "REJECTED", "EXPIRED"])(
      "reconciles %s without implying that a spawned child is terminal", (status) => {
        const { rerender } = render(<ForeverOrdersWidget />);
        acknowledge();
        rerender(<ForeverOrdersWidget />);
        state.list = { ...state.list, data: [{ ...ROW, status, child_order_id: "CHILD-1", child_status: "UNKNOWN" }], dataUpdatedAt: 2000 };
        rerender(<ForeverOrdersWidget />);
        expect(screen.getByText(status)).toBeInTheDocument();
        expect(screen.queryByText("Cancel pending. This order may still fill.")).not.toBeInTheDocument();
        expect(screen.getByText("Trigger status does not confirm the outcome of any spawned order. Check broker positions and orders."))
          .toBeInTheDocument();
        expect(screen.queryByText(/child closed|child filled|child cancelled/i)).not.toBeInTheDocument();
      },
    );

    it.each([
      { dataUpdatedAt: 100 },
      { dataUpdatedAt: 700 },
      { dataUpdatedAt: 2000, isSuccess: false, isError: true },
      { dataUpdatedAt: 2000, isSuccess: false, isLoading: true },
      { dataUpdatedAt: 2000, isFetching: true, fetchStatus: "fetching" },
      { dataUpdatedAt: 2000, fetchStatus: "paused" },
      { dataUpdatedAt: undefined },
    ])("does not reconcile from stale or unavailable terminal data: %j", (query) => {
      const { rerender } = render(<ForeverOrdersWidget />);
      acknowledge();
      rerender(<ForeverOrdersWidget />);
      state.list = { ...state.list, data: [{ ...ROW, status: "CANCELLED" }], ...query };
      rerender(<ForeverOrdersWidget />);
      expect(screen.getByText("Cancel pending. This order may still fill.")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    });

    it.each(["ACTIVE", "CANCEL_REQUESTED", "NOT_CANCELLED", "", "UNFAMILIAR_STATUS"])(
      "keeps executable or unknown trigger status %s pending after refresh", (status) => {
        const { rerender } = render(<ForeverOrdersWidget />);
        acknowledge();
        rerender(<ForeverOrdersWidget />);
        state.list = { ...state.list, data: [{ ...ROW, status }], dataUpdatedAt: 2000 };
        rerender(<ForeverOrdersWidget />);
        expect(screen.getByText("Cancel pending. This order may still fill.")).toBeInTheDocument();
      },
    );

    it("another account's fresh response cannot reconcile the original ACK", () => {
      const { rerender } = render(<ForeverOrdersWidget />);
      acknowledge();
      rerender(<ForeverOrdersWidget />);
      state.target = { broker: "dhan", account_id: "B" };
      state.list = { ...state.list, data: [{ ...ROW, status: "CANCELLED" }], dataUpdatedAt: 2000 };
      rerender(<ForeverOrdersWidget />);
      expect(screen.queryByText("Cancel pending. This order may still fill.")).not.toBeInTheDocument();
      state.target = { broker: "dhan", account_id: "A" };
      state.list = { ...state.list, dataUpdatedAt: 100 };
      rerender(<ForeverOrdersWidget />);
      expect(screen.getByText("Cancel pending. This order may still fill.")).toBeInTheDocument();
      state.list = { ...state.list, dataUpdatedAt: 3000 };
      rerender(<ForeverOrdersWidget />);
      expect(screen.queryByText("Cancel pending. This order may still fill.")).not.toBeInTheDocument();
    });

    it.each([{ account_id: "B" }, { broker: "upstox" }])(
      "explicitly cross-account terminal row cannot reconcile the ACK: %j", (scope) => {
        const { rerender } = render(<ForeverOrdersWidget />);
        acknowledge();
        rerender(<ForeverOrdersWidget />);
        state.list = { ...state.list, data: [{ ...ROW, status: "CANCELLED", ...scope }], dataUpdatedAt: 2000 };
        rerender(<ForeverOrdersWidget />);
        expect(screen.getByText("Cancel pending. This order may still fill.")).toBeInTheDocument();
        state.list = { ...state.list, data: [{ ...ROW, status: "CANCELLED", broker: "dhan", account_id: "A" }], dataUpdatedAt: 3000 };
        rerender(<ForeverOrdersWidget />);
        expect(screen.queryByText("Cancel pending. This order may still fill.")).not.toBeInTheDocument();
      },
    );

    it("terminal status for another identity cannot reconcile the matching ACK", () => {
      const { rerender } = render(<ForeverOrdersWidget />);
      acknowledge();
      rerender(<ForeverOrdersWidget />);
      state.list = { ...state.list, data: [ROW, { ...ROW, order_id: "TRIGGER-2", status: "CANCELLED" }], dataUpdatedAt: 2000 };
      rerender(<ForeverOrdersWidget />);
      const row = screen.getAllByText(ROW.symbol)[0].closest("tr")!;
      expect(within(row).getByText("Cancel pending. This order may still fill.")).toBeInTheDocument();
    });

    it.each([
      { rows: [{ ...ROW, status: "CANCELLED", order_status: "OPEN" }] },
      { rows: [{ ...ROW, status: "CANCELLED" }, ROW] },
    ])("conflicting terminal evidence cannot reconcile an ACK: %j", ({ rows }) => {
      const { rerender } = render(<ForeverOrdersWidget />);
      acknowledge();
      rerender(<ForeverOrdersWidget />);
      state.list = { ...state.list, data: rows, dataUpdatedAt: 2000 };
      rerender(<ForeverOrdersWidget />);
      expect(screen.getAllByText("Cancel pending. This order may still fill.").length).toBeGreaterThan(0);
    });

    it("does not resurrect a reconciled ACK from later error data", () => {
      const { rerender } = render(<ForeverOrdersWidget />);
      acknowledge();
      rerender(<ForeverOrdersWidget />);
      state.list = { ...state.list, data: [{ ...ROW, status: "EXPIRED" }], dataUpdatedAt: 2000 };
      rerender(<ForeverOrdersWidget />);
      expect(screen.queryByText("Cancel pending. This order may still fill.")).not.toBeInTheDocument();
      state.list = { ...state.list, isSuccess: false, isError: true, error: new Error("Listing unavailable") };
      rerender(<ForeverOrdersWidget />);
      expect(screen.queryByText("Cancel pending. This order may still fill.")).not.toBeInTheDocument();
      expect(screen.getByTestId("forever-orders-unavailable")).toBeInTheDocument();
    });
  });

  it("keeps broker cancel-pending rows visible", () => {
    state.list.data = [{ ...ROW, status: "CANCEL_REQUESTED" }];
    render(<ForeverOrdersWidget />);
    expect(screen.getByText(ROW.symbol)).toBeInTheDocument();
    expect(screen.getByText("Cancel pending. This order may still fill.")).toBeInTheDocument();
  });

  it("an unfamiliar trigger status cannot imply its spawned order is terminal", () => {
    state.list.data = [{ ...ROW, status: "NOT_CANCELLED", child_order_id: "CHILD-1" }];
    render(<ForeverOrdersWidget />);
    expect(screen.getByText("NOT_CANCELLED")).toBeInTheDocument();
    expect(screen.getByText("Trigger status does not confirm the outcome of any spawned order. Check broker positions and orders."))
      .toBeInTheDocument();
    expect(screen.queryByText(/order closed|order filled|order cancelled/i)).not.toBeInTheDocument();
  });

  it.each([
    { data: undefined, isLoading: true, isSuccess: false },
    { data: undefined, isError: true, isSuccess: false, error: new Error("Unsupported listing") },
    { data: [ROW], isError: true, isSuccess: false, error: new Error("DDPI warning remains relevant") },
    { data: undefined, isSuccess: false, fetchStatus: "paused" },
  ])("keeps unavailable orders distinct from empty orders: %j", (query) => {
    state.list = { ...state.list, ...query };
    const { rerender } = render(<ForeverOrdersWidget />);
    expect(screen.getByTestId("forever-orders-unavailable")).toBeInTheDocument();
    expect(screen.queryByText("No resting forever orders for this broker account.")).not.toBeInTheDocument();
    rerender(<ForeverOrdersWidget />);
    expect(screen.getByTestId("forever-orders-unavailable")).toBeInTheDocument();
    if (query.data?.length) expect(screen.getByText(ROW.symbol)).toBeInTheDocument();
  });

  it("does not describe acknowledgement as execution", () => {
    state.place = { ...state.place, isSuccess: true, variables: { broker: "dhan", account_id: "A" } };
    render(<ForeverOrdersWidget />);
    expect(screen.getByText("Forever order requested. Check broker triggers and orders for the outcome.")).toBeInTheDocument();
    expect(screen.queryByText(/it rests at the broker/)).not.toBeInTheDocument();
  });

  it("does not carry another account's warning or response into the active account", () => {
    const variables = { broker: "dhan", account_id: "A", order_id: ROW.order_id };
    state.place = { ...state.place, isSuccess: true, variables };
    state.cancel = { ...state.cancel, isSuccess: true, variables };
    state.modify = { ...state.modify, isError: true, variables, error: new Error("Account A refusal") };
    const { rerender } = render(<ForeverOrdersWidget />);
    expect(screen.getByText("Account A refusal")).toBeInTheDocument();
    state.target = { broker: "dhan", account_id: "B" };
    rerender(<ForeverOrdersWidget />);
    expect(screen.queryByText("Account A refusal")).not.toBeInTheDocument();
    expect(screen.queryByText("Cancel pending. This order may still fill.")).not.toBeInTheDocument();
    expect(screen.queryByText("Forever order requested. Check broker triggers and orders for the outcome.")).not.toBeInTheDocument();
  });

  it("does not let an old modify response close the active account's panel", () => {
    const mutate = vi.fn();
    state.modify = { ...state.modify, mutate };
    state.list.data = [{ ...ROW, pricetype: "LIMIT", validity: "DAY" }];
    const { rerender } = render(<ForeverOrdersWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Modify" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(mutate).toHaveBeenCalledTimes(1);
    const callbacks = mutate.mock.calls[0][1] as { onSuccess: () => void };
    state.target = { broker: "dhan", account_id: "B" };
    rerender(<ForeverOrdersWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Modify" }));
    expect(screen.getByRole("form", { name: "Modify forever order" })).toBeInTheDocument();
    act(() => callbacks.onSuccess());
    rerender(<ForeverOrdersWidget />);
    expect(screen.getByRole("form", { name: "Modify forever order" })).toBeInTheDocument();
  });

  describe.each(["place", "modify"] as const)("%s write outcomes", (operation) => {
    const warning = operation === "place"
      ? "GTT placement status unknown. A trigger or order may still execute."
      : "GTT modification status unknown. The trigger or order may still execute.";

    it.each([
      new TypeError("Failed to fetch"),
      Object.assign(new Error("Request timed out"), { status: 408 }),
      Object.assign(new Error("Broker server error"), { status: 500 }),
      Object.assign(new Error("Gateway timeout"), { status: 504 }),
    ])("shows an ambiguous outcome and preserves the raw detail: %j", (error) => {
      state[operation] = {
        ...state[operation], isError: true,
        variables: { broker: "dhan", account_id: "A" }, error,
      };
      const { rerender } = render(<ForeverOrdersWidget />);
      expect(screen.getByText(warning)).toBeInTheDocument();
      expect(screen.getByText(error.message)).toBeInTheDocument();
      expect(screen.getByText(ROW.symbol)).toBeInTheDocument();
      rerender(<ForeverOrdersWidget />);
      expect(screen.getByText(warning)).toBeInTheDocument();
      expect(state[operation].mutate).not.toHaveBeenCalled();
    });

    it.each([403, 422])("retains definite broker refusal detail for HTTP %s", (status) => {
      const error = Object.assign(new Error("DDPI authorisation required."), { status });
      state[operation] = {
        ...state[operation], isError: true,
        variables: { broker: "dhan", account_id: "A" }, error,
      };
      render(<ForeverOrdersWidget />);
      expect(screen.getByText(error.message)).toBeInTheDocument();
      expect(screen.queryByText(warning)).not.toBeInTheDocument();
      expect(state[operation].mutate).not.toHaveBeenCalled();
    });

    it("does not carry an uncertain response into another account", () => {
      state[operation] = {
        ...state[operation], isError: true,
        variables: { broker: "dhan", account_id: "A" }, error: new TypeError("Account A connection lost"),
      };
      const { rerender } = render(<ForeverOrdersWidget />);
      expect(screen.getByText(warning)).toBeInTheDocument();
      state.target = { broker: "dhan", account_id: "B" };
      rerender(<ForeverOrdersWidget />);
      expect(screen.queryByText(warning)).not.toBeInTheDocument();
      expect(screen.queryByText("Account A connection lost")).not.toBeInTheDocument();
    });
  });

  it("keeps a lost cancellation response uncertain and retains its details", () => {
    state.cancel = { ...state.cancel, isError: true, variables: { broker: "dhan", account_id: "A", order_id: ROW.order_id }, error: new TypeError("Connection lost") };
    render(<ForeverOrdersWidget />);
    expect(screen.getByText("Cancel status unknown. This order may still fill.")).toBeInTheDocument();
    expect(screen.getByText("Connection lost")).toBeInTheDocument();
    expect(screen.getByText(ROW.symbol)).toBeInTheDocument();
  });

  it("shows a verified empty book only after successful evidence", () => {
    state.list.data = [];
    render(<ForeverOrdersWidget />);
    expect(screen.getByText("No resting forever orders for this broker account.")).toBeInTheDocument();
    expect(screen.queryByTestId("forever-orders-unavailable")).not.toBeInTheDocument();
  });
});
