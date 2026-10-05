/** FlintTrade local Pine study editor and signal preview. */
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { EXCHANGES, INTERVALS, PINE_TEMPLATES } from './types';
import { usePineRunner } from './usePineRunner';
import { computeEquityCurve, computeMetrics } from './utils';
import { LOAD_PINE_DRAFT_EVENT, readAndClearPendingPineDraft, type PineDraft } from './pineBridge';
import { EquityCurveSparkline } from './EquityCurveSparkline';
export function PineTab() {
  const [code, setCode] = useState(() => readAndClearPendingPineDraft()?.source ?? PINE_TEMPLATES.ema_crossover.code);
  const [symbol, setSymbol] = useState('NIFTY');
  const [exchange, setExchange] = useState<string>('NSE_INDEX');
  const [interval, setInterval] = useState<string>('1d');
  const [start, setStart] = useState(''), [end, setEnd] = useState('');
  const runner = usePineRunner();
  useEffect(() => {
    const receive = (event: Event) => { const draft = readAndClearPendingPineDraft() ?? (event as CustomEvent<PineDraft>).detail; if (draft?.source.trim()) setCode(draft.source); };
    window.addEventListener(LOAD_PINE_DRAFT_EVENT, receive);
    return () => window.removeEventListener(LOAD_PINE_DRAFT_EVENT, receive);
  }, []);
  const metrics = runner.result && runner.bars ? computeMetrics(runner.bars, runner.result.signals) : null;
  return <div className="space-y-3 p-3">
    <div className="flex flex-wrap gap-2">{Object.entries(PINE_TEMPLATES).map(([id, template]) => <Button key={id} size="sm" variant="outline" onClick={() => setCode(template.code)}>{template.label}</Button>)}</div>
    <label className="block">Pine Script<textarea className="min-h-64 w-full rounded border border-border-default bg-surface-base p-3 font-mono text-xs" aria-label="Pine Script editor" value={code} onChange={event => setCode(event.target.value)} /></label>
    <div className="flex flex-wrap gap-3"><label>Symbol<Input aria-label="Symbol" value={symbol} onChange={event => setSymbol(event.target.value)} /></label>
      <label>Exchange<select aria-label="Exchange" value={exchange} onChange={event => setExchange(event.target.value)}>{EXCHANGES.map(item => <option key={item}>{item}</option>)}</select></label>
      <label>Interval<select aria-label="Interval" value={interval} onChange={event => setInterval(event.target.value)}>{INTERVALS.map(item => <option key={item}>{item}</option>)}</select></label>
      <label>Start<Input type="date" value={start} onChange={event => setStart(event.target.value)} /></label><label>End<Input type="date" value={end} onChange={event => setEnd(event.target.value)} /></label>
    </div>
    <div className="flex gap-2"><Button disabled={runner.isRunning || !code.trim() || !symbol.trim()} onClick={() => void runner.run(code, symbol.trim(), exchange, interval, { ...(start ? { startDate: start } : {}), ...(end ? { endDate: end } : {}) })}>{runner.isRunning ? 'Running…' : 'Run Script'}</Button>
      <Button variant="outline" onClick={runner.reset}>Reset</Button><Button variant="outline" onClick={() => void navigator.clipboard.writeText(code)}>Copy source</Button></div>
    {runner.error && <p role="alert">{runner.error}</p>}
    {runner.result?.errors?.map((error, index) => <p role="alert" key={index}>{error}</p>)}
    {metrics && <><p>{metrics.totalSignals} signals · return {metrics.totalReturn.toFixed(2)}% · approximate Sharpe {metrics.sharpeApprox.toFixed(2)}</p><EquityCurveSparkline curve={computeEquityCurve(runner.bars, runner.result!.signals)} />
      <table className="w-full text-xs"><thead><tr><th>Bar</th><th>Signal</th><th>Label</th></tr></thead><tbody>{runner.result!.signals.map((signal, index) => <tr key={index}><td>{signal.bar}</td><td>{signal.type}</td><td>{signal.label}</td></tr>)}</tbody></table></>}
    <p className="text-xs text-text-muted">Local interpreter preview. It supports a bounded Pine subset and does not submit orders.</p>
  </div>;
}
