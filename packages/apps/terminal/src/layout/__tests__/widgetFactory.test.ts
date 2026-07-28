import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { ICON_MAP } from "@/chrome/WidgetPicker";
import { widgetCatalog, widgetComponents, RETIRED_WIDGET_IDS, isMovedWidget } from "../widgetFactory";

// ---------------------------------------------------------------------------
// Catalogue-truth guard — helpers
// ---------------------------------------------------------------------------

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const FACTORY_FILE = join(SRC_ROOT, "layout", "widgetFactory.tsx");

/**
 * `widget id → "widgets/<group>/<Name>/<Name>Widget"`, parsed out of the
 * `lazyWidgets` import map in widgetFactory.tsx. Parsing the source (rather
 * than exporting the map) keeps the runtime surface unchanged — the lazy
 * imports must stay statically analysable for Vite's code splitting anyway.
 */
const WIDGET_MODULES: ReadonlyMap<string, string> = new Map(
  [
    ...readFileSync(FACTORY_FILE, "utf8").matchAll(
      /(\w+):\s*lazy\(\(\)\s*=>\s*import\("@\/(widgets\/[^"]+)"\)\)/g,
    ),
  ].map((match) => [match[1], match[2]] as const),
);

/** Every non-test `.ts`/`.tsx` file under a directory, recursively. */
function sourceFilesUnder(dir: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(dir)) {
    if (entry === "__tests__") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      files.push(...sourceFilesUnder(full));
      continue;
    }
    if (!/\.tsx?$/.test(entry) || /\.test\.tsx?$/.test(entry)) continue;
    files.push(full);
  }
  return files;
}

/**
 * The widget's own source text. Widgets that share a directory with siblings
 * (`widgets/orders/`, `widgets/account/`) are read file-by-file, so one
 * widget's code can never vouch for a neighbour's description.
 */
function widgetSource(id: string): string {
  const modulePath = WIDGET_MODULES.get(id);
  if (!modulePath) return "";
  const moduleFile = join(SRC_ROOT, `${modulePath}.tsx`);
  if (!existsSync(moduleFile)) return "";
  const dir = dirname(moduleFile);
  const widgetsInDir = readdirSync(dir).filter((entry) => /Widget\.tsx$/.test(entry));
  const files = widgetsInDir.length > 1 ? [moduleFile] : sourceFilesUnder(dir);
  return files.map((file) => readFileSync(file, "utf8")).join("\n");
}

interface CapabilityClaim {
  /** Matched against a catalogue description. */
  readonly claim: RegExp;
  /** Must match the widget's own source when the claim fires. */
  readonly evidence: RegExp;
  /** Why this phrase is pinned — read by whoever trips it. */
  readonly why: string;
}

/**
 * Phrases that name a concrete capability, each paired with the token its
 * implementation would have to contain.
 *
 * Most entries are here because the catalogue once made exactly this claim
 * with nothing behind it: Price Alerts advertised "Telegram and in-app
 * notifications" (no Telegram call, no Notification API), Trade Ideas
 * advertised "AI-generated" ideas (zero network calls), Trade Performance
 * advertised a Sharpe ratio it never computed, Session Stats advertised
 * turnover it never summed, and Trade Log advertised screenshots it cannot
 * store. The rest are tripwires for the same failure mode in phrases we do
 * currently claim truthfully.
 */
const CAPABILITY_CLAIMS: readonly CapabilityClaim[] = [
  { claim: /telegram/i, evidence: /telegram/i, why: "a Telegram claim needs a Telegram call" },
  {
    claim: /\bnotification/i,
    evidence: /Notification|notify|toast|useNotification/i,
    why: "a notification claim needs a notification path",
  },
  { claim: /\bsharpe\b/i, evidence: /sharpe/i, why: "Sharpe must actually be computed" },
  { claim: /\bvpin\b/i, evidence: /vpin/i, why: "VPIN must actually be computed" },
  { claim: /\bkelly\b/i, evidence: /kelly/i, why: "Kelly sizing must actually be implemented" },
  { claim: /monte[\s-]?carlo/i, evidence: /monte[\s_-]?carlo/i, why: "Monte Carlo must be simulated" },
  { claim: /\bturnover\b/i, evidence: /turnover/i, why: "turnover must actually be summed" },
  { claim: /\bexpectancy\b/i, evidence: /expectancy/i, why: "expectancy must actually be computed" },
  { claim: /profit factor/i, evidence: /profit[^A-Za-z0-9]?factor/i, why: "profit factor must be computed" },
  { claim: /\bcamarilla\b/i, evidence: /camarilla/i, why: "a named pivot method must exist" },
  { claim: /\bwoodie/i, evidence: /woodie/i, why: "a named pivot method must exist" },
  { claim: /\bfibonacci\b/i, evidence: /fibonacci|\bfib\b/i, why: "a named pivot method must exist" },
  { claim: /\bdemark\b/i, evidence: /demark/i, why: "a named pivot method must exist" },
  { claim: /screenshot/i, evidence: /screenshot/i, why: "screenshots need a screenshot path" },
  { claim: /full-text search/i, evidence: /search/i, why: "search claims need a search call" },
  { claim: /\bcsv\b/i, evidence: /csv/i, why: "a CSV export claim needs an export path" },
  { claim: /\btwap\b/i, evidence: /twap/i, why: "a TWAP slicing claim needs TWAP code" },
  { claim: /\bgtt\b/i, evidence: /gtt/i, why: "a GTT claim needs the GTT surface" },
  { claim: /kill switch/i, evidence: /kill/i, why: "a kill-switch claim needs the kill switch" },
  {
    claim: /\bAI-(generated|powered|driven)\b/i,
    evidence: /advisor|agent|llm|prompt|anthropic|openai|cerebras|chat/i,
    why: "an AI claim needs a model/agent call — a localStorage notebook is not AI",
  },
  { claim: /\brsi\b/i, evidence: /rsi/i, why: "a named indicator must appear in the widget" },
  { claim: /\bmacd\b/i, evidence: /macd/i, why: "a named indicator must appear in the widget" },
  { claim: /\bema\b/i, evidence: /ema/i, why: "a named indicator must appear in the widget" },
];

// ---------------------------------------------------------------------------
// Live-data claim guard — helpers
// ---------------------------------------------------------------------------

/**
 * Words that promise a moving data source rather than a fixed table. Written
 * so that spacing and hyphenation cannot defeat them ("real time", "real-time",
 * "realtime" all match) and so that they only fire on whole words — "delivery"
 * must not read as "live".
 */
const LIVE_DATA_CLAIM =
  /\b(?:live|real[\s-]*time|realtime|intraday|streaming|tick[\s-]*by[\s-]*tick|updated\s+tick)\b/i;

/**
 * A token that only appears in a widget that actually reaches for data: a
 * service module, a TanStack Query/mutation hook, a raw fetch, a WebSocket
 * atom, or one of the shared broker-read hooks. Deliberately broad — the point
 * is to separate "this widget talks to something" from "this widget renders a
 * hardcoded array", not to audit how well it does it.
 *
 * One known blind spot: `widgetSource` reads a single file for widgets that
 * share a directory (`widgets/orders/`, `widgets/account/`), so a sibling that
 * keeps its data calls in a shared module reads as fetching nothing. None of
 * those descriptions claim live data today; if one starts to, exempt it here
 * with that as the reason rather than widening the evidence regex.
 */
const LIVE_DATA_EVIDENCE =
  /@\/services\/(?:api|ftApi|websocket)|\buseQuery\b|\buseMutation\b|\bfetch\(|\buseAtomValue\b|\buseLtp\b|\buseQuote\b|\buseDepth\b|\buseOptionChain\b|\buseMarketData\b|\buseOrderFlow\b|\buse(?:Positions|Funds|Holdings|Orders|Tradebook)\b/;

/**
 * Widgets allowed to use a live-data word with no data call behind it, each
 * with the reason. An entry is only ever legitimate when the word appears
 * inside the widget's own *disclosure* of not being live — never in a promise.
 *
 * Keep this list short. Rewording the description is almost always the right
 * fix; the catalogue entry is the only promise most operators ever read.
 */
const LIVE_CLAIM_EXEMPTIONS: Readonly<Record<string, string>> = {
  instrumentcompare:
    "the only 'live' in its description is the disclaimer 'no live price feed is wired yet'",
};

describe("widgetFactory catalogue wiring", () => {
  it("resolves every catalogue widget, and every extra component is a documented retirement", () => {
    // This used to assert a strict bijection. Merged widgets break that by
    // design: a retired id leaves the picker but MUST keep resolving, because
    // Dockview looks a saved panel's component up in this map alone and
    // TerminalRoute discards the operator's entire saved tab when one fails.
    const catalogIds = widgetCatalog.map((widget) => widget.id);
    const componentIds = Object.keys(widgetComponents);

    expect(new Set(catalogIds).size).toBe(catalogIds.length);
    // Every catalogue widget resolves.
    for (const id of catalogIds) {
      expect(componentIds).toContain(id);
    }
    // Every extra resolvable id is an intentional, documented retirement.
    const extras = componentIds.filter((id) => !catalogIds.includes(id)).sort();
    expect(extras).toEqual(Object.keys(RETIRED_WIDGET_IDS).sort());
  });

  it("keeps every retired widget id loadable so saved layouts survive", () => {
    // A retired id that stopped resolving would not degrade one panel — it
    // would wipe the whole workspace tab (TerminalRoute's fromJSON catch).
    for (const [retiredId, spec] of Object.entries(RETIRED_WIDGET_IDS)) {
      expect(widgetComponents[retiredId], `${retiredId} must stay resolvable`).toBeTruthy();
      if (isMovedWidget(spec)) {
        // Tool/route-absorbed retirement: it renders a pointer panel, so the
        // requirement is a named destination, not a canonical widget.
        expect(spec.movedTo.destination.length).toBeGreaterThan(0);
      } else {
        // Its canonical target must itself be a live widget.
        expect(widgetComponents[spec.component], `${retiredId} → ${spec.component}`).toBeTruthy();
        expect(widgetCatalog.map((w) => w.id)).toContain(spec.component);
      }
      expect(spec.note.length).toBeGreaterThan(0);
    }
  });


  it("uses params a canonical actually understands", () => {
    // Every canonical resolves its view/tab param with a silent fallback to a
    // default, so a typo (`view: "skewe"`) reopens the WRONG view with a green
    // suite. This pins the accepted vocabulary per canonical: adding a
    // retirement with an unknown value now fails here instead of shipping.
    const ACCEPTED: Record<string, Record<string, readonly string[]>> = {
      orderflow: { view: ["footprint", "footprint+delta", "heatmap"] },
      ivsmile: { view: ["smile", "skew"] },
      gammadensity: { view: ["density", "exposure"] },
      domheatmap: { view: ["live", "replay"], scale: ["log", "gamma"] },
      greeksheatmap: {
        projection: ["grid", "surface"],
        metric: ["iv", "delta", "gamma", "theta", "vega"],
      },
      timesales: { view: ["tape", "stats"] },
      straddle: { view: ["straddle", "impliedmove"] },
      oichart: { view: ["bars", "butterfly", "heat", "signals"] },
      positions: { view: ["table", "net", "heat"], group: ["sector", "exchange", "flat"] },
      calculator: { tab: ["sizing", "target", "brokerage", "margin"] },
      conditionscanner: { view: ["scans", "sectors"] },
      marketoverview: {
        tab: ["breadth", "sectors", "rotation", "flows", "indices", "contribution"],
        view: ["treemap", "grid", "table", "bars", "heatmap", "sectors", "portfolio"],
      },
      pnlmonitor: { view: ["live", "summary", "drawdown"] },
      // Param-free canonicals — listed so the completeness check below can
      // tell "no params to check" apart from "someone forgot to add a row".
      fills: {},
      indexstrip: {},
      // Chart's params (symbol, interval, syncGroup, optionLeg) are free-form
      // rather than a closed vocabulary, so there is nothing to enumerate.
      chart: {},
      // Option Chain and Risk take no closed-vocabulary view params.
      optionchain: {},
      riskdashboard: {},
      orderladder: {},
    };

    for (const [retiredId, spec] of Object.entries(RETIRED_WIDGET_IDS)) {
      if (isMovedWidget(spec)) continue; // pointer panels take no params
      const accepted = ACCEPTED[spec.component];
      // An unlisted canonical used to `continue` silently, which is how seven
      // Market Overview retirements and both P&L Monitor ones skipped the very
      // check this test exists for. A missing row is now a failure.
      expect(
        accepted,
        `${retiredId} → ${spec.component} has no ACCEPTED vocabulary row, so `
        + "its params are unchecked — add one (use {} if it takes none)",
      ).toBeDefined();
      if (!accepted || !spec.params) continue;
      for (const [key, value] of Object.entries(spec.params)) {
        const vocabulary = accepted[key];
        if (!vocabulary) continue; // free-form param (symbol, tick, scan key)
        expect(
          vocabulary,
          `${retiredId} → ${spec.component} passes ${key}="${String(value)}", `
          + `which is not one of ${vocabulary.join(" | ")} — it would silently `
          + "fall back to the canonical's default view",
        ).toContain(value);
      }
    }
  });

  it("documents the current terminal widget category split", () => {
    const counts = widgetCatalog.reduce<Record<string, number>>((acc, widget) => {
      acc[widget.category] = (acc[widget.category] ?? 0) + 1;
      return acc;
    }, {});

    // Counts drop as widgets merge. docs/ARCHITECTURE.md, docs/USER_GUIDE.md
    // and the site's capabilities test pin these same numbers — update all
    // four together.
    expect(widgetCatalog).toHaveLength(71);
    expect(counts).toEqual({
      Analysis: 31,
      Trading: 18,
      Utility: 22,
    });
  });

  it("resolves every catalogue icon in the WidgetPicker ICON_MAP", () => {
    // A name missing from ICON_MAP silently renders the generic Box icon in
    // the picker — at one point 38 of 64 catalogue icons were missing.
    const missing = widgetCatalog
      .map((w) => w.icon)
      .filter((icon) => !(icon in ICON_MAP));
    expect(missing).toEqual([]);
  });

  it("resolves every catalogue widget to a source file on disk", () => {
    // The capability scan below reads these files. If an id stopped resolving
    // the scan would silently pass on an empty string, so pin resolution
    // separately and loudly.
    const unresolved = widgetCatalog
      .map((widget) => widget.id)
      .filter((id) => {
        const modulePath = WIDGET_MODULES.get(id);
        return !modulePath || !existsSync(join(SRC_ROOT, `${modulePath}.tsx`));
      });
    expect(unresolved).toEqual([]);
  });

  it("never advertises a capability the widget's own source has no trace of", () => {
    // Catalogue-truth guard. The picker's description is the only promise most
    // operators ever read, and it drifted badly: Telegram alerts with no
    // Telegram, AI-generated ideas with no network call, a Sharpe ratio that
    // was never computed.
    //
    // LIMITS — this is a heuristic, deliberately:
    //   * It only checks the phrases in CAPABILITY_CLAIMS. A false claim
    //     phrased in words nobody listed still sails through; add the phrase
    //     when you find one.
    //   * Evidence is a token in the source, not behaviour. A comment, a dead
    //     import or a variable name satisfies it — it catches "this widget has
    //     no idea what that word means", not "this widget does it correctly".
    //   * It says nothing about claims of *scale* ("up to five instruments"
    //     when MAX_SLOTS is 4) or of *form* ("four charts" for a table), which
    //     need a human reading the widget.
    const failures: string[] = [];

    for (const widget of widgetCatalog) {
      const description = widget.description ?? "";
      const source = widgetSource(widget.id);
      for (const { claim, evidence, why } of CAPABILITY_CLAIMS) {
        if (!claim.test(description)) continue;
        if (evidence.test(source)) continue;
        failures.push(
          `${widget.id}: description matches ${String(claim)} but its source has no ${String(evidence)} — ${why}`,
        );
      }
    }

    expect(failures).toEqual([]);
  });

  it("never promises live data from a widget that fetches nothing", () => {
    // The sibling guard above pins *named* capabilities (Telegram, Sharpe,
    // Kelly…). It said nothing about the broadest claim of all — that the
    // numbers move — so a batch of hardcoded-array widgets shipped describing
    // themselves as "Live currency converter", "Real-time large options trade
    // scanner" and "intraday performance" while carrying a permanent
    // sample-data badge in their own header. A description that promises a
    // feed must come from a widget that has one.
    const failures: string[] = [];

    for (const widget of widgetCatalog) {
      const description = widget.description ?? "";
      if (!LIVE_DATA_CLAIM.test(description)) continue;
      if (LIVE_DATA_EVIDENCE.test(widgetSource(widget.id))) continue;
      const reason = LIVE_CLAIM_EXEMPTIONS[widget.id];
      if (reason) continue;
      failures.push(
        `${widget.id}: description claims live/real-time/intraday data `
        + `("${description}") but its source has no data call `
        + `(${String(LIVE_DATA_EVIDENCE)}). Reword the description to disclose `
        + "the static/sample source, or add an entry to LIVE_CLAIM_EXEMPTIONS "
        + "with the reason.",
      );
    }

    expect(failures.sort()).toEqual([]);
  });

  it("keeps every live-claim exemption real, needed and documented", () => {
    // An exemption that outlives its reason is worse than no guard: it reads
    // as "audited and fine". Pin all three ways one can rot — a stale id, a
    // widget that has since grown a data call, and a description that no
    // longer contains the word the exemption was granted for.
    const stale: string[] = [];

    for (const [id, reason] of Object.entries(LIVE_CLAIM_EXEMPTIONS)) {
      expect(reason.trim().length, `${id} needs a written reason`).toBeGreaterThan(0);

      const widget = widgetCatalog.find((entry) => entry.id === id);
      if (!widget) {
        stale.push(`${id}: exempted but no longer in the catalogue — drop the entry`);
        continue;
      }
      if (!LIVE_DATA_CLAIM.test(widget.description ?? "")) {
        stale.push(`${id}: description no longer claims live data — drop the entry`);
      }
      if (LIVE_DATA_EVIDENCE.test(widgetSource(id))) {
        stale.push(`${id}: widget now has a data call — drop the entry, it is covered`);
      }
    }

    expect(stale.sort()).toEqual([]);
  });

  it("keeps the two journal surfaces distinguishable in the picker", () => {
    // Fills (which absorbed Trade Log) reads the auto-recorded fills
    // (/api/v1/trades/journal + tradebook); Journal Entries is full CRUD over
    // the annotated SQLite+FTS5 store (/api/v1/journal/entries). The fills
    // surface must not present itself as somewhere you write journal entries.
    const fills = widgetCatalog.find((widget) => widget.id === "fills");
    const journal = widgetCatalog.find((widget) => widget.id === "tradejournal");

    expect(fills?.name).not.toBe(journal?.name);
    expect(fills?.description).not.toBe(journal?.description);
    expect(fills?.description).not.toMatch(/write|create entries/i);
    expect(journal?.description).toMatch(/write|edit|annotat/i);
  });

  it("keeps Spread View out of the catalogue after its demotion to template data", () => {
    // It was four hardcoded two-leg spreads with no data source and a
    // permanently disabled execute button. The spreads are now entries in
    // lib/strategyTemplates.ts and its economic validator — the one thing it
    // uniquely owned — moved into the options builder.
    expect(widgetCatalog.find((widget) => widget.id === "spreadview")).toBeUndefined();
    expect(Object.keys(RETIRED_WIDGET_IDS)).toContain("spreadview");
  });
});
