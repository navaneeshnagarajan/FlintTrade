/**
 * GlossaryTooltip.test.tsx
 *
 * Tests for the GlossaryTooltip component.
 * Verifies tooltip rendering, missing-term passthrough, and accessibility.
 */

import { describe, it, expect, beforeAll } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { GlossaryTooltip } from "../GlossaryTooltip";

// Radix Tooltip uses ResizeObserver internally
beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("GlossaryTooltip", () => {
  it("renders children text", () => {
    render(<GlossaryTooltip term="SIP">SIP</GlossaryTooltip>);
    expect(screen.getByText("SIP")).toBeInTheDocument();
  });

  it("renders with dotted underline for known terms", () => {
    render(<GlossaryTooltip term="VIX">VIX</GlossaryTooltip>);
    const trigger = screen.getByText("VIX");
    expect(trigger.tagName).toBe("SPAN");
    expect(trigger.className).toContain("underline");
    expect(trigger.className).toContain("decoration-dotted");
    expect(trigger.className).toContain("cursor-help");
  });

  it("renders children without wrapper for unknown terms", () => {
    const { container } = render(
      <GlossaryTooltip term="NONEXISTENT_TERM">Plain Text</GlossaryTooltip>,
    );
    expect(screen.getByText("Plain Text")).toBeInTheDocument();
    // Should NOT have the underline wrapper span
    const spans = container.querySelectorAll("span.underline");
    expect(spans.length).toBe(0);
  });

  it("shows tooltip content on hover", async () => {
    render(<GlossaryTooltip term="STT">STT</GlossaryTooltip>);

    const trigger = screen.getByText("STT");
    fireEvent.pointerEnter(trigger);
    fireEvent.focus(trigger);

    // Tooltip content should appear (Radix renders it in a portal)
    await waitFor(() => {
      const tooltip = screen.getByRole("tooltip");
      expect(tooltip).toBeInTheDocument();
      expect(tooltip.textContent).toContain("Securities Transaction Tax");
    });
  });

  it("accepts ReactNode children", () => {
    render(
      <GlossaryTooltip term="LTCG">
        <strong>LTCG</strong>
      </GlossaryTooltip>,
    );
    expect(screen.getByText("LTCG")).toBeInTheDocument();
  });
});
