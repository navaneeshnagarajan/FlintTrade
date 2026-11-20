import { isPublicDemoBuild } from "@/lib/demoSession";
import { developerEnabled } from "@/chrome/DeveloperPreference";
import { lazy, Suspense } from "react";
import type { ReactNode } from "react";
import type { TabNode } from "flexlayout-react";
import { flexLayoutFactory } from "./widgetFactory";
import { HOME_WIDGET_COMPONENTS } from "@/routes/home/homeWidgetRegistry";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { widgetAllowed, type AppId } from "./appCatalog";
import { EmbeddedPage } from "@/components/layout/Page";
import { Callout } from "@/components/ui/Callout";
import { LoadingState } from "@/components/ui/states";

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

/** Page gutter and width for sections that were written to sit inside Settings. */
function PanelBody({ children }: { children: ReactNode }) {
  return <div className="mx-auto w-full max-w-[var(--ft-page-width)] px-[var(--ft-page-gutter)] py-5">{children}</div>;
}

export function appWidgetFactory(app: AppId, node: TabNode): ReactNode {
  const id = node.getComponent() ?? "";
  if (!widgetAllowed(app, id)) return <div className="p-4"><Callout tone="warning" role="alert">This widget is not compatible with {app}. No execution scope was changed.</Callout></div>;
  if (isPublicDemoBuild() && ["broker-connections", "broker-roles", "preferences", "aibackends", "obsidian", "system-console", "model-routing", "learning-permissions", "knowledge-library", "experiment-evidence", "observability", "skill-drafts"].includes(id)) return <section className="mx-auto max-w-2xl space-y-3 p-6"><h2 className="ft-text-section-title text-text-primary">{node.getName()}</h2><p className="text-sm text-text-secondary">This public preview has no accounts, credentials or connected services. Install FlintTrade to use these controls against your own backend.</p><p className="text-sm text-text-muted">The frozen preview cannot configure providers, change security or grant Live authority.</p></section>;
  if (["system-console", "observability"].includes(id) && !developerEnabled()) return <div className="p-4"><Callout tone="neutral">Enable Developer features in Settings → General to open the experimental system console. Monitoring remains available without Developer.</Callout></div>;
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
    case "broker-connections": view = <PanelBody><BrokerConnections pollAccounts={false} /></PanelBody>; break;
    case "broker-roles": view = <BrokerRoles />; break;
    case "preferences": view = <Preferences />; break;
    case "monitoring": view = <PanelBody><Monitoring /></PanelBody>; break;
    case "system-console": view = <SystemConsole />; break;
    case "historical-downloads": view = <PanelBody><HistoricalDownloads /></PanelBody>; break;
    case "local-data": view = <PanelBody><LocalData /></PanelBody>; break;
    default: {
      const HomeCard = HOME_WIDGET_COMPONENTS[id.replace(/^overview:/, "")];
      view = id.startsWith("overview:") && HomeCard ? <HomeCard /> : flexLayoutFactory(node);
    }
  }
  return <ErrorBoundary><Suspense fallback={<LoadingState fill label={`Loading ${node.getName()}…`} />}>
    <div className="h-full min-h-0 min-w-0 overflow-auto" data-app-widget={id}><EmbeddedPage>{view}</EmbeddedPage></div>
  </Suspense></ErrorBoundary>;
}
