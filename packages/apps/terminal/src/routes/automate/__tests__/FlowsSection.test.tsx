import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/tools/FlowBuilder/FlowBuilderTool", () => ({
  default: () => <div data-testid="canonical-flow-builder">Flow Builder</div>,
}));

import FlowsSection from "../FlowsSection";

describe("FlowsSection", () => {
  it("mounts the canonical functional flow builder", () => {
    render(<FlowsSection />);

    expect(screen.getByTestId("canonical-flow-builder")).toBeInTheDocument();
    expect(screen.getByText("Flow Builder")).toBeInTheDocument();
  });
});
