import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import AxeBuilder from "@axe-core/playwright";
import type { Locator, Page } from "@playwright/test";

import { expect } from "../fixture-registry";

/**
 * Fixed clock for every visual check. The runner timezone is UTC, matching
 * GitHub-hosted ubuntu-latest. Product clocks that name Asia/Kolkata stay on
 * that zone; this instant is only the frozen browser clock.
 */
export const FIXED_CLOCK = new Date("2026-01-15T09:30:00.000Z");

/** `Date#toDateString` for FIXED_CLOCK in UTC. */
export const GREETED_TODAY = "Thu Jan 15 2026";

export const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 2560, height: 1440 },
] as const;

export type Viewport = (typeof VIEWPORTS)[number];

const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] as const;

const HERE = path.dirname(fileURLToPath(import.meta.url));
const KNOWN_PATH = path.join(HERE, "known-axe-violations.json");

export interface AxeViolationSnap {
  id: string;
  impact: string | null;
  targets: string[];
}

export interface ScreenSnap {
  violations: AxeViolationSnap[];
  focus: string[];
}

type KnownFile = Record<string, ScreenSnap>;

/**
 * Laya chip copy the desk actually paints. The product has no Checking,
 * model-download, or model-version label on this chip.
 */
export const RENDERED_LAYA_LABELS = {
  ready: "Laya Ready",
  down: "Laya Down",
  degraded: "Laya Degraded",
} as const;

export const LAYA_COPY_NOT_RENDERED = [
  "Checking",
  "Downloading the model",
  "Can't verify the model",
  "Wrong model version",
] as const;

export async function installDeterminism(page: Page): Promise<void> {
  // Install the clock first. The init script below runs after it and swallows
  // the one-second Example feed and IST hand, which the clock would otherwise
  // keep moving under the screenshot.
  await page.clock.install({ time: FIXED_CLOCK });
  await page.addInitScript(() => {
    let seed = 0x6d2b79f5;
    Math.random = () => {
      seed |= 0;
      seed = (seed + 0x6d2b79f5) | 0;
      let mixed = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      mixed = (mixed + Math.imul(mixed ^ (mixed >>> 7), 61 | mixed)) ^ mixed;
      return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296;
    };

    // The Example feed and the IST second hand both use a 1s interval.
    // Swallow that delay so a longer settle cannot walk prices or the clock.
    const originalSetInterval = window.setInterval.bind(window);
    window.setInterval = ((handler: TimerHandler, timeout?: number, ...args: unknown[]) => {
      if (timeout === 1000) {
        return originalSetInterval(() => undefined, 60_000);
      }
      return originalSetInterval(handler, timeout, ...args);
    }) as typeof window.setInterval;

    const css = [
      "*,*::before,*::after{",
      "animation:none !important;",
      "transition:none !important;",
      "caret-color:transparent !important;",
      "scroll-behavior:auto !important;",
      "}",
      "html,body{",
      "overflow:hidden !important;",
      "padding-right:0 !important;",
      "}",
    ].join("");
    const apply = (): void => {
      if (document.getElementById("visual-a11y-motion")) return;
      const style = document.createElement("style");
      style.id = "visual-a11y-motion";
      style.textContent = css;
      (document.head ?? document.documentElement).appendChild(style);
    };
    if (document.head) apply();
    else document.addEventListener("DOMContentLoaded", apply);
  });
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await page.clock.pauseAt(FIXED_CLOCK);
}

export async function settle(page: Page, ready: () => Promise<boolean>): Promise<void> {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline && !(await ready())) {
    await page.clock.runFor(100);
  }
  if (!(await ready())) {
    throw new Error("screen did not become ready before the fixed clock budget");
  }
  await page.evaluate(() => document.fonts.ready);
}

export function dynamicMasks(page: Page): Locator[] {
  return [
    page.getByRole("region", { name: "Market indices" }),
    page.getByRole("region", { name: "Ticker prices" }),
    page.getByLabel("Current time in IST"),
    page.locator("canvas"),
  ];
}

async function focusOrder(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const selector = "a[href], button, input, select, textarea, [tabindex]";
    const nodes = Array.from(document.querySelectorAll<HTMLElement>(selector));
    const visible = nodes.filter((el) => {
      if (el.tabIndex < 0) return false;
      if ("disabled" in el && Boolean((el as HTMLButtonElement).disabled)) return false;
      const style = getComputedStyle(el);
      if (style.visibility === "hidden" || style.display === "none") return false;
      if (el.getAttribute("aria-hidden") === "true") return false;
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    });
    const positive = visible
      .filter((el) => el.tabIndex > 0)
      .sort((left, right) => left.tabIndex - right.tabIndex || 0);
    const normal = visible.filter((el) => el.tabIndex === 0);
    return [...positive, ...normal].map((el) => {
      const role = el.getAttribute("role") || el.tagName.toLowerCase();
      const name = (el.getAttribute("aria-label") || el.innerText || "")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 80);
      return `${role}:${name}`;
    });
  });
}

function normaliseViolations(violations: Awaited<ReturnType<AxeBuilder["analyze"]>>["violations"]): AxeViolationSnap[] {
  return violations
    .map((violation) => ({
      id: violation.id,
      impact: violation.impact ?? null,
      targets: violation.nodes.map((node) => node.target.join(" ")).sort(),
    }))
    .sort((left, right) => {
      const byId = left.id.localeCompare(right.id);
      if (byId !== 0) return byId;
      return left.targets.join("\n").localeCompare(right.targets.join("\n"));
    });
}

function readKnown(): KnownFile {
  const raw = fs.readFileSync(KNOWN_PATH, "utf8");
  const parsed: unknown = JSON.parse(raw);
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("known-axe-violations.json must be an object");
  }
  return parsed as KnownFile;
}

function writeKnown(known: KnownFile): void {
  const ordered = Object.fromEntries(
    Object.entries(known).sort(([left], [right]) => left.localeCompare(right)),
  );
  fs.writeFileSync(KNOWN_PATH, `${JSON.stringify(ordered, null, 2)}\n`);
}

function writeObservation(screenKey: string, snap: ScreenSnap): void {
  const dir = path.resolve("test-results", "axe");
  fs.mkdirSync(dir, { recursive: true });
  const safe = screenKey.replace(/[^a-z0-9@_-]+/gi, "-");
  fs.writeFileSync(path.join(dir, `${safe}.json`), `${JSON.stringify(snap, null, 2)}\n`);
}

export async function reviewScreen(
  page: Page,
  screenKey: string,
  screenshotName: string,
  target: Page | Locator = page,
): Promise<void> {
  // Axe needs live timers. The clock stays paused for the screenshot so a
  // widescreen frame can settle.
  await page.clock.resume();
  const analysis = await new AxeBuilder({ page }).withTags([...AXE_TAGS]).analyze();
  const now = await page.evaluate(() => Date.now());
  await page.clock.pauseAt(now + 50);
  const snap: ScreenSnap = {
    violations: normaliseViolations(analysis.violations),
    focus: await focusOrder(page),
  };
  writeObservation(screenKey, snap);

  const update = process.env["UPDATE_AXE_SNAPSHOT"] === "1";
  const known = readKnown();
  if (update) {
    known[screenKey] = snap;
    writeKnown(known);
  } else {
    expect(known[screenKey], `missing axe snapshot for ${screenKey}. Set UPDATE_AXE_SNAPSHOT=1 on a review run.`).toEqual(snap);
  }

  await expect(target).toHaveScreenshot(screenshotName, {
    animations: "disabled",
    caret: "hide",
    mask: dynamicMasks(page),
  });
}
