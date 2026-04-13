/**
 * Logo.test.tsx
 *
 * Tests for the FlintTrade Logo brand component.
 * Verifies rendering, size props, variant props, and accessibility.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Logo, LogoIcon, LogoWordmark, SIZE_PX } from "../Logo";
import type { LogoSize } from "../Logo";

// ---------------------------------------------------------------------------
// LogoIcon
// ---------------------------------------------------------------------------

describe("LogoIcon", () => {
  it("renders an SVG with the icon aria-label by default", () => {
    const { container } = render(<LogoIcon />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute("aria-label")).toBe("FlintTrade icon");
  });

  it("renders at md size (24px) by default", () => {
    const { container } = render(<LogoIcon />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("width")).toBe("24");
    expect(svg.getAttribute("height")).toBe("24");
  });

  it("renders at sm size (16px)", () => {
    const { container } = render(<LogoIcon size="sm" />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("width")).toBe("16");
  });

  it("renders at lg size (36px)", () => {
    const { container } = render(<LogoIcon size="lg" />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("width")).toBe("36");
  });

  it("accepts a numeric size", () => {
    const { container } = render(<LogoIcon size={48} />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("width")).toBe("48");
  });

  it("uses white fill for dark variant", () => {
    const { container } = render(<LogoIcon variant="dark" />);
    const rects = container.querySelectorAll("rect");
    // All F-letterform rects should use #ffffff
    rects.forEach((r) => expect(r.getAttribute("fill")).toBe("#ffffff"));
  });

  it("uses black fill for light variant", () => {
    const { container } = render(<LogoIcon variant="light" />);
    const rects = container.querySelectorAll("rect");
    rects.forEach((r) => expect(r.getAttribute("fill")).toBe("#0a0a0f"));
  });

  it("uses currentColor for auto variant", () => {
    const { container } = render(<LogoIcon variant="auto" />);
    const rects = container.querySelectorAll("rect");
    rects.forEach((r) => expect(r.getAttribute("fill")).toBe("currentColor"));
  });

  it("spark polygon always uses brand green (#22c55e)", () => {
    const { container } = render(<LogoIcon variant="dark" />);
    const polygons = container.querySelectorAll("polygon");
    // First polygon is the main spark
    expect(polygons[0].getAttribute("fill")).toBe("#22c55e");
  });

  it("hides from accessibility tree when aria-hidden is set", () => {
    const { container } = render(<LogoIcon aria-hidden />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("role")).toBe("presentation");
    expect(svg.getAttribute("aria-label")).toBeNull();
  });

  it("applies custom className", () => {
    const { container } = render(<LogoIcon className="my-class" />);
    expect(container.querySelector(".my-class")).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// LogoWordmark
// ---------------------------------------------------------------------------

describe("LogoWordmark", () => {
  it("renders the FlintTrade text", () => {
    render(<LogoWordmark />);
    expect(screen.getByText("FlintTrade")).toBeDefined();
  });

  it("has aria-label 'FlintTrade wordmark'", () => {
    const { container } = render(<LogoWordmark />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("aria-label")).toBe("FlintTrade wordmark");
  });

  it("scales width proportionally with size", () => {
    const { container: cMd } = render(<LogoWordmark size="md" />);
    const { container: cLg } = render(<LogoWordmark size="lg" />);
    const wMd = Number(cMd.querySelector("svg")!.getAttribute("width"));
    const wLg = Number(cLg.querySelector("svg")!.getAttribute("width"));
    expect(wLg).toBeGreaterThan(wMd);
  });
});

// ---------------------------------------------------------------------------
// Logo (combined)
// ---------------------------------------------------------------------------

describe("Logo", () => {
  it("renders full variant by default (icon + wordmark)", () => {
    const { container } = render(<Logo />);
    // Full variant renders a span wrapping both icon and wordmark
    const span = container.querySelector("span[role='img']");
    expect(span).not.toBeNull();
    expect(span?.getAttribute("aria-label")).toBe("FlintTrade");
  });

  it("renders icon-only variant", () => {
    const { container } = render(<Logo variant="icon" />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("aria-label")).toBe("FlintTrade icon");
  });

  it("renders wordmark-only variant", () => {
    render(<Logo variant="wordmark" />);
    expect(screen.getByText("FlintTrade")).toBeDefined();
  });

  it("passes colorVariant down to children", () => {
    const { container } = render(<Logo colorVariant="dark" />);
    const rects = container.querySelectorAll("rect");
    rects.forEach((r) => expect(r.getAttribute("fill")).toBe("#ffffff"));
  });

  it("applies className to root span in full variant", () => {
    const { container } = render(<Logo className="logo-root" />);
    expect(container.querySelector(".logo-root")).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// SIZE_PX constant
// ---------------------------------------------------------------------------

describe("SIZE_PX", () => {
  const sizes: LogoSize[] = ["sm", "md", "lg"];
  it("has entries for all size presets", () => {
    for (const s of sizes) {
      expect(typeof SIZE_PX[s]).toBe("number");
    }
  });

  it("sizes are strictly increasing sm < md < lg", () => {
    expect(SIZE_PX.sm).toBeLessThan(SIZE_PX.md);
    expect(SIZE_PX.md).toBeLessThan(SIZE_PX.lg);
  });
});
