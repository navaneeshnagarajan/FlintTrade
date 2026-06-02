import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const repoRoot = path.resolve(process.cwd(), "../../..");

function readRepoFile(relativePath: string): string {
  return readFileSync(path.join(repoRoot, relativePath), "utf8");
}

function assertImportsSharedDesignSystemCss(source: string): void {
  expect(source).toContain('@import "@flinttrade/design-system/tokens.css"');
  expect(source).toContain('@import "@flinttrade/design-system/glass.css"');
  expect(source).toContain('@import "@flinttrade/design-system/cinematic.css"');
}

describe("design-system extraction contract", () => {
  it("has terminal consume shared tokens, glass, and cinematic CSS from core", () => {
    const terminalCss = readRepoFile("packages/apps/terminal/src/index.css");

    assertImportsSharedDesignSystemCss(terminalCss);
    expect(terminalCss).toContain('@import "./terminal.css"');
    expect(terminalCss).toContain('@source "../../../core/design-system/src/**/*.{ts,tsx,css}"');
    expect(terminalCss).toContain('@source "../../../core/design-system/src/components/**/*.{ts,tsx}"');
  });

  it("has site consume shared tokens, glass, and cinematic CSS from core", () => {
    const siteCss = readRepoFile("packages/apps/site/src/app/globals.css");

    expect(siteCss).toContain("@import '@flinttrade/design-system/tokens.css'");
    expect(siteCss).toContain("@import '@flinttrade/design-system/glass.css'");
    expect(siteCss).toContain("@import '@flinttrade/design-system/cinematic.css'");
    expect(siteCss).toContain("@source '../../../../core/design-system/src/**/*.{ts,tsx,css}'");
    expect(siteCss).toContain("@source '../../../../core/design-system/src/components/**/*.{ts,tsx}'");
  });

  it("keeps shared font imports out of design-system token CSS", () => {
    const tokensCss = readRepoFile("packages/core/design-system/src/tokens.css");

    expect(tokensCss).not.toContain('@import "tailwindcss"');
    expect(tokensCss).not.toContain("@fontsource-variable/");
    expect(tokensCss).not.toContain("@font-face");
  });

  it("keeps terminal-only chrome rules out of shared token CSS", () => {
    const tokensCss = readRepoFile("packages/core/design-system/src/tokens.css");
    const terminalCss = readRepoFile("packages/apps/terminal/src/terminal.css");

    for (const terminalOnlySelector of [
      ".dockview-theme-dark",
      ".dockview-theme-light",
      "[data-separator]",
      "body {",
      "*:focus-visible",
      "ring-scale-in",
    ]) {
      expect(tokensCss).not.toContain(terminalOnlySelector);
      expect(terminalCss).toContain(terminalOnlySelector);
    }
  });
});
