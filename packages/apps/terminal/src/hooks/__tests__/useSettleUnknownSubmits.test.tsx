import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { clearPersistedAuthSession, writePersistedAuthSession } from "@/lib/homeEntry";
import { clearPendingOrderOutcomes } from "@/lib/pendingOrderStore";
import { useSettleUnknownSubmits } from "@/hooks/useOrderSubmitGuard";
import {
  UNKNOWN_SUBMIT_SETTLE_MS,
  orderSubmitLocked,
  submitOrderOnce,
} from "@/lib/orderSubmitGuard";

const SCOPE = "live:upstox:U1";
const INTENT = { key: "NFO:NIFTY10APR2625000CE", symbol: "NIFTY10APR2625000CE", exchange: "NFO", action: "BUY" as const };
const lost = () => Promise.reject(new TypeError("Failed to fetch"));

function Probe({ isFetching, dataUpdatedAt, listComplete }: { isFetching: boolean; dataUpdatedAt: number; listComplete: boolean }) {
  useSettleUnknownSubmits(SCOPE, isFetching, dataUpdatedAt, listComplete);
  return <div>{orderSubmitLocked(SCOPE, INTENT.key) ? "locked" : "open"}</div>;
}

describe("useSettleUnknownSubmits", () => {
  beforeEach(() => {
    sessionStorage.clear();
    writePersistedAuthSession({ token: "operator-session", username: "operator", expiresAt: "" });
    clearPendingOrderOutcomes();
  });

  afterEach(() => {
    clearPendingOrderOutcomes();
    clearPersistedAuthSession();
    sessionStorage.clear();
  });

  it("keeps the lock when a normal-speed empty read starts immediately", async () => {
    await expect(submitOrderOnce(SCOPE, INTENT, lost)).rejects.toThrow();
    const startedAt = Date.now();
    const view = render(<Probe isFetching={true} dataUpdatedAt={0} listComplete={false} />);
    expect(screen.getByText("locked")).toBeInTheDocument();
    await act(async () => {
      view.rerender(<Probe isFetching={false} dataUpdatedAt={startedAt + 25} listComplete={true} />);
    });
    expect(screen.getByText("locked")).toBeInTheDocument();
    expect(orderSubmitLocked(SCOPE, INTENT.key)).toBe(true);
  });

  it("keeps the lock when an empty read starts immediately and finishes about 2s later", async () => {
    await expect(submitOrderOnce(SCOPE, INTENT, lost)).rejects.toThrow();
    const receivedAt = Date.now();
    const view = render(<Probe isFetching={true} dataUpdatedAt={0} listComplete={false} />);
    expect(screen.getByText("locked")).toBeInTheDocument();
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 2_000)); });
    const completedAt = Date.now();
    expect(completedAt - receivedAt).toBeGreaterThanOrEqual(1_800);
    expect(completedAt - receivedAt).toBeLessThan(UNKNOWN_SUBMIT_SETTLE_MS);
    await act(async () => {
      view.rerender(<Probe isFetching={false} dataUpdatedAt={completedAt} listComplete={true} />);
    });
    expect(screen.getByText("locked")).toBeInTheDocument();
    expect(orderSubmitLocked(SCOPE, INTENT.key)).toBe(true);
  }, 10_000);

  it("unlocks on a complete read that started after the settle delay", async () => {
    await expect(submitOrderOnce(SCOPE, INTENT, lost)).rejects.toThrow();
    const receivedAt = Date.now();
    const view = render(<Probe isFetching={false} dataUpdatedAt={0} listComplete={false} />);
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, UNKNOWN_SUBMIT_SETTLE_MS + 50)); });
    expect(screen.getByText("locked")).toBeInTheDocument();
    await act(async () => {
      view.rerender(<Probe isFetching={true} dataUpdatedAt={0} listComplete={false} />);
    });
    expect(Date.now()).toBeGreaterThanOrEqual(receivedAt + UNKNOWN_SUBMIT_SETTLE_MS);
    await act(async () => {
      view.rerender(<Probe isFetching={false} dataUpdatedAt={Date.now()} listComplete={true} />);
    });
    expect(screen.getByText("open")).toBeInTheDocument();
    expect(orderSubmitLocked(SCOPE, INTENT.key)).toBe(false);
  }, 15_000);
});
