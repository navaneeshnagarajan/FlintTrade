/**
 * PriceAlertNode.test.tsx
 *
 * Unit tests for the PriceAlertNode canvas component and the registry
 * additions that support the 10 Price Alert conditions.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ReactFlowProvider } from "@xyflow/react";
import { PriceAlertNode } from "../PriceAlertNode";
import {
  PRICE_ALERT_CONDITIONS,
  CHANNEL_CONDITIONS,
  PERCENT_CONDITIONS,
  NODE_DESCRIPTORS,
  NODE_TYPE_TO_CATEGORY,
  NODE_TYPE_TO_LABEL,
} from "../../nodeRegistry";

// ---------------------------------------------------------------------------
// Registry tests
// ---------------------------------------------------------------------------

describe("nodeRegistry — priceAlert descriptor", () => {
  it("registers priceAlert in NODE_DESCRIPTORS", () => {
    expect(NODE_DESCRIPTORS.has("priceAlert")).toBe(true);
  });

  it("is categorised as triggers", () => {
    expect(NODE_TYPE_TO_CATEGORY.get("priceAlert")).toBe("triggers");
  });

  it("has label 'Price Alert'", () => {
    expect(NODE_TYPE_TO_LABEL.get("priceAlert")).toBe("Price Alert");
  });

  it("descriptor has no inputs (trigger node)", () => {
    const descriptor = NODE_DESCRIPTORS.get("priceAlert")!;
    expect(descriptor.inputs).toHaveLength(0);
  });

  it("descriptor has one output handle", () => {
    const descriptor = NODE_DESCRIPTORS.get("priceAlert")!;
    expect(descriptor.outputs).toHaveLength(1);
    expect(descriptor.outputs[0].id).toBe("out");
  });

  it("descriptor includes all 7 config fields", () => {
    const descriptor = NODE_DESCRIPTORS.get("priceAlert")!;
    const keys = descriptor.fields.map((f) => f.key);
    expect(keys).toContain("symbol");
    expect(keys).toContain("exchange");
    expect(keys).toContain("condition");
    expect(keys).toContain("price");
    expect(keys).toContain("priceUpper");
    expect(keys).toContain("pctValue");
    expect(keys).toContain("cooldownSecs");
  });

  it("condition field has 10 options", () => {
    const descriptor = NODE_DESCRIPTORS.get("priceAlert")!;
    const conditionField = descriptor.fields.find((f) => f.key === "condition")!;
    expect(conditionField.options).toHaveLength(10);
  });

  it("PRICE_ALERT_CONDITIONS list has 10 entries", () => {
    expect(PRICE_ALERT_CONDITIONS).toHaveLength(10);
  });

  it("CHANNEL_CONDITIONS contains the 4 channel types", () => {
    expect(CHANNEL_CONDITIONS.has("enteringChannel")).toBe(true);
    expect(CHANNEL_CONDITIONS.has("exitingChannel")).toBe(true);
    expect(CHANNEL_CONDITIONS.has("insideChannel")).toBe(true);
    expect(CHANNEL_CONDITIONS.has("outsideChannel")).toBe(true);
    expect(CHANNEL_CONDITIONS.size).toBe(4);
  });

  it("PERCENT_CONDITIONS contains movingUpPct and movingDownPct", () => {
    expect(PERCENT_CONDITIONS.has("movingUpPct")).toBe(true);
    expect(PERCENT_CONDITIONS.has("movingDownPct")).toBe(true);
    expect(PERCENT_CONDITIONS.size).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// Component render tests
// ---------------------------------------------------------------------------

const defaultData = {
  label: "Price Alert",
  nodeType: "priceAlert",
  color: "#f59e0b",
  config: {} as Record<string, string>,
};

function renderNode(config: Record<string, string> = {}, label = "Price Alert") {
  const data = { ...defaultData, label, config };
  return render(
    <ReactFlowProvider>
      <PriceAlertNode data={data} selected={false} />
    </ReactFlowProvider>
  );
}

describe("PriceAlertNode rendering", () => {
  it("renders the Price Alert header", () => {
    renderNode();
    expect(screen.getByText(/price alert/i)).toBeDefined();
  });

  it("shows symbol when configured", () => {
    renderNode({ symbol: "NIFTY", exchange: "NFO", condition: "crossingUp", price: "22000" });
    expect(screen.getByText("NIFTY")).toBeDefined();
  });

  it("shows exchange badge", () => {
    renderNode({ symbol: "BANKNIFTY", exchange: "NFO", condition: "greaterThan", price: "50000" });
    expect(screen.getByText("NFO")).toBeDefined();
  });

  it("shows condition label", () => {
    renderNode({ condition: "crossingDown", price: "21000" });
    expect(screen.getByText(/crossing down/i)).toBeDefined();
  });

  it("shows price value for threshold conditions", () => {
    renderNode({ condition: "greaterThan", price: "22500" });
    expect(screen.getByText("22500")).toBeDefined();
  });

  it("shows percentage value for percent conditions", () => {
    renderNode({ condition: "movingUpPct", pctValue: "2.5" });
    expect(screen.getByText("2.5%")).toBeDefined();
  });

  it("shows channel range for channel conditions", () => {
    renderNode({ condition: "insideChannel", price: "21000", priceUpper: "22000" });
    expect(screen.getByText("21000 – 22000")).toBeDefined();
  });

  it("shows cooldown when > 0", () => {
    renderNode({ condition: "crossingUp", price: "22000", cooldownSecs: "120" });
    expect(screen.getByText(/cooldown: 120s/i)).toBeDefined();
  });

  it("does not show cooldown row when cooldown is 0", () => {
    renderNode({ condition: "crossingUp", price: "22000", cooldownSecs: "0" });
    expect(screen.queryByText(/cooldown/i)).toBeNull();
  });

  it("shows custom label when different from default", () => {
    renderNode({ condition: "crossingUp", price: "22000" }, "My Alert");
    expect(screen.getByText("My Alert")).toBeDefined();
  });

  it("renders with accessible aria-label on the node group", () => {
    renderNode({ condition: "greaterThan", price: "50000" }, "Trigger 1");
    expect(screen.getByRole("group", { name: /Price Alert node: Trigger 1/i })).toBeDefined();
  });
});
