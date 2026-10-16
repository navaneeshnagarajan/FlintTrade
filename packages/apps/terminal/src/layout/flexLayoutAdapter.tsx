/**
 * flexLayoutAdapter.tsx
 *
 * The single chrome-side boundary between FlintTrade and flexlayout-react.
 * Widgets receive the FlintTrade-owned `WidgetProps` contract
 * (`types/widgets.ts`) and never import the docking library; everything
 * that must know about FlexLayout — JSON builders for presets, the
 * workspace API handle stored in `layoutStore`, and the TabNode → props
 * bridge used by the widget factory — lives here.
 *
 * Known FlexLayout traps this module is shaped around (from the
 * layout-fluidness assessment, now .local/specs/finos-migration/):
 *  - Model recreation remounts every tab (#456/#524): the Model instance is
 *    owned by TerminalRoute state and only replaced on explicit loads
 *    (preset apply, clear, saved-layout restore) — never derived in render.
 *  - Weights-based serialisation: presets set explicit weights everywhere.
 */
import { Actions, DockLocation, Model } from "flexlayout-react";
import type {
  IJsonModel,
  IJsonRowNode,
  IJsonTabNode,
  IJsonTabSetNode,
  ITabRenderValues,
  ITabSetRenderValues,
  TabSetNode,
  BorderNode,
  TabNode,
} from "flexlayout-react";
import { useStore } from "jotai";
import { useLayoutEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import type { WidgetPanelApi, WidgetProps } from "@/types/widgets";
import {
  getChannelMembership,
  setChannelMembership,
  USER_CHANNELS,
  type UserChannelId,
} from "@/services/fdc3/channels";
import { useChannelMembership } from "@/services/fdc3/hooks";

// ---------------------------------------------------------------------------
// Model defaults
// ---------------------------------------------------------------------------

/**
 * Global model attributes applied to every workspace model.
 *  - `tabEnableRename: false` — panel titles are owned by the widget
 *    catalogue, not free-typed (Dockview had no rename either).
 *  - `tabSetEnableSingleTabStretch: true` — replaces Dockview's
 *    `singleTabMode="fullwidth"`.
 */
export const WORKSPACE_GLOBAL_ATTRIBUTES: IJsonModel["global"] = {
  tabEnableRename: false,
  tabSetEnableSingleTabStretch: true,
  // Splitter thickness is a CSS variable (--splitter-size) in FlexLayout
  // 0.10 — declared in terminal.css on the specificity-boosted
  // .flexlayout__layout override block, not a model attribute.
  tabSetMinWidth: 100,
  tabSetMinHeight: 80,
};

// ---------------------------------------------------------------------------
// JSON builders (used by workspacePresets and tests)
// ---------------------------------------------------------------------------

let tabSeq = 0;

/** Unique-per-call tab id, stable enough for persistence within a layout. */
export function panelId(base: string): string {
  tabSeq += 1;
  return `${base}-${Date.now().toString(36)}-${tabSeq}`;
}

export interface TabJsonOptions {
  id?: string;
  /** Panel params persisted with the layout (pinned symbol, view, …). */
  params?: Record<string, unknown>;
}

/** A single widget tab. `component` must resolve in `widgetComponents`. */
export function tabJson(component: string, name: string, options?: TabJsonOptions): IJsonTabNode {
  return {
    type: "tab",
    id: options?.id ?? panelId(component),
    component,
    name,
    ...(options?.params !== undefined ? { config: options.params } : {}),
  };
}

/** A tabset (group of stacked tabs) with an explicit layout weight. */
export function tabsetJson(weight: number, children: IJsonTabNode[]): IJsonTabSetNode {
  return { type: "tabset", weight, children };
}

/**
 * A row with an explicit weight. Orientation alternates by nesting depth:
 * the root row lays children out horizontally, a row inside it vertically,
 * and so on — same convention as FlexLayout itself.
 */
export function rowJson(weight: number, children: Array<IJsonRowNode | IJsonTabSetNode>): IJsonRowNode {
  return { type: "row", weight, children };
}

/** A complete workspace model document around a root row. */
export function workspaceJson(root: IJsonRowNode): IJsonModel {
  return {
    global: { ...WORKSPACE_GLOBAL_ATTRIBUTES },
    borders: [],
    layout: root,
  };
}

/** The empty workspace: one empty tabset so `addPanel` always has a target. */
export function emptyWorkspaceJson(): IJsonModel {
  return workspaceJson(rowJson(100, [tabsetJson(100, [])]));
}

/** Build a Model, falling back to the empty workspace on corrupt input. */
export function createWorkspaceModel(json?: IJsonModel): Model {
  if (json) {
    try {
      return Model.fromJson(json);
    } catch {
      // Corrupted saved layout — the caller decides whether to apply a
      // preset instead; an empty model keeps the canvas usable meanwhile.
      return Model.fromJson(emptyWorkspaceJson());
    }
  }
  return Model.fromJson(emptyWorkspaceJson());
}

/**
 * Build a Model from a persisted document, or null when the document does
 * not parse — so restore paths can fall back to a DEFAULT PRESET rather
 * than the empty canvas `createWorkspaceModel` degrades to.
 */
export function tryCreateWorkspaceModel(layout: Record<string, unknown>): Model | null {
  try {
    return Model.fromJson(layout as unknown as IJsonModel);
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Model queries
// ---------------------------------------------------------------------------

/** Number of widget tabs currently in the model. */
export function countTabs(model: Model): number {
  let count = 0;
  model.visitNodes((node) => {
    if (node.getType() === "tab") count += 1;
  });
  return count;
}

/** The tabset new panels should land in: active if set, else the first. */
function targetTabsetId(model: Model): string | undefined {
  return (model.getActiveTabset() ?? model.getFirstTabSet())?.getId();
}

// ---------------------------------------------------------------------------
// TabNode → WidgetProps bridge (used by widgetFactory)
// ---------------------------------------------------------------------------

// Panel api identity must be stable across renders: widgets put `props.api`
// in hook dependency arrays, and the factory runs on every Layout render.
const panelApiCache = new WeakMap<TabNode, WidgetPanelApi>();

export function widgetPropsForNode(node: TabNode): WidgetProps {
  let api = panelApiCache.get(node);
  if (!api) {
    api = {
      id: node.getId(),
      updateParameters: (params: Record<string, unknown>) => {
        const current = (node.getConfig() as Record<string, unknown> | undefined) ?? {};
        node.getModel().doAction(
          Actions.updateNodeAttributes(node.getId(), { config: { ...current, ...params } }),
        );
      },
    };
    panelApiCache.set(node, api);
  }
  return {
    params: (node.getConfig() as Record<string, unknown> | undefined) ?? undefined,
    api,
  };
}

/**
 * Props for a widget rendered OUTSIDE the workspace canvas (the compact
 * mobile workspace, tests): a real id and a no-op `updateParameters`, so
 * widgets that persist view state simply don't persist it there.
 */
export function detachedPanelProps(id: string, params?: Record<string, unknown>): WidgetProps {
  return {
    ...(params !== undefined ? { params } : {}),
    api: { id, updateParameters: () => {} },
  };
}

// ---------------------------------------------------------------------------
// WorkspaceApi — the handle stored in layoutStore
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Tab chrome — FDC3 channel dot
// ---------------------------------------------------------------------------

/** Click cycle: red → green → blue → yellow → unlinked → red. */
const CHANNEL_CYCLE: ReadonlyArray<UserChannelId | null> = [
  ...USER_CHANNELS.map((c) => c.id),
  null,
];

const channelSlots = new WeakMap<TabNode, HTMLSpanElement>();

function WorkspaceChannelDot({ node }: { node: TabNode }) {
  const store = useStore();
  const clipRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const measureRef = useRef<() => void>(() => {});

  // The public sibling toolbar does not inherit the tab strip's scroll/clip.
  // Mirror that real viewport in an owned overflow container, not a hidden
  // action or a portal into the library's DOM. Only our own boxes are written.
  useLayoutEffect(() => {
    const slot = channelSlots.get(node);
    const strip = slot?.closest<HTMLElement>('.flexlayout__tabset_tabbar_inner');
    const clip = clipRef.current;
    const button = buttonRef.current;
    if (!slot || !strip || !clip || !button) return;
    const measure = () => {
      const bounds = strip.getBoundingClientRect();
      const target = slot.getBoundingClientRect();
      Object.assign(clip.style, { left: `${bounds.left}px`, top: `${bounds.top}px`, width: `${bounds.width}px`, height: `${bounds.height}px` });
      Object.assign(button.style, { left: `${target.left - bounds.left}px`, top: `${target.top - bounds.top}px` });
    };
    measureRef.current = measure;
    const observer = new ResizeObserver(measure);
    // Splitters may move a strip without resizing its own rectangle.
    for (let parent: HTMLElement | null = slot; parent; parent = parent.parentElement) observer.observe(parent);
    strip.ownerDocument.addEventListener('scroll', measure, true);
    measure();
    return () => {
      observer.disconnect();
      strip.ownerDocument.removeEventListener('scroll', measure, true);
      measureRef.current = () => {};
    };
  });
  const renderConfig = (node.getConfig() as Record<string, unknown> | undefined) ?? undefined;
  // Live membership — the widget follows the SAME atom, so a change here
  // reaches it instantly even in a hidden tab FlexLayout will not
  // re-render until revealed (Phase 2 audit finding).
  const channelId = useChannelMembership(node.getId(), renderConfig);
  // A panel pinned to an explicit instrument ignores channels entirely —
  // show that honestly rather than asserting a membership it never follows.
  const isPinned = Boolean(renderConfig?.symbol || renderConfig?.optionLeg);
  const meta = channelId ? USER_CHANNELS.find((c) => c.id === channelId) : undefined;
  const label = isPinned
    ? "Pinned to its own instrument — ignores link channels"
    : meta
    ? `Link channel: ${meta.label} — click to change`
    : "Link channel: none — click to change";

  const cycleChannel = () => {
    // Read the config FRESH at interaction time — the render-time snapshot
    // can be stale between tab-strip renders (the stale-spread class of
    // defect the Phase 1 audit established).
    const freshParams = (node.getConfig() as Record<string, unknown> | undefined) ?? undefined;
    const current = getChannelMembership(store, node.getId(), freshParams);
    const next = CHANNEL_CYCLE[(CHANNEL_CYCLE.indexOf(current) + 1) % CHANNEL_CYCLE.length];
    // Live state first (reaches the widget immediately)…
    setChannelMembership(store, node.getId(), next);
    // …then persist for save/restore, merging over the fresh config.
    node.getModel().doAction(
      Actions.updateNodeAttributes(node.getId(), {
        config: { ...(freshParams ?? {}), channel: next ?? "none" },
      }),
    );
  };

  return (
    <div ref={clipRef} style={{ position: "fixed", overflow: "clip", pointerEvents: "none" }}>
    <Button
      ref={buttonRef}
      key="fdc3-channel"
      type="button"
      variant="ghost"
      size="icon"
      className="h-4 w-4 shrink-0 rounded-full p-0 hover:bg-transparent"
      aria-label={label}
      title={label}
      style={{ position: "absolute", pointerEvents: "auto" }}
      onFocus={() => {
        // Reveal the original strip slot, without selecting its desk or
        // changing channel ownership. Native focus remains on this button.
        channelSlots.get(node)?.scrollIntoView({ block: "nearest", inline: "center", behavior: "instant" });
        measureRef.current();
      }}
      onPointerDown={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
      onDragStart={(e) => { e.preventDefault(); e.stopPropagation(); }}
      onContextMenu={(e) => {
        e.stopPropagation();
        // Preserve the library's per-tab callback, including native fallback.
        const allowed = channelSlots.get(node)?.closest('[role="tab"]')?.dispatchEvent(new MouseEvent("contextmenu", {
          bubbles: true, cancelable: true, clientX: e.clientX, clientY: e.clientY,
        }));
        if (allowed === false) e.preventDefault();
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") e.stopPropagation();
      }}
      onClick={(e) => {
        e.stopPropagation();
        cycleChannel();
      }}
    >
      <span
        aria-hidden="true"
        className={
          meta
            ? isPinned
              ? "h-2 w-2 rounded-full opacity-30"
              : "h-2 w-2 rounded-full"
            : "h-2 w-2 rounded-full border border-text-muted"
        }
        style={meta ? { backgroundColor: meta.colour } : undefined}
      />
    </Button>
    </div>
  );
}

/**
 * The `onRenderTab` handler for the workspace host: appends the FDC3
 * channel dot to every tab's chrome. Membership flows through the live
 * atoms in services/fdc3 — no host redraw is needed.
 */
export function renderWorkspaceTabExtras(node: TabNode, renderValues: ITabRenderValues): void {
  renderValues.buttons.push(<span key="fdc3-channel-slot" aria-hidden="true" className="inline-flex h-4 w-4 shrink-0"
    ref={(element) => { if (element) channelSlots.set(node, element); else channelSlots.delete(node); }} />);
}

/** Keep every per-tab action in the library's public sibling toolbar slot. */
export function renderWorkspaceTabSetExtras(node: TabSetNode | BorderNode, renderValues: ITabSetRenderValues): void {
  for (const tab of node.getTabNodes()) {
    renderValues.buttons.push(<WorkspaceChannelDot key={`fdc3-channel-${tab.getId()}`} node={tab} />);
  }
}

export interface AddPanelOptions {
  id?: string;
  component: string;
  title: string;
  params?: Record<string, unknown>;
}

/**
 * The workspace handle chrome consumers use (WidgetPicker, AppLayout's
 * layout export, applyPreset, the `flinttrade:addWidget` listener).
 * Deliberately minimal — only verbs with a live consumer; grow it when a
 * consumer arrives, not before.
 */
export interface WorkspaceApi {
  addPanel(options: AddPanelOptions): void;
  /**
   * Point the existing Order Pad at a new instrument. Returns false when
   * the desk has no Order Pad yet, so the caller can add the first one.
   */
  retargetOrderPad(params: Record<string, unknown>, title?: string): boolean;
  panelCount(): number;
  toJSON(): Record<string, unknown>;
  /** Replace the whole model with a preset document. */
  loadModelJson(json: IJsonModel): void;
}

/**
 * Implementation over the model owned by TerminalRoute. The route hands in
 * closures so the api always operates on the CURRENT model instance —
 * loads replace the model, they never mutate through a stale reference.
 */
export function createWorkspaceApi(
  getModel: () => Model,
  loadModel: (model: Model) => void,
): WorkspaceApi {
  return {
    addPanel: ({ id, component, title, params }) => {
      const model = getModel();
      const tab = tabJson(component, title, { id, params });
      const target = targetTabsetId(model);
      if (target !== undefined) {
        model.doAction(Actions.addNode(tab, target, DockLocation.CENTER, -1, true));
      } else {
        // Degenerate model with no tabset at all — rebuild around the tab.
        loadModel(createWorkspaceModel(workspaceJson(rowJson(100, [tabsetJson(100, [tab])]))));
      }
    },
    retargetOrderPad: (params, title) => {
      const model = getModel();
      let tabId: string | undefined;
      model.visitNodes((node) => {
        if (tabId || node.getType() !== "tab") return;
        const tab = node as TabNode;
        if (tab.getComponent() === "orderpad") tabId = tab.getId();
      });
      if (!tabId) return false;
      const node = model.getNodeById(tabId) as TabNode | undefined;
      const current = (node?.getConfig() as Record<string, unknown> | undefined) ?? {};
      model.doAction(Actions.updateNodeAttributes(tabId, {
        config: { ...current, ...params },
        ...(title ? { name: title } : {}),
      }));
      model.doAction(Actions.selectTab(tabId));
      // FlexLayout memoises tab content and skips a redraw when the tab node
      // object is unchanged, so the pad would keep the previous symbol.
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("flinttrade:orderPadPrefill", {
          detail: { tabId, params, nonce: crypto.randomUUID() },
        }));
      }
      return true;
    },
    panelCount: () => countTabs(getModel()),
    toJSON: () => getModel().toJson() as unknown as Record<string, unknown>,
    loadModelJson: (json) => loadModel(createWorkspaceModel(json)),
  };
}
