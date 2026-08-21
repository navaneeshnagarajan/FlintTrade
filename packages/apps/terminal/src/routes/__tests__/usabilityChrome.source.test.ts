/**
 * Pins the highest-impact visual/usability repairs so they cannot silently
 * regress to unreadable loaders, clipped dialogs, or a blank auth gate.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const srcRoot = join(process.cwd(), "src");

function read(rel: string): string {
  return readFileSync(join(srcRoot, rel), "utf8");
}

describe("terminal usability chrome", () => {
  it("keeps loading copy on a readable text token, not shadcn muted-surface", () => {
    const main = read("main.tsx");
    const gate = read("routes/ProtectedRoute.tsx");
    expect(main).toContain("text-text-muted");
    expect(main).not.toMatch(/(?<![-\w])text-muted(?![-\w])/);
    expect(gate).toContain("text-text-muted");
    expect(gate).not.toMatch(/(?<![-\w])text-muted(?![-\w])/);
    expect(gate).toContain("bg-surface-base");
  });

  it("shows a redirecting state instead of a blank unauthenticated page", () => {
    const gate = read("routes/ProtectedRoute.tsx");
    expect(gate).toContain("Redirecting to welcome");
    expect(gate).not.toMatch(/if \(!isAuthenticated\) return null;/);
  });

  it("keeps dialogs inside the viewport", () => {
    const dialog = read("components/ui/dialog.tsx");
    const alert = read("components/ui/alert-dialog.tsx");
    expect(dialog).toContain("max-h-[min(90dvh,calc(100%-2rem))]");
    expect(dialog).toContain("overflow-y-auto");
    expect(alert).toContain("max-h-[min(90dvh,calc(100%-2rem))]");
    expect(alert).toContain("overflow-y-auto");
  });

  it("centres short public pages without clipping tall setup forms", () => {
    const shell = read("components/layout/PublicRouteShell.tsx");
    expect(shell).toContain("my-auto w-full");
    expect(shell).not.toMatch(/flex-col items-center justify-center/);
  });

  it("gives FlexLayout tab bodies a definite height and a static focus ring", () => {
    const css = read("terminal.css");
    expect(css).toContain(".flexlayout__tab > *");
    expect(css).toContain("height: 100%");
    expect(css).toContain("outline: 2px solid var(--color-accent");
    expect(css).not.toContain("ring-scale-in");
    expect(css).toContain("var(--color-accent, hsl(var(--primary)))");
  });

  it("keeps the mode pill reachable when the top bar is crowded", () => {
    const topbar = read("chrome/TopBarV2.tsx");
    expect(topbar).toContain("overflow-x-auto");
    const modeIndex = topbar.indexOf("<ModeIndicator />");
    const clockIndex = topbar.indexOf("<ISTClock />");
    expect(modeIndex).toBeGreaterThan(0);
    expect(clockIndex).toBeGreaterThan(modeIndex);
  });
});
