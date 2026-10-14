import { widgetCatalog } from "./widgetFactory";
import { HOME_WIDGET_CATALOG } from "@/routes/home/homeWidgetRegistry";

export const APPS = [
  { id: "terminal", name: "Terminal", path: "/terminal", description: "Markets, account overview and manual trading" },
  { id: "testing", name: "Testing", path: "/testing", description: "Strategy research, Paper forward tests and datasets" },
  { id: "portfolio", name: "Portfolio", path: "/portfolio", description: "Investments, holdings, allocation and goals" },
  { id: "automation", name: "Automation", path: "/automation", description: "Strategies, schedules, AI runs and approvals" },
  { id: "reports", name: "Reports", path: "/reports", description: "Journal, performance, notes and coaching" },
  { id: "learn", name: "Learn", path: "/learn", description: "Lessons, glossary, strategies and documentation" },
  { id: "brokers", name: "Brokers", path: "/brokers", description: "Connections, account roles and copying readiness" },
  { id: "settings", name: "Settings", path: "/settings", description: "Security, preferences and integrations" },
  { id: "system", name: "System", path: "/system", description: "Health, network, resources and operational evidence" },
] as const;
export type AppId = typeof APPS[number]["id"];

const ALIASES: Record<string, AppId> = { "/home": "terminal", "/trade": "terminal", "/invest": "portfolio", "/lab": "testing", "/automate": "automation", "/ai": "automation", "/ditto": "brokers", "/admin": "system", "/admin/observability": "system" };
export function appForPath(path: string): AppId | undefined {
  return APPS.find(app => app.path === path)?.id ?? ALIASES[path];
}
export function appPath(id: AppId): string { return APPS.find(app => app.id === id)!.path; }

export interface AppWidget {
  id: string;
  name: string;
  description: string;
  apps: readonly AppId[];
  minWidth: number;
  minHeight: number;
}
// Every existing active widget has an explicit home. Testing is deliberately an
// allowlist: the account-wide order renderers have no independent Paper scope.
const HOMES: Record<string, readonly AppId[]> = {
  holdings: ["portfolio", "terminal"], portfolioallocation: ["portfolio"], portfoliooptimiser: ["portfolio"], portfoliopivot: ["portfolio", "reports"],
  tradecopier: ["brokers"], reconciliation: ["brokers", "terminal"],
  strategymonitor: ["automation"], actioncenter: ["automation", "terminal"],
  aibackends: ["automation", "settings"], aiteam: ["automation", "terminal"], aiadvisor: ["automation", "terminal"], obsidian: ["automation", "reports"],
  tradejournal: ["reports"], audittrail: ["reports", "system"], tradeidea: ["reports", "terminal"],
  historicalchain: ["testing", "terminal"], seasonality: ["testing", "terminal"], calculator: ["testing", "portfolio", "terminal"],
  strategytemplates: ["testing", "learn"], currencyconverter: ["portfolio", "terminal"],
};
const surfaces: Array<Pick<AppWidget, "id" | "name" | "description" | "apps">> = [
  { id: "observability", name: "Operational observability", description: "Existing metrics, security/rate-limit controls, monitoring and audit composition", apps: ["system"] },
  { id: "skill-drafts", name: "Agent skill drafts", description: "Existing optional draft read/review actions, separate from human experience preferences", apps: ["automation", "settings"] },
  { id: "learning-permissions", name: "Learning permissions", description: "Explicit server-confirmed learning scope, receipts and revocation", apps: ["automation", "settings"] },
  { id: "knowledge-library", name: "Shared knowledge", description: "Authenticated canonical full procedures and explicit task context", apps: ["learn", "automation", "settings"] },
  { id: "experiment-evidence", name: "Experiment evidence", description: "Read immutable R5 trial, experiment, training job and adoption records", apps: ["testing"] },
  { id: "core-diagnostics", name: "Core diagnostics", description: "Actual R4 resource, acquisition, model/job and network observation evidence", apps: ["system"] },
  { id: "model-routing", name: "Model connections and tasks", description: "Core-owned fixed or routed advisory tasks, exact admission, quota and durable receipts", apps: ["automation", "settings"] },
  { id: "research", name: "Strategy research", description: "Builder, Pine editor, backtests, optimisation and results", apps: ["testing"] },
  { id: "investments", name: "Investments", description: "All investment and portfolio tools", apps: ["portfolio"] },
  { id: "run-control", name: "Run control", description: "Schedules, strategies, webhooks, logs and stop controls", apps: ["automation"] },
  { id: "ai-centre", name: "AI workspace", description: "Analysis, chat, agents, knowledge and history", apps: ["automation"] },
  { id: "trade-review", name: "Trade review", description: "Log, Session, Performance, Calendar, Deep Analytics, Notes and Coach", apps: ["reports"] },
  { id: "learning", name: "Learning library", description: "Market basics, glossary, strategy library, Practice guidance and resources", apps: ["learn"] },
  { id: "broker-connections", name: "Broker connections", description: "Native connection setup and exact account lifecycle", apps: ["brokers"] },
  { id: "broker-roles", name: "Account roles and copying", description: "Execution/data roles, copying controls and qualification restrictions", apps: ["brokers"] },
  { id: "preferences", name: "Preferences and security", description: "Shared settings, support, providers and help", apps: ["settings"] },
  { id: "monitoring", name: "Monitoring", description: "Host health, traffic, connection and order latency", apps: ["system"] },
  { id: "system-console", name: "System console", description: "Logs, metrics and diagnostics tools", apps: ["system"] },
  { id: "historical-downloads", name: "Historical downloads", description: "Download jobs and coverage progress", apps: ["testing"] },
  { id: "local-data", name: "Local datasets", description: "Local OHLCV, tick capture and bhavcopy", apps: ["testing"] },
];
export const APP_WIDGETS: readonly AppWidget[] = [
  ...widgetCatalog.map(widget => ({ ...widget, description: widget.description ?? widget.name, apps: HOMES[widget.id] ?? ["terminal"] as const, minWidth: 280, minHeight: 200 })),
  ...HOME_WIDGET_CATALOG.map(widget => ({ id: `overview:${widget.componentId}`, name: `${widget.name} overview`, description: widget.description, apps: (widget.domain === "invest" || widget.componentId === "PortfolioCard" ? ["terminal", "portfolio"] : ["terminal"]) as AppId[], minWidth: 280, minHeight: 180 })),
  ...surfaces.map(widget => ({ ...widget, minWidth: 400, minHeight: 260 })),
];
export function widgetsForApp(app: AppId): readonly AppWidget[] { return APP_WIDGETS.filter(widget => widget.apps.includes(app)); }
export function widgetAllowed(app: AppId, id: string): boolean { return APP_WIDGETS.some(widget => widget.id === id && widget.apps.includes(app)); }
export function homeForWidget(id: string, current?: AppId): AppId | undefined {
  const widget = APP_WIDGETS.find(widget => widget.id === id);
  return current && widget?.apps.includes(current) ? current : widget?.apps[0];
}
