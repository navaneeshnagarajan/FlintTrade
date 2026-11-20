import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { SummaryView } from "../SummaryView";

const funds = { availableCash: 1000, usedMargin: 0, totalBalance: 1000 };

describe("SummaryView Muhurat funds note", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the settlement-holiday funds note during the F&O window", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-08T09:30:00.000Z")); // 15:00 IST
    render(<SummaryView positions={[]} funds={funds} netPnL={0} />);
    expect(screen.getByTestId("muhurat-funds-note")).toHaveTextContent(
      "not included in available funds",
    );
    expect(screen.getByTestId("muhurat-funds-note")).toHaveTextContent("6 November 2026");
    expect(screen.getByTestId("muhurat-funds-note")).toHaveTextContent("settlement holiday");
  });

  it("hides the funds note outside the F&O window", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-08T04:30:00.000Z")); // 10:00 IST
    render(<SummaryView positions={[]} funds={funds} netPnL={0} />);
    expect(screen.queryByTestId("muhurat-funds-note")).not.toBeInTheDocument();
  });
});
