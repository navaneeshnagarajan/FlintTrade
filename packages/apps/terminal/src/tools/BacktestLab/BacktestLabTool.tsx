/** Backtest configuration and results from FlintTrade's local research engine. */
import { useEffect, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import type { Time } from 'lightweight-charts';
import { createFlintLineChart } from '@flinttrade/design-system';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useLightweightChartTheme } from '@/hooks/useChartTheme';
import { lightweightLineRuntime } from '@/lib/lightweightChartRuntime';
import { getStrategies, runBacktest, type BacktestConfig, type BacktestResult } from '@/services/ftApi';

const starters = [
  { name: 'ema_crossover', description: 'EMA Crossover' },
  { name: 'sma_crossover', description: 'SMA Crossover' },
  { name: 'rsi_mean_reversion', description: 'RSI Mean Reversion' },
];
function EquityChart({ result }: { result: BacktestResult }) {
  const host = useRef<HTMLDivElement>(null);
  const theme = useLightweightChartTheme();
  useEffect(() => {
    if (!host.current || !result.equity_curve.length) return;
    const chart = createFlintLineChart(lightweightLineRuntime, host.current, theme, {
      height: 240, series: [{ id: 'equity', options: { color: '#34d399', lineWidth: 2, priceFormat: { type: 'price', precision: 0, minMove: 1 } } }],
    });
    chart.seriesById.equity.setData(result.equity_curve.map(point => ({ time: (Date.parse(point.timestamp) / 1000) as Time, value: point.equity })));
    chart.chart.timeScale().fitContent();
    return () => chart.remove();
  }, [result, theme]);
  return <div ref={host} role="img" aria-label="Backtest equity curve" className="h-60 w-full" />;
}
function exportResult(result: BacktestResult) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'flinttrade-backtest.json'; anchor.click(); URL.revokeObjectURL(url);
}
export default function BacktestLabTool({ onClose }: { onClose?: () => void }) {
  const today = new Date().toISOString().slice(0, 10);
  const [config, setConfig] = useState<BacktestConfig>({ symbol: '', exchange: 'NSE', interval: '1d',
    start_date: `${Number(today.slice(0, 4)) - 1}${today.slice(4)}`, end_date: today,
    strategy: 'ema_crossover', initial_capital: 1_000_000, position_size_pct: 10 });
  const [strategies, setStrategies] = useState(starters);
  const [tab, setTab] = useState('configure');
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [catalogueError, setCatalogueError] = useState<string | null>(null);
  useEffect(() => {
    let current = true;
    if (typeof getStrategies === 'function') void getStrategies().then(items => {
      if (current && items.length) setStrategies(items.map(item => ({ name: item.name, description: item.description || item.name })));
    }).catch(() => { if (current) setCatalogueError('Strategy catalogue unavailable. Starter choices remain available.'); });
    return () => { current = false; };
  }, []);
  const run = useMutation({ mutationFn: runBacktest, onSuccess: value => { setResult(value); setTab('results'); } });
  const update = <K extends keyof BacktestConfig>(key: K, value: BacktestConfig[K]) => setConfig(previous => ({ ...previous, [key]: value }));
  const valid = config.symbol.trim().length > 0 && config.start_date < config.end_date && config.initial_capital > 0 && config.position_size_pct > 0 && config.position_size_pct <= 100;
  return <section className="flex h-full min-h-0 flex-col text-text-primary">
    <header className="flex items-center justify-between border-b border-border-default p-3"><h2>Backtest Lab</h2>{onClose && <Button variant="ghost" onClick={onClose}>Close</Button>}</header>
    <Tabs className="flex min-h-0 flex-1 flex-col" value={tab} onValueChange={setTab}><TabsList><TabsTrigger value="configure">Configure</TabsTrigger><TabsTrigger value="results">Results</TabsTrigger><TabsTrigger value="trades">Trades</TabsTrigger></TabsList>
      <TabsContent value="configure" className="space-y-4 overflow-auto p-3">
        <label className="block">Strategy<Select value={config.strategy} onValueChange={value => update('strategy', value)}><SelectTrigger><SelectValue placeholder="Select strategy" /></SelectTrigger><SelectContent>{strategies.map(item => <SelectItem key={item.name} value={item.name}>{item.description}</SelectItem>)}</SelectContent></Select></label>
        {catalogueError && <p>{catalogueError}</p>}
        <div className="grid grid-cols-2 gap-3">
          <label>Symbol<Input aria-label="Symbol" placeholder="RELIANCE" value={config.symbol} onChange={event => update('symbol', event.target.value)} /></label>
          <label>Exchange<Input aria-label="Exchange" value={config.exchange} onChange={event => update('exchange', event.target.value)} /></label>
          <label>Interval<Input aria-label="Interval" value={config.interval} onChange={event => update('interval', event.target.value)} /></label>
          <label>Initial capital<Input aria-label="Initial capital" type="number" min={1} value={config.initial_capital} onChange={event => update('initial_capital', Number(event.target.value))} /></label>
          <label>Start date<Input aria-label="Start date" type="date" value={config.start_date} onChange={event => update('start_date', event.target.value)} /></label>
          <label>End date<Input aria-label="End date" type="date" value={config.end_date} onChange={event => update('end_date', event.target.value)} /></label>
          <label>Position size %<Input aria-label="Position size %" type="number" min={1} max={100} value={config.position_size_pct} onChange={event => update('position_size_pct', Number(event.target.value))} /></label>
        </div>
        <Button disabled={!valid || run.isPending} onClick={() => { setResult(null); run.mutate({ ...config, symbol: config.symbol.trim() }); }}>{run.isPending ? 'Running…' : 'Run Backtest'}</Button>
        {run.error && <p role="alert">{run.error.message}</p>}
      </TabsContent>
      <TabsContent value="results" className="space-y-4 overflow-auto p-3">{result ? <>
        <EquityChart result={result} /><dl className="grid grid-cols-2 gap-3">{Object.entries(result.metrics).map(([key, value]) => <div key={key}><dt className="capitalize">{key.replaceAll('_', ' ')}</dt><dd className="font-mono">{Number.isFinite(value) ? Number(value).toLocaleString('en-IN', { maximumFractionDigits: 3 }) : '—'}</dd></div>)}</dl>
        <p>Final equity: {result.final_equity.toLocaleString('en-IN')} · {result.total_bars} bars</p><Button onClick={() => exportResult(result)}>Export results</Button>
      </> : <p>Run a backtest to see results.</p>}</TabsContent>
      <TabsContent value="trades" className="overflow-auto p-3">{result ? <table className="w-full text-xs"><caption>Completed simulated trades</caption><thead><tr>{['Symbol', 'Side', 'Quantity', 'Entry', 'Exit', 'P&L', 'Charges', 'Bars'].map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>{result.trades.map((trade, index) => <tr key={index}><td>{trade.symbol}</td><td>{trade.side}</td><td>{trade.quantity}</td><td title={trade.entry_timestamp}>{trade.entry_price}</td><td title={trade.exit_timestamp}>{trade.exit_price}</td><td>{trade.net_pnl ?? trade.pnl}</td><td>{trade.commission}</td><td>{trade.bars_held}</td></tr>)}</tbody></table> : <p>Run a backtest to see trades.</p>}</TabsContent>
    </Tabs>
  </section>;
}
