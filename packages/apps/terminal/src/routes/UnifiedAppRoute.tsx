import { Activity, useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { Actions, Layout, Model, type TabNode, type IJsonModel } from "flexlayout-react";
import "flexlayout-react/style/combined.css";
import { APPS, APP_WIDGETS, widgetAllowed, widgetsForApp, type AppId } from "@/layout/appCatalog";
import { APP_PRESETS, buildAppPreset, readAppLayouts, saveAppLayout, validateAppLayout } from "@/layout/appLayouts";
import { appWidgetFactory } from "@/layout/appWidgetFactory";
import { createWorkspaceApi, renderWorkspaceTabExtras } from "@/layout/flexLayoutAdapter";
import { useThemeStore } from "@/stores/themeStore";
import { useModeStore } from "@/stores/modeStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useCanonicalScopeKey } from "@/services/canonicalData";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { KillSwitchPill } from "./TerminalRoute";
import { InstrumentLinks } from "@/chrome/InstrumentLinks";
import { PracticeLaterSetup } from "./SetupAccountRoute";

interface WidgetRequest { widgetId?: string; props?: Record<string, unknown>; title?: string }
function wideJson(model: Model): IJsonModel {
  const json = model.toJson();
  function strip(node: { children?: unknown[]; maximized?: boolean }) {
    delete node.maximized;
    node.children?.forEach(child => strip(child as typeof node));
  }
  strip(json.layout);
  return json;
}
function panels(model: Model): TabNode[] {
  const tabs: TabNode[] = [];
  model.visitNodes(node => { if (node.getType() === "tab") tabs.push(node as TabNode); });
  return tabs;
}

/** One composition implementation for every app. Auth, feeds, queries and
 * execution owners remain above this presentation in AppLayout/QueryProvider. */
export default function UnifiedAppRoute({ app, active = true }: { app: AppId; active?: boolean }) {
  // Activity disconnects the contents' store subscriptions while hidden. Keep
  // scope notifications live here so each view's own key can retire private
  // state, including observed A→B→A, without rekeying the docking tree.
  useCanonicalScopeKey();
  const meta = APPS.find(item => item.id === app)!;
  const location = useLocation();
  const navigate = useNavigate();
  const mode = useModeStore(s => s.mode);
  const account = useBrokerStore(s => s.activeAccountId);
  const theme = useThemeStore(s => s.getResolvedMode());
  const [initial] = useState(() => {
    try { return { model: Model.fromJson(readAppLayouts(app)["Current"] ?? buildAppPreset(app, "default")), error: "" }; }
    catch (error) { return { model: Model.fromJson(buildAppPreset(app, "default")), error: String(error) }; }
  });
  const [model, setModel] = useState(initial.model);
  const modelRef = useRef(model);
  modelRef.current = model;
  const [error, setError] = useState(initial.error);
  const [picker, setPicker] = useState(false);
  const [search, setSearch] = useState("");
  const [layoutName, setLayoutName] = useState("");
  const [savedNames, setSavedNames] = useState(() => { try { return Object.keys(readAppLayouts(app)).filter(name => name !== "Current"); } catch { return []; } });
  const [notice, setNotice] = useState("");
  const [compact, setCompact] = useState(false);
  const [revision, setRevision] = useState(0);
  const host = useRef<HTMLDivElement>(null);

  const persist = useCallback((current: Model) => {
    try { saveAppLayout(app, "Current", wideJson(current)); setError(""); }
    catch (problem) { setError(String(problem)); }
  }, [app]);
  useEffect(() => {
    if (!active) return;
    const listener = () => { persist(model); setRevision(v => v + 1); };
    model.addChangeListener(listener);
    return () => { model.removeChangeListener(listener); persist(model); };
  }, [active, model, persist]);
  useEffect(() => {
    if (!active || !host.current) return;
    const observer = new ResizeObserver(([entry]) => setCompact(entry.contentRect.width < 760 || entry.contentRect.height < 330));
    observer.observe(host.current);
    return () => observer.disconnect();
  }, [active]);
  // Maximisation is a projection on the SAME model, retaining mounted drafts
  // and widget identity. It is stripped from the persisted wide composition.
  useEffect(() => {
    if (!active) return;
    const maximized = model.getMaximizedTabset();
    if (compact && !maximized) {
      const target = model.getActiveTabset() ?? panels(model)[0]?.getParent();
      if (target) model.doAction(Actions.maximizeToggle(target.getId()));
    } else if (!compact && maximized) model.doAction(Actions.maximizeToggle(maximized.getId()));
  }, [active, compact, model, revision]);

  const add = useCallback((request: WidgetRequest) => {
    const id = request.widgetId;
    if (!id || !widgetAllowed(app, id)) { setError("This widget belongs to a different app. No account or mode was changed."); return; }
    const current = modelRef.current;
    const api = createWorkspaceApi(() => current, setModel);
    const meta = APP_WIDGETS.find(w => w.id === id)!;
    if (id === "orderpad" && api.retargetOrderPad(request.props ?? {}, request.title)) return;
    // Protect configuration/security and complete route forms from duplicate owners.
    const existing = panels(current).find(tab => tab.getComponent() === id);
    if (existing && ["preferences", "research", "investments", "learning", "run-control", "broker-roles", "ai-centre"].includes(id)) {
      current.doAction(Actions.selectTab(existing.getId())); return;
    }
    api.addPanel({ id: `${app}:${id}:${crypto.randomUUID()}`, component: id, title: request.title ?? meta.name, params: { channel: "none", ...request.props } });
    setPicker(false);
  }, [app]);
  useEffect(() => {
    if (!active) return;
    const request = (location.state as { openWidget?: WidgetRequest } | null)?.openWidget;
    if (request) { add(request); navigate(location.pathname + location.search + location.hash, { replace: true, state: null }); }
  }, [active, location, add, navigate]);
  useEffect(() => {
    if (!active) return;
    const widget = (event: Event) => add((event as CustomEvent<WidgetRequest>).detail);
    const preset = (event: Event) => {
      const id = (event as CustomEvent<{ presetId?: string }>).detail?.presetId;
      if (id && APP_PRESETS[app].some(p => p.id === id)) setModel(Model.fromJson(buildAppPreset(app, id)));
      else setError("This preset is not compatible with the current app.");
    };
    const reset = () => setModel(Model.fromJson(buildAppPreset(app, "default")));
    const escape = () => setPicker(false);
    window.addEventListener("flinttrade:app-widget", widget);
    window.addEventListener("flinttrade:apply-layout", preset);
    window.addEventListener("flinttrade:reset-layout", reset);
    window.addEventListener("flinttrade:escape", escape);
    return () => {
      window.removeEventListener("flinttrade:app-widget", widget);
      window.removeEventListener("flinttrade:apply-layout", preset);
      window.removeEventListener("flinttrade:reset-layout", reset);
      window.removeEventListener("flinttrade:escape", escape);
    };
  }, [active, app, add]);
  const exportLayout = useCallback(() => {
    const blob = new Blob([JSON.stringify({ version: 1, app, layout: wideJson(modelRef.current) }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob); const anchor = document.createElement("a");
    anchor.href = url; anchor.download = `flinttrade-${app}-layout.json`; anchor.click(); URL.revokeObjectURL(url);
  }, [app]);
  useEffect(() => { if (!active) return; window.addEventListener("flinttrade:export-layout", exportLayout); return () => window.removeEventListener("flinttrade:export-layout", exportLayout); }, [active, exportLayout]);
  async function importLayout(file?: File) {
    if (!file) return;
    try {
      if (file.size > 1_000_000) throw new Error("Layout file is too large.");
      const document: unknown = JSON.parse(await file.text());
      const envelope = document as { version?: unknown; app?: unknown; layout?: unknown };
      if (envelope?.version !== 1 || envelope.app !== app || !validateAppLayout(app, envelope.layout)) throw new Error("Not a compatible fresh app layout. Authority and legacy layouts cannot be imported.");
      setModel(Model.fromJson(envelope.layout)); setNotice("Imported presentation layout; execution unchanged.");
    } catch (e) { setError(String(e)); }
  }
  // Activity belongs INSIDE the ref-dependent docking tree. Hiding Layout
  // itself detaches its ref and makes its next render unmount every widget.
  const factory = useCallback((node: TabNode) => <Activity mode={active ? "visible" : "hidden"}>{appWidgetFactory(app, node)}</Activity>, [active, app]);
  const tabs = panels(model);
  function selectPanel(id: string) {
    const previous = model.getMaximizedTabset();
    if (previous) model.doAction(Actions.maximizeToggle(previous.getId()));
    model.doAction(Actions.selectTab(id));
    const parent = model.getNodeById(id)?.getParent();
    if (compact && parent) model.doAction(Actions.maximizeToggle(parent.getId()));
  }
  return <section className="flex h-full min-h-0 flex-col" aria-label={`${meta.name} app`} data-testid="unified-app">
    <Activity mode={active ? "visible" : "hidden"}>
    <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border-default bg-surface-base px-3 py-2">
      <h1 className="font-heading text-sm font-semibold">{meta.name}</h1>
      <label className="text-xs text-text-secondary">Preset <select aria-label={`${meta.name} preset`} className="rounded border border-border-default bg-surface-card p-1" defaultValue="" onChange={e => { if (e.target.value) setModel(Model.fromJson(buildAppPreset(app, e.target.value))); }}><option value="" disabled>Choose layout</option>{APP_PRESETS[app].map(p => <option value={p.id} key={p.id}>{p.name}</option>)}</select></label>
      <Button variant="outline" size="sm" onClick={() => setPicker(true)} aria-label="Add widget">+ Widget</Button>
      <Input aria-label="Layout name" value={layoutName} onChange={e => setLayoutName(e.target.value)} placeholder="Name this layout" className="h-8 w-36" />
      <Button variant="ghost" size="sm" onClick={() => { try { saveAppLayout(app, layoutName, wideJson(model)); setSavedNames(Object.keys(readAppLayouts(app)).filter(n => n !== "Current")); setNotice(`Saved ${layoutName}`); } catch (e) { setError(String(e)); } }}>Save layout</Button>
      <select aria-label="Restore saved layout" className="rounded border border-border-default bg-surface-card p-1 text-xs" value="" onChange={e => { try { const saved = readAppLayouts(app)[e.target.value]; if (validateAppLayout(app, saved)) { setModel(Model.fromJson(saved)); setNotice(`Restored ${e.target.value}`); } } catch (e) { setError(String(e)); } }}><option value="">Restore layout</option>{savedNames.map(n => <option key={n}>{n}</option>)}</select>
    </div>
    <details className="shrink-0 border-b border-border-default px-3 py-1 text-xs"><summary className="cursor-pointer">Layout actions</summary><div className="flex flex-wrap items-center gap-2 py-2"><Button size="sm" variant="outline" onClick={exportLayout}>Export layout</Button><label>Import layout <input aria-label="Import app layout" type="file" accept="application/json,.json" onChange={event => void importLayout(event.target.files?.[0])} /></label><Button size="sm" variant="ghost" onClick={() => setModel(Model.fromJson(buildAppPreset(app, "default")))}>Reset app layout</Button><span className="text-text-muted">Presentation only. Saved named layouts and all non-layout records are retained.</span></div></details>
    <p className="shrink-0 border-b border-border-default px-3 py-1 text-xs text-text-secondary" data-testid="app-execution-scope">
      {app === "testing" ? "Testing · Paper research scope only. Terminal account and Live authority are unchanged." : `${mode === "live" ? "Live" : "Sandbox"} · ${account || "No execution account selected"}`}
      {app === "terminal" ? " · Linking changes selections, never execution authority." : ""}
    </p>
    <InstrumentLinks app={app} />
    {app === "terminal" && <PracticeLaterSetup />}
    {error && <p role="alert" className="shrink-0 px-3 py-2 text-xs text-warning">{error}</p>}
    {notice && <p role="status" className="shrink-0 px-3 text-xs text-text-secondary">{notice}</p>}
    {compact && <label className="shrink-0 px-3 py-1 text-xs">Panel <select aria-label="Compact panel" className="max-w-full bg-surface-card p-1" onChange={e => selectPanel(e.target.value)} value={model.getActiveTabset()?.getSelectedNode()?.getId() ?? tabs[0]?.getId() ?? ""}>{tabs.map(tab => <option key={tab.getId()} value={tab.getId()}>{tab.getName()}</option>)}</select></label>}
    </Activity>
    <div ref={host} className={`relative min-h-0 flex-1 overflow-hidden flexlayout__theme_${theme === "light" ? "light" : "dark"}`} data-testid="app-layout">
      <Layout model={model} factory={factory} onRenderTab={renderWorkspaceTabExtras} realtimeResize />
      {!tabs.length && <div className="absolute inset-0 grid place-items-center"><Button onClick={() => setPicker(true)}>Add your first widget</Button></div>}
    </div>
    <Activity mode={active ? "visible" : "hidden"}>
    {app === "terminal" && <KillSwitchPill />}
    <Dialog open={picker} onOpenChange={setPicker}><DialogContent className="max-h-[80dvh] overflow-y-auto"><DialogTitle>{meta.name} widgets</DialogTitle>
      <Input aria-label="Search widgets" value={search} onChange={e => setSearch(e.target.value)} />
      <p className="text-xs text-text-muted">Tools for this app. Availability still depends on source, account and qualification.</p>
      <div className="grid gap-2">{widgetsForApp(app).filter(w => `${w.name} ${w.description}`.toLowerCase().includes(search.toLowerCase())).map(w => <Button key={w.id} variant="outline" className="h-auto justify-start whitespace-normal p-3 text-left" aria-label={`Add ${w.name}`} onClick={() => add({ widgetId: w.id })}><span><strong className="block text-sm">{w.name}</strong><span className="text-xs text-text-muted">{w.description}</span></span></Button>)}</div>
      <Button variant="ghost" onClick={() => setPicker(false)} aria-label="Close widget catalogue">Close</Button>
    </DialogContent></Dialog>
    </Activity>
  </section>;
}
