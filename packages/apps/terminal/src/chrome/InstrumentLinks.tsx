import { useEffect, useId, useMemo, useState } from "react";
import { ChevronDown, Link2, Unlink } from "lucide-react";
import { useStore } from "jotai";
import { createWidgetAgent } from "@/services/fdc3/widgetAgent";
import { instrumentContext, instrumentFromContext } from "@/services/fdc3/contexts";
import { USER_CHANNELS } from "@/services/fdc3/channels";
import type { AppId } from "@/layout/appCatalog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { cn } from "@/lib/utils";

/** Selection bus only. Never reads or writes account/mode/grant stores. */
export function InstrumentLinks({ app, compact = false, onOpenChange }: { app: AppId; compact?: boolean; onOpenChange?: (open: boolean) => void }) {
  const store = useStore();
  const [open, setOpen] = useState(false);
  const panelId = useId();
  useEffect(() => { onOpenChange?.(open); }, [open, onOpenChange]);
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
  const linked = channel !== "none";
  return <div className="contents" data-testid="instrument-links">
    <Button variant="ghost" size="sm" className="shrink-0" aria-expanded={open} aria-controls={panelId} aria-label={`Instrument links · ${message}`} title={`Instrument links · ${message}`} onClick={() => setOpen(value => !value)}>
      {linked ? <Link2 aria-hidden="true" className="text-accent" /> : <Unlink aria-hidden="true" />}
      <span className={cn(compact && "sr-only")}>Links</span>
      <ChevronDown aria-hidden="true" className={cn("transition-transform", open && "rotate-180")} />
    </Button>
    <div id={panelId} role="group" aria-label="Instrument links" hidden={!open} className="order-last basis-full space-y-2 rounded-md border border-border-default bg-surface-card px-3 py-2 text-xs">
      <p role="status" className="font-medium text-text-primary">Instrument links · {message}</p>
      <div className="flex flex-wrap items-center gap-2">
        <NativeSelect controlSize="sm" aria-label="Instrument link channel" value={channel} onChange={e => { setChannel(e.target.value); setMessage(e.target.value === "none" ? "Unlinked" : "Linked selections only"); }}>
          <option value="none">Unlinked</option>{USER_CHANNELS.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
        </NativeSelect>
        <Input aria-label="Linked symbol" value={symbol} onChange={e => setSymbol(e.target.value)} placeholder="Exact symbol" className="h-8 w-36 text-xs md:text-xs" />
        <Input aria-label="Linked venue" value={exchange} onChange={e => setExchange(e.target.value)} placeholder="Exact venue / segment" className="h-8 w-44 text-xs md:text-xs" />
        <Button size="sm" variant="outline" disabled={channel === "none" || !symbol || !exchange} onClick={() => void publish()}>Broadcast selection</Button>
        <Button size="sm" variant="ghost" disabled={!symbol || !exchange} onClick={() => void prepare("ViewChart")}>View chart in Terminal</Button>
        <Button size="sm" variant="ghost" disabled={!symbol || !exchange} onClick={() => void prepare("CreateOrder")}>Prepare order in Terminal</Button>
      </div>
      <p className="text-text-muted">Use the same coloured tab link to follow this selection. Unlink to stop updates. Preparing an order never submits it.</p>
    </div>
  </div>;
}
