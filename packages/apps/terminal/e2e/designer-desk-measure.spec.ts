import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "./fixture-registry";
import { seedExploreDemoSession } from "./helpers";
import { registerExampleDeskReads, registerPracticeOrderPadReads } from "./visual/desk-mocks";

const WORKSPACE_GLOBAL = {
  tabEnableRename: false,
  tabSetEnableSingleTabStretch: true,
  tabSetMinWidth: 100,
  tabSetMinHeight: 80,
};

function persistLayout(): string {
  const layout = {
    global: WORKSPACE_GLOBAL,
    borders: [],
    layout: {
      type: "row",
      weight: 100,
      children: [
        { type: "tabset", weight: 50, children: [{ type: "tab", id: "d-chart", component: "chart", name: "Chart" }] },
        { type: "tabset", weight: 25, children: [{ type: "tab", id: "d-pad", component: "orderpad", name: "Order Pad" }] },
        { type: "tabset", weight: 25, children: [{ type: "tab", id: "d-pos", component: "positions", name: "Positions" }] },
      ],
    },
  };
  return JSON.stringify({ Current: layout });
}

async function seed(page: Page, theme: "dark" | "light"): Promise<void> {
  await seedExploreDemoSession(page);
  await page.addInitScript((payload) => {
    localStorage.setItem("flinttrade:app-layouts:v1:terminal", payload.layout);
    localStorage.setItem("flinttrade-theme", JSON.stringify({
      state: {
        activeThemeId: "graphite",
        mode: payload.theme,
        customThemes: [],
        glass: true,
        reduceMotion: true,
      },
      version: 4,
    }));
    localStorage.removeItem("flinttrade:practice-later");
  }, { layout: persistLayout(), theme });
  await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
}

async function measure(page: Page) {
  return page.evaluate(() => {
    const banned = /\b(Paper|Sandbox|Explore|Explorer)\b/;
    const bodyText = document.body.innerText;
    const bannedHits = bodyText.split("\n").map(line => line.trim()).filter(line => banned.test(line)).slice(0, 40);

    const swatch = document.createElement("canvas");
    swatch.width = swatch.height = 1;
    const paint = swatch.getContext("2d", { willReadFrequently: true });
    function channels(color: string): [number, number, number] {
      if (!paint) return [0, 0, 0];
      paint.clearRect(0, 0, 1, 1);
      paint.fillStyle = color;
      paint.fillRect(0, 0, 1, 1);
      const [r, g, b] = paint.getImageData(0, 0, 1, 1).data;
      return [r, g, b];
    }
    function opaqueBg(el: Element | null): string {
      let node: Element | null = el;
      while (node) {
        const bg = getComputedStyle(node).backgroundColor;
        const match = bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/);
        if (match && (match[4] === undefined || Number(match[4]) >= 0.95)) return bg;
        node = node.parentElement;
      }
      return "rgb(10, 10, 15)";
    }
    function lin(c: number): number {
      const s = c / 255;
      return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    }
    function ratio(fg: string, bg: string): number {
      const [fr, fgG, fb] = channels(fg);
      const [br, bgG, bb] = channels(bg);
      const L1 = 0.2126 * lin(fr) + 0.7152 * lin(fgG) + 0.0722 * lin(fb);
      const L2 = 0.2126 * lin(br) + 0.7152 * lin(bgG) + 0.0722 * lin(bb);
      const lighter = Math.max(L1, L2);
      const darker = Math.min(L1, L2);
      return Math.round(((lighter + 0.05) / (darker + 0.05)) * 100) / 100;
    }

    const ticker = document.querySelector("[data-testid='ticker-strip']");
    const tickerText: { text: string; fontSize: number; ratio: number; color: string; bg: string }[] = [];
    if (ticker) {
      const seen = new Set<Element>();
      for (const el of ticker.querySelectorAll("*")) {
        if (seen.has(el)) continue;
        const direct = [...el.childNodes].some(node => node.nodeType === Node.TEXT_NODE && (node.textContent ?? "").trim());
        if (!direct) continue;
        seen.add(el);
        const cs = getComputedStyle(el);
        if (cs.display === "none" || cs.visibility === "hidden" || el.closest(".sr-only")) continue;
        const bg = opaqueBg(el);
        tickerText.push({
          text: (el.textContent ?? "").trim().slice(0, 40),
          fontSize: Number.parseFloat(cs.fontSize),
          ratio: ratio(cs.color, bg),
          color: cs.color,
          bg,
        });
      }
    }

    function panel(name: string) {
      const tab = [...document.querySelectorAll("[role='tab']")].find(el => (el.textContent ?? "").includes(name));
      const panelEl = [...document.querySelectorAll("[role='tabpanel']")].find(el => (el.getAttribute("aria-label") ?? el.textContent ?? "").includes(name) || (tab && tab.getAttribute("aria-controls") === el.id));
      const target = panelEl ?? tab?.closest(".flexlayout__tabset") ?? null;
      if (!target) return { name, present: false };
      const box = target.getBoundingClientRect();
      const points = [
        [box.x + box.width / 2, box.y + box.height / 2],
        [box.x + 12, box.y + 28],
        [box.x + box.width - 12, box.y + box.height - 12],
      ];
      const hits = points.map(([x, y]) => {
        const top = document.elementFromPoint(x, y);
        const covered = Boolean(top && !target.contains(top));
        return {
          x: Math.round(x),
          y: Math.round(y),
          covered,
          top: covered ? `${top?.tagName}.${(top?.className ?? "").toString().slice(0, 80)} ${(top?.textContent ?? "").trim().slice(0, 40)}` : "",
        };
      });
      return {
        name,
        present: true,
        w: Math.round(box.width),
        h: Math.round(box.height),
        covered: hits.some(hit => hit.covered),
        hits,
      };
    }

    const doc = document.documentElement;
    const clipped = [...document.querySelectorAll("button, a, input, select, summary")].filter(el => {
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden") return false;
      const box = el.getBoundingClientRect();
      if (box.width < 2 || box.height < 2) return false;
      if (box.right > window.innerWidth + 1 || box.left < -1) return true;
      let parent = el.parentElement;
      while (parent) {
        const pcs = getComputedStyle(parent);
        if (/(auto|hidden|scroll|clip)/.test(pcs.overflowX + pcs.overflow)) {
          const pb = parent.getBoundingClientRect();
          if (box.right > pb.right + 1 || box.left < pb.left - 1) return true;
        }
        parent = parent.parentElement;
      }
      return false;
    }).slice(0, 20).map(el => ({
      text: (el.textContent ?? el.getAttribute("aria-label") ?? "").trim().slice(0, 40),
      box: (() => { const b = el.getBoundingClientRect(); return { l: Math.round(b.left), r: Math.round(b.right), w: Math.round(b.width) }; })(),
    }));

    return {
      viewport: { w: window.innerWidth, h: window.innerHeight },
      scrollWidth: doc.scrollWidth,
      clientWidth: doc.clientWidth,
      overflow: doc.scrollWidth > doc.clientWidth + 1,
      bannedHits,
      tickerText,
      clipped,
      panels: ["Chart", "Order Pad", "Positions"].map(panel),
      compact: Boolean(document.querySelector("[aria-label='Compact panel']")),
      help: (() => {
        const button = document.querySelector("[aria-label='Open local help']");
        const footer = document.querySelector("[data-testid='system-status-bar']");
        if (!button) return { present: false, inFooter: true, fixed: false };
        return {
          present: true,
          inFooter: Boolean(footer?.contains(button)),
          fixed: getComputedStyle(button).position === "fixed",
        };
      })(),
      niftyLabels: [...document.querySelectorAll("[aria-label^='NIFTY 50:']")].map(el => el.getAttribute("aria-label") ?? ""),
      exampleChip: document.querySelector("[data-testid='feed-freshness-chip']")?.textContent?.trim() ?? "",
      host: (() => {
        const host = document.querySelector("[data-testid='app-layout']");
        const box = host?.getBoundingClientRect();
        return box ? { w: Math.round(box.width), h: Math.round(box.height) } : null;
      })(),
    };
  });
}

for (const width of [1440, 2560] as const) {
  for (const theme of ["dark", "light"] as const) {
    test(`desk ${width} ${theme}`, async ({ page, syntheticApi }, testInfo) => {
      const height = width === 1440 ? 900 : 1440;
      await page.setViewportSize({ width, height });
      await seed(page, theme);
      registerExampleDeskReads(syntheticApi);
      registerPracticeOrderPadReads(syntheticApi);
      await page.goto("/terminal");
      await expect(page.getByRole("tab", { name: "Chart" })).toBeVisible({ timeout: 20_000 });
      await page.waitForTimeout(500);
      const report = await measure(page);
      await testInfo.attach("measure", { body: JSON.stringify(report, null, 2), contentType: "application/json" });
      await page.screenshot({ path: testInfo.outputPath(`desk-${width}-${theme}.png`), fullPage: false });
      expect(report.overflow, "page overflows horizontally").toBe(false);
      expect(report.bannedHits, "banned operator words").toEqual([]);
      expect(report.compact, "a compact overlay replaced the desk").toBe(false);
      expect(report.clipped, "controls clipped at the viewport or an overflow parent").toEqual([]);
      for (const name of ["Chart", "Order Pad", "Positions"]) {
        const panel = report.panels.find(item => item.name === name);
        expect(panel?.present, name).toBe(true);
        expect(panel && "covered" in panel ? panel.covered : true, `${name} is covered`).toBe(false);
        expect(panel && "w" in panel ? panel.w : 0, name).toBeGreaterThan(200);
      }
      const small = report.tickerText.filter(item => item.fontSize < 12);
      const faint = report.tickerText.filter(item => item.ratio < 4.5);
      expect(small, "ticker text below 12px").toEqual([]);
      expect(faint, "ticker text below 4.5:1").toEqual([]);
      expect(report.help.inFooter, "Help covers the desk instead of sitting in the footer").toBe(true);
      expect(report.help.fixed, "Help is still position fixed").toBe(false);
      expect(report.exampleChip, "Example chip").toBe("Example");
      expect(report.niftyLabels.length, "NIFTY is on the tape").toBeGreaterThan(0);
      expect(report.niftyLabels.every(label => /^NIFTY 50: \d/.test(label)), `ticker price missing: ${report.niftyLabels.join(" | ")}`).toBe(true);
      const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      const axeReport = {
        theme,
        width,
        violations: axe.violations.map(violation => ({
          id: violation.id,
          impact: violation.impact,
          help: violation.help,
          nodes: violation.nodes.slice(0, 8).map(node => node.target.join(" ")),
        })),
      };
      await testInfo.attach(`axe-${width}-${theme}`, { body: JSON.stringify(axeReport, null, 2), contentType: "application/json" });
    });
  }
}
