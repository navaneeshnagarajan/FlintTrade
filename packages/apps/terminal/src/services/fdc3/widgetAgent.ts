import type { AppIdentifier, Channel, Context, ContextHandler, ContextMetadata, DesktopAgent, Listener } from "@finos/fdc3";
import { channelInstrumentAtoms, getChannelContext, isUserChannelId, USER_CHANNELS, type JotaiStore, type UserChannelId } from "./channels";
import { instrumentFromContext } from "./contexts";
import type { WsInstrument } from "@/types/api";

/** A tested in-process subset of FINOS FDC3 2.2.3, NOT an externally
 * discoverable full DesktopAgent. All channels share the existing data atoms. */
export type WidgetAgent = Pick<DesktopAgent, "getUserChannels" | "getCurrentChannel" | "joinUserChannel" | "leaveCurrentChannel" | "broadcast" | "addContextListener" | "raiseIntent"> & { dispose(): void };
export interface PreparedWorkflow { widgetId: string; props: Record<string, unknown>; title?: string }
const origins = new WeakMap<JotaiStore, Map<UserChannelId, { instrument: WsInstrument; source: AppIdentifier }>>();
export function createWidgetAgent(store: JotaiStore, identity: AppIdentifier, open: (workflow: PreparedWorkflow) => void = workflow => {
  window.dispatchEvent(new CustomEvent("flinttrade:addWidget", { detail: workflow }));
}): WidgetAgent {
  if (!identity.instanceId) throw new Error("Instance identity is required");
  let disposed = false;
  let current: UserChannelId | null = null;
  const subscriptions = new Set<() => void>();
  const listeners = new Set<{ type: string | null; handler: ContextHandler; stop?: () => void }>();
  const source = Object.freeze({ ...identity });
  function assertOpen() { if (disposed) throw new Error("AccessDenied"); }
  function metadata(id: UserChannelId): ContextMetadata | undefined {
    const entry = origins.get(store)?.get(id);
    return entry?.instrument === store.get(channelInstrumentAtoms[id]) ? { source: entry.source } : undefined;
  }
  function subscribe(id: UserChannelId, type: string | null, handler: ContextHandler): () => void {
    const stop = store.sub(channelInstrumentAtoms[id], () => {
      const context = getChannelContext(store, id);
      const meta = metadata(id);
      if (meta?.source?.appId === source.appId && meta.source.instanceId === source.instanceId) return;
      if (context && (!type || context.type === type)) handler(context, meta);
    });
    const unsubscribe = () => { stop(); subscriptions.delete(unsubscribe); };
    subscriptions.add(unsubscribe);
    return unsubscribe;
  }
  async function publish(id: UserChannelId, context: Context) {
    assertOpen();
    const instrument = instrumentFromContext(context);
    if (!instrument) throw new Error("MalformedContext");
    const previous = store.get(channelInstrumentAtoms[id]);
    // Context transformations by followers must not create an origin ping-pong.
    if (previous?.symbol === instrument.symbol && previous.exchange === instrument.exchange) return;
    let map = origins.get(store);
    if (!map) { map = new Map(); origins.set(store, map); }
    map.set(id, { instrument, source });
    store.set(channelInstrumentAtoms[id], instrument);
  }
  function channel(id: UserChannelId): Channel {
    const meta = USER_CHANNELS.find(c => c.id === id)!;
    async function addContextListener(type: string | null | ContextHandler, callback?: ContextHandler): Promise<Listener> {
      assertOpen();
      const handler = typeof type === "function" ? type : callback;
      if (!handler) throw new Error("MalformedContext");
      const stop = subscribe(id, typeof type === "function" ? null : type, handler);
      return { unsubscribe: async () => stop() };
    }
    return {
      id, type: "user", displayMetadata: { name: meta.label, color: meta.colour },
      broadcast: context => publish(id, context),
      getCurrentContext: async type => { assertOpen(); const ctx = getChannelContext(store, id); return !type || ctx?.type === type ? ctx : null; },
      addContextListener,
    };
  }
  function attach(entry: { type: string | null; handler: ContextHandler; stop?: () => void }) {
    entry.stop?.(); entry.stop = undefined;
    if (!current) return;
    entry.stop = subscribe(current, entry.type, entry.handler);
    const context = getChannelContext(store, current);
    if (context && (!entry.type || entry.type === context.type)) entry.handler(context, metadata(current));
  }
  async function addContextListener(type: string | null | ContextHandler, callback?: ContextHandler): Promise<Listener> {
    assertOpen();
    const handler = typeof type === "function" ? type : callback;
    if (!handler) throw new Error("MalformedContext");
    const entry = { type: typeof type === "function" ? null : type, handler, stop: undefined as (() => void) | undefined };
    listeners.add(entry); attach(entry);
    return { async unsubscribe() { entry.stop?.(); listeners.delete(entry); } };
  }
  return {
    getUserChannels: async () => { assertOpen(); return USER_CHANNELS.map(c => channel(c.id)); },
    getCurrentChannel: async () => current ? channel(current) : null,
    joinUserChannel: async id => { assertOpen(); if (!isUserChannelId(id)) throw new Error("NoChannelFound"); current = id; listeners.forEach(attach); },
    leaveCurrentChannel: async () => { current = null; listeners.forEach(attach); },
    broadcast: async context => { assertOpen(); if (current) await publish(current, context); },
    addContextListener,
    raiseIntent: async (intent, context, target) => {
      assertOpen();
      const instrument = instrumentFromContext(context);
      if (!instrument) throw new Error("NoAppsFound");
      const app = typeof target === "string" ? target : target?.appId;
      if (app && app !== "flinttrade.terminal") throw new Error("TargetAppUnavailable");
      if (typeof target === "object" && target.instanceId && target.instanceId !== "main") throw new Error("TargetInstanceUnavailable");
      if (intent === "CreateOrder" && source.appId === "flinttrade.testing" && !app) throw new Error("Explicit Terminal target required");
      const widgetId = intent === "CreateOrder" ? "orderpad" : ["ViewChart", "ViewInstrument"].includes(intent) ? "chart" : null;
      if (!widgetId) throw new Error("NoAppsFound");
      open({ widgetId, props: { symbol: instrument.symbol, exchange: instrument.exchange } });
      return { source: { appId: "flinttrade.terminal", instanceId: "main" }, intent, getResult: async () => ({ type: "flinttrade.workflow", status: "prepared", widgetId }) };
    },
    dispose() { subscriptions.forEach(stop => stop()); listeners.clear(); current = null; disposed = true; },
  };
}
