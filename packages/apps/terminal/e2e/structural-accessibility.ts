import fs from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { test as nativeTest, expect } from "./observed-registry";
import type { Page, TestInfo } from "@playwright/test";
import { seedExploreDemoSession } from "./helpers";
import { registerExampleDeskReads } from "./visual/desk-mocks";
import { installDeterminism, settle, VIEWPORTS } from "./visual/support";
import { interactions } from "./workspace-interactions";

export interface StructuralHooks {
  ready?: (page: Page, info: TestInfo) => Promise<void>;
  complete?: (page: Page, info: TestInfo, checkpoint: "interaction" | "structure") => Promise<void>;
}

export function registerStructuralAccessibility(test: typeof nativeTest, hooks: StructuralHooks = {}) {
for (const viewport of VIEWPORTS) {
  test.describe(`structural ${viewport.width}`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });
    test("keyboard drag selection and channel propagation", async ({ page, syntheticApi }, info) => {
      await installDeterminism(page);
      await seedExploreDemoSession(page);
      registerExampleDeskReads(syntheticApi);
      await page.goto("/home");
      await settle(page, async () => (await Promise.all([
        page.getByRole("tabpanel", { name:"Watchlist", exact:true }).getByRole("button", {name:"Add symbol",exact:true}).isVisible(),
        page.getByRole("tabpanel", {name:"Chart",exact:true}).getByRole("button",{name:"Open chart display settings",exact:true}).isVisible(),
        page.getByRole("region",{name:"Positions book",exact:true}).isVisible(),
      ])).every(Boolean));
      await hooks.ready?.(page, info);
      await interactions(page,info);
      await hooks.complete?.(page, info, "interaction");
    });
    for (const rule of ["nested-interactive", "aria-required-children", "aria-required-parent"]) {
      test(rule, async ({ page, syntheticApi }, info) => {
        await installDeterminism(page);
        await seedExploreDemoSession(page);
        registerExampleDeskReads(syntheticApi);
        await page.goto("/home");
        const watchlist = page.getByRole("tabpanel", { name: "Watchlist", exact: true });
        await settle(page, async () => (await Promise.all([
          watchlist.getByRole("button", { name: "Add symbol", exact: true }).isVisible(),
          page.getByRole("tabpanel", { name: "Chart", exact: true }).getByRole("button", { name: "Open chart display settings", exact: true }).isVisible(),
          page.getByRole("region", { name: "Positions book", exact: true }).isVisible(),
        ])).every(Boolean));
        await hooks.ready?.(page, info);
        await page.clock.resume();
        const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
        await page.clock.pauseAt((await page.evaluate(() => Date.now())) + 50);
        fs.writeFileSync(info.outputPath("axe-raw.json"), JSON.stringify(axe, null, 2));
        fs.writeFileSync(info.outputPath("native.ax.txt"), await page.locator("body").ariaSnapshot());
        const geometry = await page.locator('.flexlayout__tab_button, button[aria-label^="Link channel"], [data-tour-target="watchlist"] *').evaluateAll(elements => elements.map(el => {
          const r = el.getBoundingClientRect();
          const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
          return { tag: el.tagName, id: el.id, role: el.getAttribute("role"), label: el.getAttribute("aria-label"), text: el.textContent, html: el.outerHTML, box: { x: r.x, y: r.y, width: r.width, height: r.height }, hit: !!hit && (hit === el || el.contains(hit)) };
        }));
        fs.writeFileSync(info.outputPath("geometry.json"), JSON.stringify(geometry, null, 2));
        await page.screenshot({ path: info.outputPath("native.png") });
        expect(axe.violations.filter(v => v.id === rule), `Actual native ${rule}, not a recorded baseline`).toEqual([]);
        await hooks.complete?.(page, info, "structure");
      });
    }
  });
}

}
