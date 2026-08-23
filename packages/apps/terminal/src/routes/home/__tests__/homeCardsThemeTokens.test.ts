import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const homeDir = join(process.cwd(), "src/routes/home");
const bentoDir = join(process.cwd(), "src/components/bento");

const darkOnlyTokens = [
  "#e8e8f0",
  "#9090b0",
  "#505068",
  "#6b6b8a",
  "rgba(255,255,255",
];

describe("home dashboard theme tokens", () => {
  it("does not hard-code dark-mode text and glass colours", () => {
    const offenders = readdirSync(homeDir)
      .filter((file) => file.endsWith(".tsx"))
      .flatMap((file) => {
        const content = readFileSync(join(homeDir, file), "utf8");
        return darkOnlyTokens
          .filter((token) => content.includes(token))
          .map((token) => `${file}: ${token}`);
      });

    expect(offenders).toEqual([]);
  });

  it("keeps dashboard cards visible without relying on entrance animation", () => {
    const offenders = ["BentoCard.tsx", "AddWidgetCard.tsx"]
      .filter((file) => readFileSync(join(bentoDir, file), "utf8").includes("initial={{ opacity: 0"))
      .map((file) => `${file}: initial opacity 0`);

    expect(offenders).toEqual([]);
  });

  it("overlays home widget chrome so resize/remove controls do not steal card height", () => {
    const frame = readFileSync(join(homeDir, "HomeWidgetFrame.tsx"), "utf8");
    expect(frame).toContain("home-widget-toolbar");
    expect(frame).toContain("absolute top-1.5 right-1.5");
    // Hover-reveal is limited to fine pointers; coarse/touch keeps the
    // toolbar visible so drag / resize / remove stay tappable.
    expect(frame).toContain("@media (hover: hover) and (pointer: fine)");
    expect(frame).toContain(".home-widget-frame:focus-within .home-widget-toolbar");
    expect(frame).not.toContain("pointer-events-none");
    expect(frame).not.toContain("group-hover:opacity-100");
  });
});
