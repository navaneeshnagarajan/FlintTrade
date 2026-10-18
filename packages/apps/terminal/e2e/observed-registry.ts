/** Native evidence layered on the fail-closed fixture; no verifier runtime. */
import fs from "node:fs";
import { test as base, expect } from "./fixture-registry";
import type { Request } from "@playwright/test";
export { expect };

export const test = base.extend<{ visualEvidence: void }>({
  visualEvidence: [async ({ page, syntheticApi }, use, info) => {
    void syntheticApi; // Teardown observes the live page before its existing owner disposes it.
    const ledger: Record<string, unknown>[] = [];
    const requests = new Map<Request, Record<string, unknown>>();
    const bodyReads: Promise<void>[] = [];
    const consoleRows: unknown[] = [];
    const initiators: unknown[] = [];
    const errors: string[] = [];
    const scripts = new Set<string>();
    let firstPingObserved = false;
    const out = (name: string, data: unknown) => fs.writeFileSync(info.outputPath(name), JSON.stringify(data, null, 2) + "\n");
    const interesting = (url: string) => /\/(?:ft-api|api|v1|health)(?:\/|$)/.test(new URL(url).pathname);
    page.on("request", request => {
      if (!interesting(request.url())) return;
      const row = { url: request.url(), method: request.method(), body: request.postData(), headers: request.headers(), hostTime: Date.now(), outcome: "pending" };
      ledger.push(row); requests.set(request, row);
    });
    page.on("requestfailed", request => {
      const row = requests.get(request);
      if (row) Object.assign(row, { outcome: "failed", failure: request.failure(), finishedHost: Date.now() });
    });
    page.on("response", response => {
      const row = requests.get(response.request());
      if (!row) return;
      Object.assign(row, { status: response.status(), responseHeaders: response.headers() });
      bodyReads.push((async () => {
        try {
          const error = await response.finished();
          if (error) throw error;
          const bytes = await response.body();
          Object.assign(row, { outcome: "completed", responseBodyBase64: bytes.toString("base64"), finishedHost: Date.now() });
          if (new URL(response.url()).pathname === "/ft-api/api/v1/ping" && !firstPingObserved) {
            firstPingObserved = true;
            const loaded = [...scripts];
            const modules = ["/src/providers/QueryProvider.tsx", "/src/stores/operatorSignalStore.ts", "/src/stores/authStore.ts", "/src/stores/modeStore.ts"].map(suffix => loaded.find(url => url.split("?")[0].endsWith(suffix)));
            try {
              out("observation-first-ping-phase.json", await page.evaluate(async urls => {
                const [query, signals, auth, mode] = await Promise.all(urls.map(url => url ? import(/* @vite-ignore */ url) : null));
                return {
                  url: location.href, browserTime: Date.now(), performanceTime: performance.now(), text: document.body.innerText,
                  queries: query?.queryClient.getQueryCache().getAll().map((q: { queryKey: unknown; state: unknown; getObserversCount: () => number }) => ({ key: q.queryKey, state: q.state, observers: q.getObserversCount() })),
                  signals: signals?.useOperatorSignalStore.getState(), authStatus: auth?.useAuthStore.getState().status, mode: mode?.useModeStore.getState().mode,
                  modules: urls,
                };
              }, modules));
            } catch (error) { out("observation-first-ping-phase-error.json", String(error)); }
          }
        } catch (error) { Object.assign(row, { outcome: "body-failed", error: String(error) }); }
      })());
    });
    page.on("console", m => consoleRows.push({ type: m.type(), text: m.text(), location: m.location(), hostTime: Date.now() }));
    page.on("pageerror", e => consoleRows.push({ type: "pageerror", message: String(e), hostTime: Date.now() }));
    const cdp = await page.context().newCDPSession(page);
    cdp.on("Debugger.scriptParsed", e => scripts.add(e.url));
    await cdp.send("Debugger.enable");
    await cdp.send("Debugger.setAsyncCallStackDepth", { maxDepth: 32 });
    await cdp.send("Network.enable");
    cdp.on("Network.requestWillBeSent", e => { if (interesting(e.request.url)) initiators.push(e); });
    cdp.on("Network.loadingFailed", e => initiators.push(e));
    try { await use(); }
    finally {
      try {
        if (page.isClosed()) throw new Error("Page closed before visual evidence");
        fs.writeFileSync(info.outputPath("observation-dom.html"), await page.content());
        fs.writeFileSync(info.outputPath("observation-aria.yml"), await page.locator("body").ariaSnapshot());
        await page.screenshot({ path: info.outputPath("observation-screen.png"), animations: "allow" });
        out("observation-ranges.json", await page.evaluate(() => {
          const box = (r: DOMRect) => ({ x: r.x, y: r.y, width: r.width, height: r.height, top: r.top, left: r.left, right: r.right, bottom: r.bottom });
          const texts: unknown[] = [];
          const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          while (walk.nextNode()) {
            const node = walk.currentNode;
            if (!node.textContent?.trim()) continue;
            const el = node.parentElement;
            if (!el || ["SCRIPT", "STYLE"].includes(el.tagName)) continue;
            const range = document.createRange(); range.selectNodeContents(node);
            const rects = Array.from(range.getClientRects(), box);
            if (!rects.length) continue;
            const rect = el.getBoundingClientRect();
            const centre = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
            const ancestors = [];
            for (let p: Element | null = el; p; p = p.parentElement) {
              const style = getComputedStyle(p);
              if (/(hidden|clip|auto|scroll)/.test(style.overflowX + style.overflowY)) ancestors.push({ tag: p.tagName, id: p.id, box: box(p.getBoundingClientRect()), overflowX: style.overflowX, overflowY: style.overflowY, scrollTop: p.scrollTop, scrollLeft: p.scrollLeft, clientHeight: p.clientHeight, scrollHeight: p.scrollHeight });
            }
            texts.push({ text: node.textContent, tag: el.tagName, id: el.id, testId: el.getAttribute("data-testid"), box: box(rect), ranges: rects, centreHit: Boolean(centre && (centre === el || el.contains(centre))), ancestors });
          }
          return { url: location.href, browserTime: Date.now(), performanceTime: performance.now(), width: innerWidth, height: innerHeight, online: navigator.onLine, texts };
        }));
        const provider = [...scripts].find(url => /\/src\/providers\/QueryProvider\.tsx(?:\?|$)/.test(url));
        out("observation-queries.json", provider ? await page.evaluate(async url => {
          const mod = await import(/* @vite-ignore */ url);
          return mod.queryClient.getQueryCache().getAll().map((q: { queryKey: unknown; state: unknown; getObserversCount: () => number }) => ({ key: q.queryKey, state: q.state, observers: q.getObserversCount() }));
        }, provider) : { error: "No mounted QueryProvider script", scripts: [...scripts] });
      } catch (error) { errors.push(String(error)); }
      out("observation-bodies-live.json", ledger); out("observation-console.json", consoleRows); out("observation-initiators.json", initiators); out("observation-observer-errors.json", errors);
      // Dispose through the existing owner, then finish every body ledger.
      // The base fixture repeats this idempotent disposal and retains its failures.
      try { await syntheticApi.dispose(); }
      finally {
        await Promise.all(bodyReads);
        out("observation-bodies-closed.json", ledger);
        out("observation-close.json", { pageClosed: page.isClosed(), hostTime: Date.now() });
      }
      if (errors.length) throw new Error(errors.join("\n"));
    }
  }, { auto: true }],
});
