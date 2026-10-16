import type { Page, TestInfo } from "@playwright/test";
import { expect } from "../fixture-registry";

/** The same native Help action must not cover any painted content or footer field. */
export async function verifyHelpPlacement(page: Page, screenKey: string, info: TestInfo): Promise<void> {
  const help = page.getByRole("button", { name: "Open local help", exact: true });
  const signedOut = /^(sign-in|setup|two-operator)@/.test(screenKey);
  await expect(help).toHaveCount(signedOut ? 0 : 1);
  if (signedOut) return;
  await expect(help).toBeVisible();
  const observation = await help.evaluate(button => {
    const box = (r: DOMRect) => ({ left: r.left, top: r.top, right: r.right, bottom: r.bottom });
    const rect = box(button.getBoundingClientRect());
    const footer = document.querySelector('[data-testid="system-status-bar"]');
    const footerRect = footer ? box(footer.getBoundingClientRect()) : null;
    const intersect = (a: typeof rect, b: typeof rect) => ({ left: Math.max(a.left, b.left), top: Math.max(a.top, b.top), right: Math.min(a.right, b.right), bottom: Math.min(a.bottom, b.bottom) });
    const positive = (r: typeof rect) => r.right > r.left && r.bottom > r.top;
    // Edge midpoints stay on the painted button; rounded-corner cut-outs do not.
    const centerX = (rect.left + rect.right) / 2;
    const centerY = (rect.top + rect.bottom) / 2;
    const points = [[rect.left + 1, centerY], [rect.right - 1, centerY], [centerX, rect.top + 1], [centerX, rect.bottom - 1], [centerX, centerY]];
    const hits = points.map(([x, y]) => { const hit = document.elementFromPoint(x!, y!); return { x, y, owns: hit === button || (hit !== null && button.contains(hit)), tag: hit?.tagName, text: hit?.textContent }; });
    const overlaps: { text: string; rect: typeof rect; intersection: typeof rect; hit: string | null; helpOwnsHit: boolean }[] = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (!node.textContent?.trim() || button.contains(node)) continue;
      const parent = node.parentElement;
      if (!parent || parent.closest("script, style, [aria-hidden=true]")) continue;
      let clip = { left: 0, top: 0, right: innerWidth, bottom: innerHeight };
      let hidden = false;
      for (let el: HTMLElement | null = parent; el; el = el.parentElement) {
        const style = getComputedStyle(el);
        if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) { hidden = true; break; }
        const r = el.getBoundingClientRect();
        if (style.overflowX !== "visible") { clip.left = Math.max(clip.left, r.left + el.clientLeft); clip.right = Math.min(clip.right, r.left + el.clientLeft + el.clientWidth); }
        if (style.overflowY !== "visible") { clip.top = Math.max(clip.top, r.top + el.clientTop); clip.bottom = Math.min(clip.bottom, r.top + el.clientTop + el.clientHeight); }
      }
      if (hidden) continue;
      const range = document.createRange(); range.selectNodeContents(node);
      for (const native of range.getClientRects()) {
        const visible = intersect(box(native), clip);
        const overlap = intersect(visible, rect);
        if (!positive(visible) || !positive(overlap)) continue;
        const hit = document.elementFromPoint((overlap.left + overlap.right) / 2, (overlap.top + overlap.bottom) / 2);
        overlaps.push({ text: node.textContent.trim(), rect: visible, intersection: overlap, hit: hit?.textContent ?? null, helpOwnsHit: hit === button || (hit !== null && button.contains(hit)) });
      }
    }
    return { rect, footerRect, hits, overlaps, inFooter: footer?.contains(button) ?? false };
  });
  await info.attach(`help-geometry-${screenKey}`, { body: JSON.stringify(observation, null, 2), contentType: "application/json" });
  await info.attach(`help-native-${screenKey}`, { body: await page.screenshot(), contentType: "image/png" });
  expect(observation.overlaps, "Help obscures painted text").toEqual([]);
  expect(observation.hits.every(hit => hit.owns), "Help must own every sampled hit point").toBe(true);
  expect(observation.inFooter, "Help belongs in reserved footer flow, not over trading content").toBe(true);
  expect(observation.footerRect).not.toBeNull();
  expect(observation.rect.top).toBeGreaterThanOrEqual(observation.footerRect!.top);
  expect(observation.rect.bottom).toBeLessThanOrEqual(observation.footerRect!.bottom);
}

export async function verifyHelpKeyboard(page: Page, screenKey: string): Promise<void> {
  if (/^(sign-in|setup|two-operator)@/.test(screenKey)) return;
  const help = page.getByRole("button", { name: "Open local help", exact: true });
  await help.focus();
  await help.press("Enter");
  await expect(page.getByRole("dialog", { name: "Local help · not an AI response" })).toBeVisible();
  await page.keyboard.press("Escape");
  // Radix restores focus on the queued close task; the visual clock is paused.
  await page.clock.runFor(100);
  await expect(page.getByRole("dialog", { name: "Local help · not an AI response" })).toBeHidden();
  await expect(help).toBeFocused();
}
