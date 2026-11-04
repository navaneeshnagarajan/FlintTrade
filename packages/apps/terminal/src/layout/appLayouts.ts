import { Model, type IJsonModel } from "flexlayout-react";
import { APP_WIDGETS, type AppId, widgetAllowed } from "./appCatalog";
import { rowJson, tabJson, tabsetJson, workspaceJson } from "./flexLayoutAdapter";
import { buildPresetJsonById } from "./workspacePresets";

export const APP_LAYOUT_NAMESPACE = "flinttrade:app-layouts:v1";
export const DEFAULT_APP_WIDGETS: Record<AppId, string[]> = {
  terminal: ["overview:WelcomeCard", "chart", "watchlist", "positions", "orders"],
  testing: ["research", "experiment-evidence"], portfolio: ["investments"], automation: ["run-control"],
  reports: ["trade-review"], learn: ["learning"], brokers: ["broker-connections", "broker-roles"],
  settings: ["preferences"], system: ["core-diagnostics"],
};
export const APP_PRESETS: Record<AppId, readonly { id: string; name: string; template?: boolean }[]> = {
  terminal: [
    { id: "scalper-zone", name: "Scalper zone", template: true },
    { id: "volatility-trading", name: "Volatility trading", template: true },
    { id: "classic", name: "Classic", template: true },
    { id: "watchlist-driven", name: "Watchlist driven", template: true },
    { id: "market-overview", name: "Market watch", template: true },
    { id: "chart-focus", name: "Chart focus" }, { id: "overview", name: "Overview" },
    { id: "trader", name: "Trader" }, { id: "market-watch", name: "Market watch (FlintTrade)" },
    { id: "options-scalper", name: "Option Scalper" }, { id: "multi-chart", name: "Multi chart" },
  ],
  testing: [{ id: "default", name: "Research" }, { id: "data", name: "Data library" }],
  portfolio: [{ id: "default", name: "Investments" }, { id: "allocation", name: "Allocation" }],
  automation: [{ id: "default", name: "Operations" }, { id: "ai", name: "AI and knowledge" }],
  reports: [{ id: "default", name: "Review" }, { id: "journal", name: "Journal and notes" }],
  learn: [{ id: "default", name: "Library" }], brokers: [{ id: "default", name: "Connections and roles" }],
  settings: [{ id: "default", name: "Preferences" }], system: [{ id: "default", name: "Health" }, { id: "diagnostics", name: "Diagnostics" }],
};
export function buildAppPreset(app: AppId, preset: string): IJsonModel {
  // Captured desktop compositions use this same app-local layout owner.
  // Existing saved JSON and the earlier FlintTrade presets are not migrated.
  if (app === "terminal" && ["scalper-zone", "volatility-trading", "classic", "market-overview"].includes(preset)) {
    const tab = (id: string) => tabJson(id, APP_WIDGETS.find(widget => widget.id === id)!.name, { id: `${app}:${id}`, params: { channel: "none" } });
    const group = (weight: number, ids: string[]) => tabsetJson(weight, ids.map(tab));
    if (preset === "scalper-zone") return workspaceJson(rowJson(100, [group(75, ["scalper"]), group(25, ["positions", "orders", "optionchain"])]));
    if (preset === "classic") return workspaceJson(rowJson(100, [group(52, ["chart"]), group(23, ["positions", "orders"]), group(25, ["optionchain", "watchlist"])]));
    if (preset === "volatility-trading") return workspaceJson(rowJson(100, [rowJson(63, [group(50, ["chart", "straddle"]), rowJson(50, [group(52, ["oichart"]), group(48, ["positions", "orders"])])]), group(37, ["optionchain", "watchlist"])]));
    return workspaceJson(rowJson(100, [group(48, ["chart"]), rowJson(52, [group(50, ["straddle"]), group(50, ["oichart"])])]));
  }
  // Fresh desks follow the captured watchlist-left, chart-right composition.
  // Persisted Current/named compositions are read before this fallback; no
  // migration, reset or account/channel mutation. Chart focus is an opt-in mirror.
  if (app === "terminal" && ["default", "chart-focus", "watchlist-driven"].includes(preset)) {
    const tab = (id: string) => tabJson(id, APP_WIDGETS.find(widget => widget.id === id)!.name, {
      id: `${app}:${id}`, params: { channel: "none" },
    });
    const chart = { ...tabsetJson(72, [tab("chart"), tab("positions"), tab("orders")]), active: true, selected: 0 };
    const watchlist = tabsetJson(28, preset === "watchlist-driven"
      ? [tab("watchlist")]
      : [tab("watchlist"), tab("overview:WelcomeCard")]);
    return workspaceJson(rowJson(100, preset === "chart-focus" ? [chart, watchlist] : [watchlist, chart]));
  }
  if (app === "terminal" && ["market-watch", "options-scalper", "multi-chart"].includes(preset)) {
    const built = buildPresetJsonById(preset);
    if (built && validateAppLayout(app, built)) return built;
  }
  const special: Record<string, string[]> = {
    "testing:data": ["historical-downloads", "local-data", "historicalchain"],
    "portfolio:allocation": ["portfolioallocation", "portfoliooptimiser", "holdings"],
    "automation:ai": ["model-routing", "ai-centre", "aiteam", "aibackends", "obsidian"],
    "reports:journal": ["tradejournal", "trade-review", "obsidian"],
    "system:diagnostics": ["core-diagnostics", "monitoring", "system-console", "audittrail"],
  };
  const ids = special[`${app}:${preset}`] ?? DEFAULT_APP_WIDGETS[app];
  const tabs = ids.map(id => tabJson(id, APP_WIDGETS.find(w => w.id === id)!.name, { id: `${app}:${id}`, params: { channel: "none" } }));
  // Wide overview separates account summary, market and books. All other tools
  // start in tabsets so a full-sized operational form is usable immediately.
  if (app === "terminal" && ids === DEFAULT_APP_WIDGETS.terminal) {
    return workspaceJson(rowJson(100, [
      rowJson(32, [tabsetJson(45, [tabs[0]]), tabsetJson(55, [tabs[2]])]),
      rowJson(68, [tabsetJson(65, [tabs[1]]), tabsetJson(35, [tabs[3], tabs[4]])]),
    ]));
  }
  return workspaceJson(rowJson(100, [tabsetJson(100, tabs)]));
}
const FORBIDDEN = /^(?:account(?:Id|_id)?|broker(?:Id|_id)?|token|password|secret|apiKey|api_key|grant|authority|armed|executionScope|mode|runId)$/i;
function safeConfig(value: unknown): boolean {
  if (!value || typeof value !== "object") return true;
  return Object.entries(value).every(([key, child]) => !FORBIDDEN.test(key) && safeConfig(child));
}
/** Fresh presentation-only envelope: rejects cross-purpose/authority payloads,
 * unknown nodes and popouts rather than restoring a hidden execution surface. */
export function validateAppLayout(app: AppId, value: unknown): value is IJsonModel {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  const hasEntries = (entry: unknown) => entry !== undefined && (entry === null || typeof entry !== "object" || Object.keys(entry).length > 0);
  if (hasEntries(v.subLayouts) || hasEntries(v.popouts) || (Array.isArray(v.borders) && v.borders.length)) return false;
  let count = 0;
  function visit(node: unknown): boolean {
    if (!node || typeof node !== "object") return false;
    const n = node as Record<string, unknown>;
    if (n.type === "tab") {
      count += 1;
      return typeof n.component === "string" && widgetAllowed(app, n.component) && safeConfig(n.config);
    }
    return (n.type === "row" || n.type === "tabset") && Array.isArray(n.children) && n.children.every(visit);
  }
  if (!visit(v.layout) || count > 100) return false;
  try { Model.fromJson(value as IJsonModel); return true; } catch { return false; }
}
export function readAppLayouts(app: AppId): Record<string, IJsonModel> {
  const raw = localStorage.getItem(`${APP_LAYOUT_NAMESPACE}:${app}`);
  if (!raw) return {};
  const parsed: unknown = JSON.parse(raw);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Layout storage is unreadable; saved data was not replaced.");
  if (!Object.values(parsed).every(layout => validateAppLayout(app, layout))) throw new Error("Layout contains an incompatible widget or execution authority; saved data was not replaced.");
  return parsed as Record<string, IJsonModel>;
}
export function saveAppLayout(app: AppId, name: string, layout: IJsonModel): void {
  if (!name.trim() || name.length > 100 || ["__proto__", "constructor", "prototype"].includes(name)) throw new Error("Choose a valid layout name.");
  if (!validateAppLayout(app, layout)) throw new Error("Incompatible layout; no changes saved.");
  const saved = readAppLayouts(app);
  localStorage.setItem(`${APP_LAYOUT_NAMESPACE}:${app}`, JSON.stringify({ ...saved, [name]: layout }));
}
