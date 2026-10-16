import { isPublicDemoBuild } from "@/lib/demoSession";
import { developerEnabled } from "@/chrome/DeveloperPreference";
import { lazy, Suspense } from "react";
import type { ReactNode } from "react";
import type { TabNode } from "flexlayout-react";
import { flexLayoutFactory } from "./widgetFactory";
import { HOME_WIDGET_COMPONENTS } from "@/routes/home/homeWidgetRegistry";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { widgetAllowed, type AppId } from "./appCatalog";

const Observability = lazy(() => import("@/admin/observability/ObservabilityDashboard"));
const SkillDrafts = lazy(() => import("@/tools/Settings/SkillSection").then(m => ({ default: m.SkillDraftReviewSection })));
const LearningPermissions = lazy(() => import("@/components/help/LearningPermissions"));
const KnowledgeLibrary = lazy(() => import("@/components/help/KnowledgeSelector"));
const TestingEvidence = lazy(() => import("@/routes/TestingEvidencePanel"));
const Diagnostics = lazy(() => import("@/chrome/SystemDiagnostics").then(m => ({ default: m.SystemDiagnostics })));
const ModelRouting = lazy(() => import("@/components/help/ModelRoutingPanel"));
const Research = lazy(() => import("@/routes/LabRoute"));
const Investments = lazy(() => import("@/routes/InvestRoute"));
const RunControl = lazy(() => import("@/routes/AutomateRoute"));
const AIWorkspace = lazy(() => import("@/routes/AIRoute"));
const TradeReview = lazy(() => import("@/tools/TradeJournal/TradeJournalTool"));
const Learning = lazy(() => import("@/routes/LearnRoute"));
const BrokerConnections = lazy(() => import("@/components/account/BrokerConnect").then(m => ({ default: m.BrokerConnect })));
const BrokerRoles = lazy(() => import("@/routes/DittoRoute"));
const Preferences = lazy(() => import("@/routes/SettingsRoute"));
const Monitoring = lazy(() => import("@/tools/Settings/MonitoringSection").then(m => ({ default: m.MonitoringSection })));
const SystemConsole = lazy(() => import("@/routes/AdminRoute"));
const HistoricalDownloads = lazy(() => import("@/tools/Settings/HistoricalDownloadPanel").then(m => ({ default: m.HistoricalDownloadPanel })));
const LocalData = lazy(() => import("@/tools/Settings/LocalDataPanel").then(m => ({ default: m.LocalDataPanel })));

export function appWidgetFactory(app: AppId, node: TabNode): ReactNode {
  const id = node.getComponent() ?? "";
  if (!widgetAllowed(app, id)) return <p role="alert">This widget is not compatible with {app}. No execution scope was changed.</p>;
  if (isPublicDemoBuild() && ["broker-connections", "broker-roles", "preferences", "aibackends", "obsidian", "system-console", "model-routing", "learning-permissions", "knowledge-library", "experiment-evidence", "observability", "skill-drafts"].includes(id)) return <section className="space-y-3 p-6"><h2 className="text-lg">{node.getName()}</h2><p>This public preview has no accounts, credentials or connected services. Install FlintTrade to use these controls against your own backend.</p><p className="text-sm text-text-muted">The frozen preview cannot configure providers, change security or grant Live authority.</p></section>;
  if (["system-console", "observability"].includes(id) && !developerEnabled()) return <p className="p-4 text-sm">Enable Developer features in Settings → General to open the experimental system console. Monitoring remains available without Developer.</p>;
  let view: ReactNode;
  switch (id) {
    case "observability": view = <Observability />; break;
    case "skill-drafts": view = <div className="space-y-4 p-4"><p className="text-xs text-text-muted">Optional compatibility review. This is not a human experience level and is not a required queue for independently validated core learning.</p><SkillDrafts /></div>; break;
    case "learning-permissions": view = <LearningPermissions />; break;
    case "knowledge-library": view = <KnowledgeLibrary />; break;
    case "experiment-evidence": view = <TestingEvidence />; break;
    case "core-diagnostics": view = <Diagnostics />; break;
    case "model-routing": view = <ModelRouting />; break;
    case "research": view = <Research />; break;
    case "investments": view = <Investments />; break;
    case "run-control": view = <RunControl />; break;
    case "ai-centre": view = <AIWorkspace />; break;
    case "trade-review": view = <TradeReview onClose={() => window.dispatchEvent(new CustomEvent("flinttrade:navigate", { detail: "/terminal" }))} />; break;
    case "learning": view = <Learning />; break;
    case "broker-connections": view = <BrokerConnections pollAccounts={false} />; break;
    case "broker-roles": view = <BrokerRoles />; break;
    case "preferences": view = <Preferences />; break;
    case "monitoring": view = <Monitoring />; break;
    case "system-console": view = <SystemConsole />; break;
    case "historical-downloads": view = <HistoricalDownloads />; break;
    case "local-data": view = <LocalData />; break;
    default: {
      const HomeCard = HOME_WIDGET_COMPONENTS[id.replace(/^overview:/, "")];
      view = id.startsWith("overview:") && HomeCard ? <HomeCard /> : flexLayoutFactory(node);
    }
  }
  return <ErrorBoundary><Suspense fallback={<p role="status" className="p-4 text-text-muted">Loading {node.getName()}…</p>}>
    <div className="h-full min-h-0 min-w-0 overflow-auto" data-app-widget={id}>{view}</div>
  </Suspense></ErrorBoundary>;
}
