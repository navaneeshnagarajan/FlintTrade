import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { OperatorStatusStrip } from "../OperatorStatusStrip";
import { classifyOperatorSignals, type OperatorSignals } from "@/lib/operatorIncident";

function signals(overrides: Partial<OperatorSignals> = {}): OperatorSignals {
  return {
    feedDisconnected: false,
    localPing: "ok",
    transportReason: null,
    health: "healthy",
    publicSite: "ok",
    nativeHttpFreeze: false,
    brokerRateLimited: false,
    brokerReject: {
      message: "Trading halted by exchange circuit breaker",
      httpStatus: 400,
      broker: "dhan",
    },
    activeAccount: null,
    wsFailure: null,
    llmChrome: "ready",
    sessionClockClosed: true,
    ...overrides,
  };
}

describe("OperatorStatusStrip", () => {
  it("names the exchange class and the rectify line under the strip", () => {
    const incident = classifyOperatorSignals(signals());
    expect(incident?.failureClass).toBe("exchange");
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <OperatorStatusStrip kind="exchange" incident={incident} />
      </QueryClientProvider>,
    );
    const strip = screen.getByTestId("incident-strip");
    expect(strip).toHaveAttribute("data-strip-level", "blocked");
    expect(strip).toHaveAttribute("data-failure-class", "exchange");
    expect(strip).toHaveTextContent("Blocked");
    expect(strip).toHaveTextContent(/exchange/i);
    expect(screen.getByTestId("operator-rectify")).toHaveTextContent(/cannot reverse a reject/i);
    expect(strip).not.toHaveTextContent("Connected");
  });
});
