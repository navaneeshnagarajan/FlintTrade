import { Activity, useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { ChevronDown, Download, LayoutGrid, Plus, RotateCcw, Search, Upload, X } from "lucide-react";
import { useLocation, useNavigate } from "react-router";
import { Actions, Layout, Model, type TabNode, type IJsonModel } from "flexlayout-react";
import "flexlayout-react/style/combined.css";
import { APPS, APP_WIDGETS, widgetAllowed, widgetsForApp, type AppId } from "@/layout/appCatalog";
import { APP_PRESETS, buildAppPreset, readAppLayouts, saveAppLayout, validateAppLayout } from "@/layout/appLayouts";
import { appWidgetFactory } from "@/layout/appWidgetFactory";
import { createWorkspaceApi, renderWorkspaceTabExtras, renderWorkspaceTabSetExtras } from "@/layout/flexLayoutAdapter";
import { useThemeStore } from "@/stores/themeStore";
import { useModeStore } from "@/stores/modeStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useCanonicalScopeKey } from "@/services/canonicalData";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { NativeSelect } from "@/components/ui/native-select";
import { EmptyState } from "@/components/ui/states";
import { cn } from "@/lib/utils";
import { executionScopeLine } from "@/lib/executionScopeLine";
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
  const [layoutOpen, setLayoutOpen] = useState(false);
  const [linksOpen, setLinksOpen] = useState(false);
  // An open toolbar panel borrows height from the desk. That must not flip a
  // wide desk into the one-panel compact view, so only width decides then.
  const toolbarPanelOpen = useRef(false);
  toolbarPanelOpen.current = layoutOpen || linksOpen;
  const layoutPanelId = useId();
  const importInput = useRef<HTMLInputElement>(null);
  const [revision, setRevision] = useState(0);
  const host = useRef<HTMLDivElement>(null);
  // Search + Enter closes the catalogue. Focus must not return to "+ Widget"
  // while that Enter is still down, or the trigger opens the dialog again.
  const closeFromSearchRef = useRef(false);

  const persist = useCallback((current: Model) => {
    try { saveAppLayout(app, "Current", wideJson(current)); setError(""); }
    catch (problem) { setError(String(problem)); }
  }, [app]);
  useEffect(() => {
    if (!active) setPicker(false);
  }, [active]);
  useEffect(() => {
    if (!active) return;
    // Replacing/restoring a model is itself a presentation change. The old
    // effect's cleanup flushes its model; publish the replacement afterwards
    // even when the user performs no subsequent docking action before reload.
    persist(model);
    const listener = () => { persist(model); setRevision(v => v + 1); };
    model.addChangeListener(listener);
    return () => { model.removeChangeListener(listener); persist(model); };
  }, [active, model, persist]);
  useEffect(() => {
    if (!active || !host.current) return;
    const observer = new ResizeObserver(([entry]) => setCompact(entry.contentRect.width < 760 || (entry.contentRect.height < 330 && !toolbarPanelOpen.current)));
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
    setPicker(false);
    const current = modelRef.current;
    const api = createWorkspaceApi(() => current, setModel);
    const meta = APP_WIDGETS.find(w => w.id === id)!;
    if (id === "orderpad" && api.retargetOrderPad(request.props ?? {}, request.title)) return;
    // Protect configuration/security and complete route forms from duplicate owners.
    const existing = panels(current).find(tab => tab.getComponent() === id);
    if (existing && ["preferences", "research", "investments", "learning", "run-control", "broker-roles", "ai-centre"].includes(id)) {
      current.doAction(Actions.selectTab(existing.getId()));
      return;
    }
    api.addPanel({ id: `${app}:${id}:${crypto.randomUUID()}`, component: id, title: request.title ?? meta.name, params: { channel: "none", ...request.props } });
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
  const catalogue = widgetsForApp(app).filter((widget) =>
    `${widget.name} ${widget.description}`.toLowerCase().includes(search.trim().toLowerCase()),
  );
  function addFromSearch(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter" || search.trim().length === 0 || catalogue.length === 0) return;
    event.preventDefault();
    event.stopPropagation();
    closeFromSearchRef.current = true;
    add({ widgetId: catalogue[0].id });
  }
  function keepFocusOffTrigger(event: Event) {
    if (!closeFromSearchRef.current) return;
    closeFromSearchRef.current = false;
    event.preventDefault();
  }
  const scope = executionScopeLine({ app, mode, account });
  const selectedPanel = model.getActiveTabset()?.getSelectedNode()?.getId() ?? tabs[0]?.getId() ?? "";
  function saveNamedLayout() {
    try {
      saveAppLayout(app, layoutName, wideJson(model));
      setSavedNames(Object.keys(readAppLayouts(app)).filter(n => n !== "Current"));
      setNotice(`Saved ${layoutName}`);
    } catch (e) { setError(String(e)); }
  }
  function restoreNamedLayout(name: string) {
    try {
      const saved = readAppLayouts(app)[name];
      if (validateAppLayout(app, saved)) { setModel(Model.fromJson(saved)); setNotice(`Restored ${name}`); }
    } catch (e) { setError(String(e)); }
  }
  return <section className="flex h-full min-h-0 flex-col" aria-label={`${meta.name} app`} data-testid="unified-app">
    <Activity mode={active ? "visible" : "hidden"}>
    <div className="flex h-9 shrink-0 items-center gap-2 border-b border-white/10 bg-[#071018] px-2 text-[#e8eef2]" data-testid="app-toolbar">
      <h1 className={cn("shrink-0 font-heading text-sm font-semibold text-[#7dffa1]", compact && "sr-only")}>{meta.name}</h1>
      {compact && <NativeSelect aria-label="Compact panel" controlSize="sm" wrapperClassName="min-w-0 flex-1" onChange={e => selectPanel(e.target.value)} value={selectedPanel}>{tabs.map(tab => <option key={tab.getId()} value={tab.getId()}>{tab.getName()}</option>)}</NativeSelect>}
      <p className="shrink-0 text-[11px] font-medium tracking-wide text-[#9fb0bc]" data-testid="desk-total-pnl">TOTAL P&amp;L <span className="text-[#e8eef2]">—</span></p>
      <p className={cn("min-w-0 truncate text-xs text-[#9fb0bc]", compact ? "order-last basis-full" : "flex-1")} title={scope} data-testid="app-execution-scope">
        {scope}
      </p>
      <Button variant="outline" size="sm" className="shrink-0" onClick={() => setPicker(true)} aria-label="Add widget"><Plus aria-hidden="true" /><span className={cn(compact && "sr-only")}>Widget</span></Button>
      <div className="contents">
        <Button variant="ghost" size="sm" className="shrink-0" aria-expanded={layoutOpen} aria-controls={layoutPanelId} aria-label="Layout" onClick={() => setLayoutOpen(open => !open)}>
          <LayoutGrid aria-hidden="true" /><span className={cn(compact && "sr-only")}>Layout</span><ChevronDown aria-hidden="true" className={cn("transition-transform", layoutOpen && "rotate-180")} />
        </Button>
        <div id={layoutPanelId} role="group" aria-label={`${meta.name} layout`} hidden={!layoutOpen} className="order-last flex basis-full flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-border-default bg-surface-card px-3 py-2">
          <label className="flex min-w-0 items-center gap-1.5 text-xs text-text-secondary">Preset
            <NativeSelect controlSize="sm" aria-label={`${meta.name} preset`} defaultValue="" onChange={e => { if (e.target.value) setModel(Model.fromJson(buildAppPreset(app, e.target.value))); }}><option value="" disabled>Choose layout</option>{APP_PRESETS[app].map(p => <option value={p.id} key={p.id}>{p.name}</option>)}</NativeSelect>
          </label>
          <span className="flex min-w-0 items-center gap-1.5">
            <Input aria-label="Layout name" value={layoutName} onChange={e => setLayoutName(e.target.value)} placeholder="Name this layout" className="h-8 w-40 min-w-0 text-xs md:text-xs" />
            <Button variant="outline" size="sm" onClick={saveNamedLayout}>Save layout</Button>
          </span>
          <NativeSelect controlSize="sm" aria-label="Restore saved layout" value="" onChange={e => restoreNamedLayout(e.target.value)}><option value="">Restore layout</option>{savedNames.map(n => <option key={n}>{n}</option>)}</NativeSelect>
          <span className="flex flex-wrap items-center gap-1">
            <Button size="sm" variant="ghost" onClick={exportLayout}><Download aria-hidden="true" />Export layout</Button>
            <Button size="sm" variant="ghost" onClick={() => importInput.current?.click()}><Upload aria-hidden="true" />Import layout</Button>
            <input ref={importInput} aria-label="Import app layout" type="file" accept="application/json,.json" className="sr-only" tabIndex={-1} onChange={event => { void importLayout(event.target.files?.[0]); event.target.value = ""; }} />
            <Button size="sm" variant="ghost" onClick={() => setModel(Model.fromJson(buildAppPreset(app, "default")))}><RotateCcw aria-hidden="true" />Reset app layout</Button>
          </span>
          <p className="basis-full text-xs text-text-muted">Presentation only. Saved named layouts and all non-layout records are retained.</p>
        </div>
      </div>
      <InstrumentLinks app={app} compact={compact} onOpenChange={setLinksOpen} />
    </div>
    {app === "terminal" && <PracticeLaterSetup />}
    {error && <p role="alert" className="flex shrink-0 items-start gap-2 border-b border-warning/30 bg-warning/[0.08] px-3 py-1.5 text-xs text-[var(--color-warning-text,var(--color-warning))]"><span className="min-w-0 flex-1 break-words">{error}</span><Button variant="ghost" size="icon-xs" aria-label="Dismiss message" onClick={() => setError("")}><X aria-hidden="true" /></Button></p>}
    {notice && <p role="status" className="flex shrink-0 items-center gap-2 border-b border-border-default bg-surface-card px-3 py-1 text-xs text-text-secondary"><span className="min-w-0 flex-1 truncate">{notice}</span><Button variant="ghost" size="icon-xs" aria-label="Dismiss notice" onClick={() => setNotice("")}><X aria-hidden="true" /></Button></p>}
    </Activity>
    <div ref={host} className={`relative min-h-0 flex-1 overflow-hidden flexlayout__theme_${theme === "light" ? "light" : "dark"}`} data-testid="app-layout">
      <Layout model={model} factory={factory} onRenderTab={renderWorkspaceTabExtras} onRenderTabSet={renderWorkspaceTabSetExtras} realtimeResize />
      {!tabs.length && <div className="absolute inset-0 grid place-items-center bg-surface-base"><EmptyState icon={LayoutGrid} title={`${meta.name} has no panels`} description="Add a widget, or choose a preset from Layout, to fill this page." action={<Button onClick={() => setPicker(true)}>Add your first widget</Button>} /></div>}
    </div>
    <Activity mode={active ? "visible" : "hidden"}>
    {app === "terminal" && <KillSwitchPill />}
    </Activity>
    {active && picker ? <Dialog open onOpenChange={next => { if (!next) setPicker(false); }}><DialogContent className="flex max-h-[80dvh] flex-col gap-3 sm:max-w-2xl" onCloseAutoFocus={keepFocusOffTrigger}><DialogTitle>{meta.name} widgets</DialogTitle>
      <div className="relative shrink-0">
        <Search aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-text-muted" />
        <Input aria-label="Search widgets" placeholder="Search widgets" className="pl-9" value={search} onChange={e => setSearch(e.target.value)} onKeyDown={addFromSearch} />
      </div>
      <p className="shrink-0 text-xs text-text-muted">Tools for this app. Availability still depends on source, account and qualification.</p>
      <div className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1">
        {catalogue.length ? <div className="grid gap-2 sm:grid-cols-2">{catalogue.map(w => <Button key={w.id} type="button" variant="outline" className="h-auto items-start justify-start whitespace-normal p-3 text-left" aria-label={`Add ${w.name}`} onClick={() => add({ widgetId: w.id })}><span className="min-w-0"><strong className="block text-sm font-medium text-text-primary">{w.name}</strong><span className="text-xs font-normal text-text-secondary">{w.description}</span></span></Button>)}</div>
          : <EmptyState size="sm" icon={Search} title="No widgets match" description="Try a shorter search, or clear it to see every widget for this app." />}
      </div>
      <Button type="button" variant="ghost" className="shrink-0 self-end" onClick={() => setPicker(false)} aria-label="Close widget catalogue">Close</Button>
    </DialogContent></Dialog> : null}
  </section>;
}
