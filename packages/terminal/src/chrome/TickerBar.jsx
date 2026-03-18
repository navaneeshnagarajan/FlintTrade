import { useDataBus } from '../hooks/useDataBus'

/**
 * The four market-wide indices shown in the ticker.
 * DataBus topic key: quote:<symbol>:<exchange>
 * Data shape: { ltp: number, change: number, pct: number }
 */
const INDICES = [
  { symbol: 'NIFTY', exchange: 'NSE_INDEX', name: 'NIFTY 50' },
  { symbol: 'SENSEX', exchange: 'BSE_INDEX', name: 'SENSEX' },
  { symbol: 'BANKNIFTY', exchange: 'NSE_INDEX', name: 'BANK NIFTY' },
  { symbol: 'INDIA VIX', exchange: 'NSE_INDEX', name: 'VIX' },
]

function IndexChip({ symbol, exchange, name }) {
  const { data } = useDataBus(`quote:${symbol}:${exchange}`)

  const ltp = data?.ltp ?? null
  const change = data?.change ?? 0
  const pct = data?.pct ?? 0
  const isUp = change >= 0

  return (
    <div className="flex items-center gap-2 px-4 shrink-0 border-r border-border-default last:border-r-0 h-full">
      <span className="text-xs text-text-muted">{name}</span>
      <span className="text-xs font-mono text-text-primary tabular-nums">
        {ltp !== null ? ltp.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '\u2014'}
      </span>
      <span
        className={`text-xs font-mono tabular-nums ${
          ltp === null ? 'text-text-muted' : isUp ? 'text-profit' : 'text-loss'
        }`}
      >
        {ltp !== null
          ? `${isUp ? '\u25b2' : '\u25bc'}${Math.abs(pct).toFixed(2)}%`
          : ''}
      </span>
    </div>
  )
}

/**
 * TickerBar — always-visible bar at h-7 showing live index prices.
 * Subscribes via DataBus; shows em-dash when no data is available.
 */
export default function TickerBar() {
  return (
    <div className="h-7 bg-surface-base border-b border-border-default flex items-center overflow-x-auto shrink-0">
      {INDICES.map((idx) => (
        <IndexChip key={`${idx.symbol}:${idx.exchange}`} {...idx} />
      ))}
    </div>
  )
}
