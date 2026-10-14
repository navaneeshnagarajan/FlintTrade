import { useEffect, useMemo, useState } from "react";
import { useStore } from "jotai";
import { createWidgetAgent } from "@/services/fdc3/widgetAgent";
import { instrumentContext, instrumentFromContext } from "@/services/fdc3/contexts";
import { USER_CHANNELS } from "@/services/fdc3/channels";
import type { AppId } from "@/layout/appCatalog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** Selection bus only. Never reads or writes account/mode/grant stores. */
export function InstrumentLinks({ app }: { app: AppId }) {
  const store = useStore();
  const [channel, setChannel] = useState("none");
  const [symbol, setSymbol] = useState("");
  const [exchange, setExchange] = useState("");
  const [message, setMessage] = useState("Unlinked");
  const agent = useMemo(() => createWidgetAgent(store, { appId: `flinttrade.${app}`, instanceId: `${app}:selection` }), [app, store]);
  useEffect(() => {
    let active = true;
    const listener = agent.addContextListener("fdc3.instrument", context => {
      if (!active) return;
      const instrument = instrumentFromContext(context);
      if (instrument) { setSymbol(instrument.symbol); setExchange(instrument.exchange); setMessage("Linked selection received; execution unchanged"); }
    });
    return () => { active = false; void listener.then(handle => handle.unsubscribe()); void agent.leaveCurrentChannel(); };
  }, [agent]);
  useEffect(() => {
    const change = channel === "none" ? agent.leaveCurrentChannel() : agent.joinUserChannel(channel);
    void change.catch(error => setMessage(String(error)));
  }, [agent, channel]);
  // Listener ownership is retired by the effect above, including StrictMode
  // replay; agent objects own no transport and become collectible with the view.
  async function publish() {
    try { await agent.broadcast(instrumentContext({ symbol, exchange })); setMessage("Selection broadcast; execution unchanged"); }
    catch (error) { setMessage(String(error)); }
  }
  async function prepare(intent: "ViewChart" | "CreateOrder") {
    try { await agent.raiseIntent(intent, instrumentContext({ symbol, exchange }), { appId: "flinttrade.terminal" }); }
    catch (error) { setMessage(String(error)); }
  }
  return <details className="shrink-0 border-b border-border-default px-3 py-1 text-xs" data-testid="instrument-links">
    <summary className="cursor-pointer text-text-secondary">Instrument links · {message}</summary>
    <div className="flex flex-wrap items-center gap-2 py-2">
      <select aria-label="Instrument link channel" className="rounded border border-border-default bg-surface-card p-2" value={channel} onChange={e => { setChannel(e.target.value); setMessage(e.target.value === "none" ? "Unlinked" : "Linked selections only"); }}>
        <option value="none">Unlinked</option>{USER_CHANNELS.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
      </select>
      <Input aria-label="Linked symbol" value={symbol} onChange={e => setSymbol(e.target.value)} placeholder="Exact symbol" className="h-8 w-36" />
      <Input aria-label="Linked venue" value={exchange} onChange={e => setExchange(e.target.value)} placeholder="Exact venue / segment" className="h-8 w-44" />
      <Button size="sm" variant="outline" disabled={channel === "none" || !symbol || !exchange} onClick={() => void publish()}>Broadcast selection</Button>
      <Button size="sm" variant="ghost" disabled={!symbol || !exchange} onClick={() => void prepare("ViewChart")}>View chart in Terminal</Button>
      <Button size="sm" variant="ghost" disabled={!symbol || !exchange} onClick={() => void prepare("CreateOrder")}>Prepare order in Terminal</Button>
    </div>
    <p className="pb-2 text-text-muted">Use the same coloured tab link to follow this selection. Unlink to stop updates. Preparing an order never submits it.</p>
  </details>;
}
