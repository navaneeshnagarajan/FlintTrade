import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { describe, expect, it } from "vitest";
import { ProvenanceBadge, type ProvenanceKind } from "../ProvenanceBadge";
import { DemoBadge } from "@/routes/home/DemoBadge";
import { readFileSync } from "fs";
import { join } from "path";
import { useModeStore } from "@/stores/modeStore";

const LABELS: ProvenanceKind[] = ["Sample", "Unavailable", "Live", "Stale"];

const DEFAULT_TITLES: Record<ProvenanceKind, string> = {
  Sample: "Sample data — not live",
  Unavailable: "Data unavailable",
  Live: "Live data",
  Stale: "Stale data — may be out of date",
};

describe("ProvenanceBadge (Slice 3 canonical atom)", () => {
  it.each(LABELS)("renders label %s with data-provenance and default title (corner)", (label) => {
    render(<ProvenanceBadge label={label} />);
    const badge = screen.getByTestId("provenance-badge");
    expect(badge).toHaveTextContent(label);
    expect(badge).toHaveAttribute("data-provenance", label);
    expect(badge).toHaveAttribute("title", DEFAULT_TITLES[label]);
    expect(badge.className).toMatch(/absolute/);
    expect(badge).not.toHaveAttribute("role", "status");
    expect(badge).not.toHaveAttribute("aria-live");
  });

  it.each(["explore", "practice", "live"] as const)("discloses inline Sample figures in %s", (mode) => {
    useModeStore.setState({ mode });
    render(<ProvenanceBadge label="Sample" placement="inline" />);
    expect(screen.getByText("Sample")).toHaveAttribute("data-provenance", "Sample");
    expect(screen.getByText("Sample")).toHaveAttribute("title", "Sample data — not live");
  });

  it("inline placement omits absolute positioning and uses inline test id", () => {
    render(<ProvenanceBadge label="Live" placement="inline" />);
    const badge = screen.getByTestId("provenance-badge-inline");
    expect(badge).toHaveTextContent("Live");
    expect(badge).toHaveAttribute("data-provenance", "Live");
    expect(badge.className).not.toMatch(/\babsolute\b/);
    expect(badge).not.toHaveAttribute("role", "status");
    expect(badge).not.toHaveAttribute("aria-live");
  });

  it("merges caller className, style, and testId without live-region semantics", () => {
    render(
      <ProvenanceBadge
        label="Live"
        className="extra-class"
        style={{ opacity: 0.8 }}
        testId="custom-badge"
        title="Custom title"
      />,
    );
    const badge = screen.getByTestId("custom-badge");
    expect(badge.className).toMatch(/extra-class/);
    expect(badge).toHaveStyle({ opacity: "0.8" });
    expect(badge).toHaveAttribute("title", "Custom title");
    expect(badge).toHaveAttribute("data-provenance", "Live");
    expect(badge).not.toHaveAttribute("role", "status");
    expect(badge).not.toHaveAttribute("aria-live");
  });

  it("canonical atom does not export DemoBadge (route shim owns the alias)", () => {
    const src = readFileSync(
      join(process.cwd(), "src", "components", "data", "ProvenanceBadge.tsx"),
      "utf8",
    );
    expect(src).toMatch(/export function ProvenanceBadge/);
    expect(src).not.toMatch(/export function DemoBadge/);
  });
});

describe("DemoBadge route compatibility shim", () => {
  it("retains the route alias and its explicit Sample default", () => {
    render(<DemoBadge />);
    expect(screen.getByTestId("home-demo-badge")).toHaveTextContent("Sample");
  });
});
