import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

import { DemoBanner, SAMPLE_DATA_BANNER } from "./DemoBanner";
import { useModeStore } from "@/stores/modeStore";

describe("DemoBanner", () => {
  beforeEach(() => {
    useModeStore.setState({ mode: "explore" });
  });

  it("uses the sample-data sentence", () => {
    render(<DemoBanner />);
    expect(screen.getByText(SAMPLE_DATA_BANNER)).toBeInTheDocument();
  });

  it("never shows the sample-data sentence in Practice", () => {
    useModeStore.setState({ mode: "practice" });
    render(<DemoBanner />);
    expect(screen.queryByText(SAMPLE_DATA_BANNER)).not.toBeInTheDocument();
  });

  it("keeps a caller-specific sentence in Practice", () => {
    useModeStore.setState({ mode: "practice" });
    render(
      <DemoBanner message="The built-in tax ledger is illustrative; live tax-history ingestion is not wired." />,
    );
    expect(
      screen.getByText("The built-in tax ledger is illustrative; live tax-history ingestion is not wired."),
    ).toBeInTheDocument();
  });
});
