/**
 * Unified app compatibility source guard.
 * Preserve legacy entry/shortcut access without restoring separate Home/Trade apps.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { personaDefaultRoute } from "@/lib/personaDefaultRoute";

const srcRoot = join(process.cwd(), "src");

function read(rel: string): string {
  return readFileSync(join(srcRoot, rel), "utf8");
}

function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
}

function walkTsx(dir: string, acc: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules" || entry.name === "__tests__") continue;
      walkTsx(full, acc);
      continue;
    }
    if (/\.tsx$/.test(entry.name) && !entry.name.includes(".test.")) {
      acc.push(full);
    }
  }
  return acc;
}

describe("Slice 2 Home vs Trade ownership — source guard", () => {
  it("command palette derives all canonical app commands without dummy legacy identities", () => {
    const src = stripComments(read("components/CommandPalette/useCommandRegistry.ts"));
    expect(src).toContain("APPS.map");
    expect(src).toContain("`nav:${app.id}`");
    expect(src).toContain("`Go to ${app.name}`");
    expect(src).toContain("path: app.path");
    expect(src).toContain('"Alt+T"');
    expect(src).not.toMatch(/nav:home|nav:trade/);
  });

  it("KeyboardShortcutsDialog documents Go to Home and Go to Trade", () => {
    const src = stripComments(read("components/KeyboardShortcuts/KeyboardShortcutsDialog.tsx"));
    expect(src).toMatch(/Go to Home/);
    expect(src).toMatch(/Go to Trade/);
    expect(src).toMatch(/["']Alt["']\s*,\s*["']H["']/);
    expect(src).toMatch(/["']Alt["']\s*,\s*["']T["']/);
  });

  it("useGlobalKeys implements Alt+H / Alt+T and AppLayout wires navigate callbacks", () => {
    const hook = stripComments(read("hooks/useGlobalKeys.ts"));
    const layout = stripComments(read("routes/AppLayout.tsx"));
    expect(hook).toMatch(/onGoHome/);
    expect(hook).toMatch(/onGoTrade/);
    expect(hook).toMatch(/altKey[\s\S]{0,100}[\"']h[\"']/i);
    expect(hook).toMatch(/altKey[\s\S]{0,100}[\"']t[\"']/i);
    expect(layout).toMatch(/useGlobalKeys\s*\(/);
    expect(layout).toMatch(/onGoHome\s*:/);
    expect(layout).toMatch(/onGoTrade\s*:/);
    expect(layout).toMatch(/navigate\(\s*[\"']\/home[\"']\s*\)/);
    expect(layout).toMatch(/navigate\(\s*[\"']\/trade[\"']\s*\)/);
    // Single mount only — no second useGlobalKeys import usage beyond the call.
    const mounts = layout.match(/useGlobalKeys\s*\(/g) ?? [];
    expect(mounts).toHaveLength(1);
  });

  it("TopBar logo targets /home not /trade", () => {
    const src = stripComments(read("chrome/TopBarV2.tsx"));
    expect(src).toMatch(/to=["']\/home["']/);
    expect(src).not.toMatch(/aria-label=["']Flint home["'][\s\S]{0,80}to=["']\/trade["']/);
    expect(src).not.toMatch(/to=["']\/trade["'][\s\S]{0,80}aria-label=["']Flint home["']/);
  });

  it("all persona inputs enter the unified Terminal compatibility route", () => {
    expect(personaDefaultRoute("trader")).toBe("/trade");
    expect(personaDefaultRoute("beginner")).toBe("/trade");
    expect(personaDefaultRoute("investor")).toBe("/trade");
    const setup = stripComments(read("routes/setup/applySetupChoices.ts"));
    expect(setup).toMatch(/personaDefaultRoute/);
  });

  it("Application owns canonical apps and legacy redirects behind the protected shell", () => {
    const src = stripComments(read("Application.tsx"));
    expect(read("main.tsx")).toContain('import("./Application")');
    expect(src).toContain("...APPS.map");
    expect(src).toContain("element: <LegacyAppRedirect />");
    expect(src).toContain("<ProtectedRoute><AppLayout /></ProtectedRoute>");
    expect(src).toContain("appPath(app) + location.search + location.hash");
    expect(src).toContain("location.state} replace");
    // Mounted alias/state/history assertions live in ApplicationCompatibility.navigation.
  });

  it("HomeRoute does not import Trade workspace chrome", () => {
    const src = stripComments(read("routes/HomeRoute.tsx"));
    expect(src).not.toMatch(/widgetFactory/);
    expect(src).not.toMatch(/flexLayoutAdapter/);
    expect(src).not.toMatch(/TradeBottomPanel/);
    expect(src).not.toMatch(/KillSwitchPill/);
  });

  it("TerminalRoute mounts TradeBottomPanel", () => {
    const src = stripComments(read("routes/TerminalRoute.tsx"));
    expect(src).toMatch(/TradeBottomPanel/);
  });

  it("routes/home production tsx has no order write paths", () => {
    const homeDir = join(srcRoot, "routes/home");
    const offenders: string[] = [];
    for (const full of walkTsx(homeDir)) {
      const text = stripComments(readFileSync(full, "utf8"));
      if (/placeOrder|assertNativeWriteTargetReadyOrThrow/.test(text)) {
        offenders.push(full.replace(srcRoot, "src"));
      }
    }
    expect(offenders).toEqual([]);
  });
});
