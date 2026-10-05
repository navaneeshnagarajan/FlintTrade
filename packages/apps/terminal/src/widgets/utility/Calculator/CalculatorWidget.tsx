/** FlintTrade local trade arithmetic. The calculator never places an order. */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { FlintDonutBreakdown } from "@flinttrade/design-system";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAccountReadContext } from "@/hooks/useAccountReadsEnabled";
import { statutoryLeg } from "@/lib/indianCharges";
import { lotSizeFromMaster, useInstrumentLotRows } from "@/lib/instrumentLots";
import { getFunds, getMargin } from "@/services/api";
import type { WidgetProps } from "@/types/widgets";

const SECTIONS = { sizing: "Sizing", target: "Target / R:R", brokerage: "Brokerage", margin: "Margin" } as const;
type Section = keyof typeof SECTIONS;
type Method = "Fixed %" | "Kelly" | "ATR";
const inr = (value: number) => `₹${new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(value)}`;
const positive = (...values: number[]) => values.every((value) => Number.isFinite(value) && value > 0);

function NumericField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label className="block space-y-1 text-xs text-text-secondary">{label}
    <Input type="number" aria-label={label} value={value} step="any" onChange={(event) => onChange(event.target.value)} />
  </label>;
}
function Result({ label, value }: { label: string; value: string }) {
  return <div className="flex items-center justify-between gap-3 py-1.5 text-xs"><span className="text-text-muted">{label}</span><span className="font-mono text-text-primary">{value}</span></div>;
}

function MarginPanel({ symbol, lot, price }: { symbol: string; lot: number; price: number }) {
  const context = useAccountReadContext();
  const [rate, setRate] = useState("15");
  const signature = JSON.stringify([context?.identity.scopeKey, context?.enabled, symbol, lot, price]);
  const sequence = useRef(0);
  const activeSignature = useRef(signature);
  activeSignature.current = signature;
  const controller = useRef<AbortController | undefined>(undefined);
  type Margin = Awaited<ReturnType<typeof getMargin>>;
  type Funds = Awaited<ReturnType<typeof getFunds>>;
  const [observation, setObservation] = useState<{ signature: string; margin?: Margin; funds?: Funds; pending: boolean; error?: string }>();
  const visible = observation?.signature === signature ? observation : undefined;
  useEffect(() => () => { controller.current?.abort(); }, [signature]);
  const estimate = positive(lot, price, Number(rate)) ? lot * price * Number(rate) / 100 : 0;
  const margin = visible?.margin;

  async function requestMargin(event: FormEvent) {
    event.preventDefault();
    if (!context?.enabled || !positive(lot)) return;
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    const requestNumber = ++sequence.current;
    setObservation((previous) => ({ ...(previous?.signature === signature ? previous : {}), signature, pending: true }));
    try {
      const [funds, quote] = await Promise.all([
        getFunds(context, abort.signal),
        getMargin(context, symbol, "NFO", lot, "NRML", "BUY", abort.signal),
      ]);
      if (!abort.signal.aborted && requestNumber === sequence.current && activeSignature.current === signature) {
        setObservation({ signature, funds, margin: quote, pending: false });
      }
    } catch {
      if (!abort.signal.aborted && requestNumber === sequence.current && activeSignature.current === signature) {
        setObservation({ signature, pending: false, error: "API unavailable — showing estimate" });
      }
    }
  }
  return <div className="space-y-3">
    <h3 className="text-sm font-semibold">Margin Required</h3>
    <p className="text-xs text-text-muted">Manual margin scenario: the percentage below is your assumption. This SPAN-like illustration is not a broker quote.</p>
    <NumericField label="Assumed margin %" value={rate} onChange={setRate} />
    <p className="text-xs">Product: <span>NRML</span> · {symbol} · {lot} units</p>
    <span className="text-xs font-semibold">{margin ? context?.identity.mode === "practice" ? "PRACTICE" : "LIVE" : "ESTIMATE"}</span>
    <Result label="SPAN Margin" value={inr(margin?.span_margin ?? estimate * 0.6)} />
    <Result label="Exposure Margin" value={inr(margin?.exposure_margin ?? estimate * 0.4)} />
    <Result label="Total Required" value={inr(margin?.total_margin_required ?? estimate)} />
    {visible?.funds ? <><Result label="Available Funds" value={inr(visible.funds.availableCash)} /><Result label="After Margin" value={inr(visible.funds.availableCash - (margin?.total_margin_required ?? estimate))} /></> : null}
    <form onSubmit={(event) => { void requestMargin(event); }}>
      <Button type="submit" disabled={!context?.enabled || Boolean(visible?.pending)}>{visible?.pending ? "Fetching…" : "Get Live Margin"}</Button>
    </form>
    {visible?.error ? <p role="alert" className="text-xs text-text-muted">{visible.error}</p> : null}
    <p className="text-xs text-text-muted">Native broker HTTP reads remain unavailable until the read cutover. Practice uses its own account snapshot.</p>
  </div>;
}

export default function CalculatorWidget({ params, api }: WidgetProps) {
  const [section, setSection] = useState<Section>(() => params?.tab && Object.hasOwn(SECTIONS, String(params.tab)) ? params.tab as Section : "sizing");
  const [method, setMethod] = useState<Method>("Fixed %");
  const [capital, setCapital] = useState("500000");
  const [riskPercent, setRiskPercent] = useState("1");
  const [entry, setEntry] = useState("22000");
  const [stop, setStop] = useState("21800");
  const [target, setTarget] = useState("22500");
  const [quantity, setQuantity] = useState("1");
  const [lot, setLot] = useState("50");
  const [winRate, setWinRate] = useState("55");
  const [rewardRisk, setRewardRisk] = useState("2");
  const [atr, setAtr] = useState("180");
  const [atrMultiplier, setAtrMultiplier] = useState("1.5");
  const [symbol, setSymbol] = useState("NIFTY");
  const [brokeragePrice, setBrokeragePrice] = useState("100");
  const rows = useInstrumentLotRows();
  const masterLot = lotSizeFromMaster(symbol, rows) ?? 1;
  // An edit belongs to this instrument-master lot revision. Another symbol's
  // master update does not discard the operator's edit.
  const lotRevision = `${symbol}:${masterLot}`;
  const [brokerLotEdit, setBrokerLotEdit] = useState<{ revision: string; value: string }>();
  const brokerLot = brokerLotEdit?.revision === lotRevision ? brokerLotEdit.value : String(masterLot);
  const tradeEntry = Number(entry), tradeStop = Number(stop), unitsPerLot = Number(lot), accountCapital = Number(capital);
  const direction = tradeStop > tradeEntry ? -1 : 1;
  const distance = method === "ATR" ? Number(atr) * Number(atrMultiplier) : Math.abs(tradeEntry - tradeStop);
  const kellyStake = Number(rewardRisk) > 0 ? Math.max(0, Number(winRate) / 100 - (1 - Number(winRate) / 100) / Number(rewardRisk)) / 2 : 0;
  const budget = accountCapital * (method === "Kelly" ? kellyStake : Number(riskPercent) / 100);
  const sizingValid = positive(accountCapital, unitsPerLot, tradeEntry, tradeStop, distance, budget) && Number.isInteger(unitsPerLot)
    && (method === "Kelly" ? Number(winRate) <= 100 && Number(winRate) >= 0 : Number(riskPercent) <= 100);
  const lots = sizingValid ? Math.floor(budget / (distance * unitsPerLot)) : 0;
  const minimumRisk = unitsPerLot * distance;
  const actualRisk = lots * minimumRisk;
  const riskShare = sizingValid ? actualRisk / accountCapital * 100 : 0;
  const derivedTarget = target === "" ? tradeEntry + direction * Math.abs(tradeEntry - tradeStop) * Number(rewardRisk) : Number(target);
  const reward = direction * (derivedTarget - tradeEntry);
  const riskDistance = Math.abs(tradeEntry - tradeStop);
  const targetValid = positive(tradeEntry, tradeStop, derivedTarget, riskDistance, reward, Number(quantity), unitsPerLot)
    && Number.isInteger(Number(quantity)) && Number.isInteger(unitsPerLot);
  const rr = targetValid ? reward / riskDistance : 0;
  const breakeven = 100 / (1 + rr);
  const turnover = Number(brokerLot) * Number(brokeragePrice);
  const today = new Date();
  const on = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  const buy = statutoryLeg({ exchange: "NSE", segment: "equity_options", turnover: Math.max(0, turnover), isBuy: true, on, brokerage: 20 });
  const sell = statutoryLeg({ exchange: "NSE", segment: "equity_options", turnover: Math.max(0, turnover), isBuy: false, on, brokerage: 20 });
  const chargeRows = [["STT", buy.stt + sell.stt], ["Brokerage", buy.brokerage + sell.brokerage], ["Exchange Charges", buy.exchangeCharges + sell.exchangeCharges], ["SEBI Fee", buy.sebiFee + sell.sebiFee], ["Stamp Duty", buy.stampDuty + sell.stampDuty], ["GST", buy.gst + sell.gst], ["Total Cost", buy.total + sell.total]] as const;

  function chooseSection(next: Section) { setSection(next); api.updateParameters({ tab: next }); }
  function template(name: string) {
    const values = name === "Conservative" ? [500000, 1, 2] : name === "Balanced" ? [200000, 2, 2] : [100000, 3, 3];
    setCapital(String(values[0])); setRiskPercent(String(values[1])); setRewardRisk(String(values[2]));
  }
  const tradeFields = <>
    <NumericField label="Entry Price" value={entry} onChange={setEntry} />
    <NumericField label="Stop Loss" value={stop} onChange={setStop} />
    <NumericField label="Lot Size" value={lot} onChange={setLot} />
  </>;
  return <section className="h-full overflow-auto p-4 space-y-4" aria-label="Trade calculator">
    <h2 className="text-sm font-semibold">Calculator</h2>
    <div role="tablist" aria-label="Calculator sections" className="flex flex-wrap gap-1">{Object.entries(SECTIONS).map(([key, label]) => <Button key={key} role="tab" aria-selected={section === key} variant={section === key ? "secondary" : "ghost"} size="sm" onClick={() => chooseSection(key as Section)}>{label}</Button>)}</div>
    {section === "sizing" ? <>
      <div className="flex flex-wrap gap-2">{["Conservative", "Balanced", "Aggressive"].map((name) => <Button key={name} size="sm" variant="outline" onClick={() => template(name)}>{name}</Button>)}</div>
      <div role="tablist" aria-label="Position sizing method" className="flex gap-1">{(["Fixed %", "Kelly", "ATR"] as Method[]).map((name) => <Button key={name} role="tab" aria-selected={method === name} variant={method === name ? "secondary" : "ghost"} onClick={() => setMethod(name)}>{name}</Button>)}</div>
      <div className="grid grid-cols-2 gap-3">
        <NumericField label="Account Capital" value={capital} onChange={setCapital} />
        {method === "Kelly" ? <><NumericField label="Win Rate %" value={winRate} onChange={setWinRate} /><NumericField label="Reward : Risk" value={rewardRisk} onChange={setRewardRisk} /></> : <NumericField label="Risk per Trade %" value={riskPercent} onChange={setRiskPercent} />}
        {tradeFields}
        {method === "ATR" ? <><NumericField label="ATR Value" value={atr} onChange={setAtr} /><NumericField label="ATR Multiplier" value={atrMultiplier} onChange={setAtrMultiplier} /></> : null}
      </div>
      {sizingValid ? <><Result label="Position Size (lots)" value={String(lots)} /><Result label="Units (shares)" value={String(lots * unitsPerLot)} /><Result label="Position Value" value={inr(lots * unitsPerLot * tradeEntry)} /><Result label="SL Points" value={distance.toFixed(2)} /><Result label="Risk Budget" value={inr(budget)} /><Result label="Actual Risk" value={inr(actualRisk)} /><Result label="Minimum Unit Risk" value={inr(minimumRisk)} />
        {method === "Kelly" ? <Result label="Kelly Stake" value={`${(kellyStake * 100).toFixed(2)}%`} /> : method === "ATR" ? <Result label="Stop Loss (from ATR)" value={inr(tradeEntry - direction * distance)} /> : null}
        <div className="flex flex-wrap items-center gap-4"><FlintDonutBreakdown ariaLabel="Capital allocation" slices={[{ label: "At Risk", value: Math.min(100, riskShare), color: "#fb7185" }, { label: "Available", value: Math.max(0, 100 - riskShare), color: "#34d399" }]} /><div className="flex-1"><Result label="At Risk" value={`${riskShare.toFixed(2)}%`} /><Result label="Available" value={`${Math.max(0, 100 - riskShare).toFixed(2)}%`} /></div></div>
        {sizingValid && lots === 0 ? <p role="status" className="text-xs text-amber-400">A single {unitsPerLot === 1 ? "share" : "lot"} risks {inr(minimumRisk)} — more than the {inr(budget)} you allowed. Your budget cannot cover a whole tradable unit. No position fits this risk limit.</p> : null}
      </> : <p className="text-xs text-text-muted">Fill in all fields with positive values and a distinct stop price.</p>}
    </> : section === "target" ? <>
      <div className="grid grid-cols-2 gap-3">{tradeFields}<NumericField label="Target Price" value={target} onChange={setTarget} /><NumericField label="Quantity (lots)" value={quantity} onChange={setQuantity} />
        <label className="text-xs">Target R:R<Select value={rewardRisk} onValueChange={setRewardRisk}><SelectTrigger aria-label="Target R:R"><SelectValue /></SelectTrigger><SelectContent>{[1, 1.5, 2, 3, 4].map((ratio) => <SelectItem key={ratio} value={String(ratio)}>{ratio.toFixed(2)} : 1</SelectItem>)}</SelectContent></Select></label>
      </div>
      {targetValid ? <><Result label="Target" value={inr(derivedTarget)} /><Result label="Reward Points" value={reward.toFixed(2)} /><Result label="Risk per Trade" value={inr(riskDistance * Number(quantity) * unitsPerLot)} /><Result label="Potential Profit" value={inr(reward * Number(quantity) * unitsPerLot)} /><Result label="R:R Ratio" value={`${rr.toFixed(2)} : 1`} /><Result label="Breakeven Win Rate" value={`${breakeven.toFixed(1)}%`} /><div aria-label="Risk reward ratio" className="h-2 rounded bg-loss overflow-hidden"><div className="h-full bg-profit" style={{ width: `${100 - breakeven}%` }} /></div><p className="text-xs text-text-muted">Win {breakeven.toFixed(1)}% of your trades to break even at this R:R, before charges.</p></> : <p className="text-xs text-text-muted">Enter entry, stop loss and target on the correct side of the trade.</p>}
    </> : <>
      <div className="grid grid-cols-2 gap-3"><label className="text-xs">Underlying<Input aria-label="Underlying" value={symbol} onChange={(event) => setSymbol(event.target.value.toUpperCase())} /></label><NumericField label="Price (₹)" value={brokeragePrice} onChange={setBrokeragePrice} /><NumericField label="Lot Size" value={brokerLot} onChange={(value) => setBrokerLotEdit({ revision: lotRevision, value })} /></div>
      <p className="text-xs text-text-muted">{masterLot > 1 ? "Lot size comes from the broker instrument master." : "No lot size is available in the cached instrument master. Enter a lot size to calculate a scenario."}</p>
      {section === "brokerage" ? <div><h3 className="text-sm font-semibold">Charges Breakdown</h3>{chargeRows.map(([label, value]) => <Result key={label} label={label} value={inr(value)} />)}<Result label="Breakeven/Unit" value={`₹${(positive(Number(brokerLot)) ? (buy.total + sell.total) / Number(brokerLot) : 0).toFixed(3)}`} /><p className="text-xs text-text-muted">Illustrates one buy and one sell with ₹20 brokerage per leg. Rates use the shared dated statutory table.</p></div> : <MarginPanel symbol={symbol} lot={Number(brokerLot)} price={Number(brokeragePrice)} />}
    </>}
  </section>;
}
