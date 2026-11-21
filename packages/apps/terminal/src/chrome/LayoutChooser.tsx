import { Plus } from "lucide-react";
import { APP_PRESETS, buildAppPreset } from "@/layout/appLayouts";
import type { AppId } from "@/layout/appCatalog";
import { Button } from "@/components/ui/button";

type PreviewNode = { type: string; name?: string; weight?: number; children?: PreviewNode[] };
function PanelPreview({ node, vertical = false }: { node: PreviewNode; vertical?: boolean }) {
  if (node.type === "tabset") return <div className="ft-template-pane" style={{ flex: node.weight ?? 100 }}>{node.children?.map((tab, index) => <span key={index}>{tab.name}</span>)}</div>;
  return <div className="ft-template-row" style={{ flex: node.weight ?? 100, flexDirection: vertical ? "column" : "row" }}>{node.children?.map((child, index) => <PanelPreview key={index} node={child} vertical={!vertical} />)}</div>;
}

/** Layout illustrations come from the canonical composition, never a second
 * template catalogue or fabricated market screenshot. Selection is owned by
 * the retained app route, exactly like its preset and saved-layout controls. */
export function LayoutChooser({ app, canReturn, onChoose, onCustom, onReturn }: {
  app: AppId; canReturn: boolean; onChoose: (id: string) => void; onCustom: () => void; onReturn: () => void;
}) {
  return <section className="ft-layout-chooser" aria-label="Choose a layout">
    <div className="ft-layout-chooser-heading"><h2>Select a layout to get started</h2><p>Presentation templates · account and execution authority stay unchanged.</p></div>
    <div className="ft-template-grid">
      <button type="button" className="ft-template-choice" onClick={onCustom} aria-label="Create new layout"><div className="ft-template-preview ft-template-empty"><Plus aria-hidden="true" /></div><span>Create new layout</span></button>
      {APP_PRESETS[app].filter(preset => app !== "terminal" || preset.template).map(preset => <button type="button" key={preset.id} className="ft-template-choice" onClick={() => onChoose(preset.id)} aria-label={`Use ${preset.name} layout`}><div className="ft-template-preview" aria-hidden="true"><PanelPreview node={buildAppPreset(app, preset.id).layout as PreviewNode} /></div><span>{preset.name}</span></button>)}
    </div>
    {app === "terminal" && <details className="ft-extra-templates"><summary>More FlintTrade layouts</summary><div className="flex flex-wrap justify-center gap-2 py-3">{APP_PRESETS[app].filter(preset => !preset.template).map(preset => <Button key={preset.id} variant="outline" onClick={() => onChoose(preset.id)}>{preset.name}</Button>)}</div></details>}
    <p className="ft-template-caption">Panel previews show the actual template composition, not market data.</p>
    {canReturn && <Button variant="ghost" onClick={onReturn}>Return to workspace</Button>}
  </section>;
}
