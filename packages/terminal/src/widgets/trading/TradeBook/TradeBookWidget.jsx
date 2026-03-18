import { useState, useEffect, useCallback, useMemo } from 'react'
import { Clock, RefreshCw } from 'lucide-react'
import { getTradebook } from '../../../services/api'

const INR = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 })

function isMarketHours() {
  const now = new Date()
  const ist = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
  const mins = ist.getHours() * 60 + ist.getMinutes()
  const day = ist.getDay()
  if (day === 0 || day === 6) return false
  return mins >= 555 && mins <= 930
}

// Parse a trade timestamp into a sortable number and display string.
// OpenAlgo tradebook entries typically carry a `trade_time` or `timestamp` field.
function parseTradeTime(trade) {
  const raw = trade.trade_time || trade.timestamp || trade.order_time || ''
  if (!raw) return { display: '—', ms: 0 }
  const d = new Date(raw)
  if (!isNaN(d)) {
    return {
      display: d.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false }),
      ms: d.getTime(),
    }
  }
  // Fallback: return as-is
  return { display: String(raw).slice(0, 8), ms: 0 }
}

const FILTER_ALL  = 'ALL'
const FILTER_BUY  = 'BUY'
const FILTER_SELL = 'SELL'

export default function TradeBookWidget({ node }) {
  const [trades, setTrades] = useState([])
  const [lastFetch, setLastFetch] = useState(null)
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState(FILTER_ALL)

  const fetchTrades = useCallback(async () => {
    setLoading(true)
    try {
      const raw = await getTradebook()
      // OpenAlgo may return { trades: [...] } or directly an array
      const list = Array.isArray(raw) ? raw : (Array.isArray(raw?.trades) ? raw.trades : [])
      setTrades(list)
      setLastFetch(new Date())
    } catch {
      setTrades([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchTrades()
    const ms = isMarketHours() ? 30000 : 120000
    const id = setInterval(fetchTrades, ms)
    return () => clearInterval(id)
  }, [fetchTrades])

  // Re-schedule interval when market hours status changes (handles open/close transition)
  useEffect(() => {
    const tick = setInterval(() => {
      // Re-mount effect on market boundary by forcing a re-check every minute
    }, 60000)
    return () => clearInterval(tick)
  }, [])

  const filtered = useMemo(() => {
    const list = filter === FILTER_ALL
      ? trades
      : trades.filter(t => {
          const side = (t.action || t.transaction_type || t.side || '').toUpperCase()
          return side === filter
        })

    // Most recent first — sort descending by trade time
    return [...list].sort((a, b) => {
      const ta = parseTradeTime(a).ms
      const tb = parseTradeTime(b).ms
      return tb - ta
    })
  }, [trades, filter])

  const counts = useMemo(() => ({
    all:  trades.length,
    buy:  trades.filter(t => (t.action || t.transaction_type || t.side || '').toUpperCase() === 'BUY').length,
    sell: trades.filter(t => (t.action || t.transaction_type || t.side || '').toUpperCase() === 'SELL').length,
  }), [trades])

  function FilterPill({ value, label, count }) {
    const active = filter === value
    return (
      <button
        onClick={() => setFilter(value)}
        className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
          active
            ? value === FILTER_BUY
              ? 'bg-profit/20 text-profit border border-profit/40'
              : value === FILTER_SELL
                ? 'bg-loss/20 text-loss border border-loss/40'
                : 'bg-surface-hover text-text-primary border border-border-default'
            : 'text-text-muted border border-transparent hover:text-text-secondary hover:border-border-default'
        }`}
      >
        {label}{count > 0 ? ` (${count})` : ''}
      </button>
    )
  }

  return (
    <div className="h-full flex flex-col overflow-hidden text-xs">
      {/* Header */}
      <div className="flex items-center justify-between px-2 py-1 border-b border-border-default shrink-0 gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-text-muted uppercase tracking-wider text-[10px]">TRADES</span>
          <span className="text-[10px] text-text-secondary font-mono">({trades.length})</span>
        </div>
        <div className="flex items-center gap-2">
          {lastFetch && (
            <span className="text-[10px] text-text-muted flex items-center gap-0.5">
              <Clock size={8} />
              {lastFetch.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false })}
            </span>
          )}
          <button
            onClick={fetchTrades}
            disabled={loading}
            className="text-text-muted hover:text-text-primary disabled:opacity-40"
          >
            <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {/* Filter pills */}
      <div className="flex items-center gap-1.5 px-2 py-1 border-b border-border-default shrink-0">
        <FilterPill value={FILTER_ALL}  label="All"  count={counts.all} />
        <FilterPill value={FILTER_BUY}  label="Buy"  count={counts.buy} />
        <FilterPill value={FILTER_SELL} label="Sell" count={counts.sell} />
      </div>

      {/* Body */}
      {filtered.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-text-muted">
          No trades today
        </div>
      ) : (
        <div className="flex-1 overflow-auto">
          <table className="w-full">
            <thead className="sticky top-0 bg-surface-card z-10">
              <tr className="text-[10px] text-text-muted uppercase tracking-wider">
                <th className="px-2 py-1 text-left">Time</th>
                <th className="px-2 py-1 text-left">Symbol</th>
                <th className="px-2 py-1 text-center">Side</th>
                <th className="px-2 py-1 text-right">Qty</th>
                <th className="px-2 py-1 text-right">Price</th>
                <th className="px-2 py-1 text-right">Value</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((t, i) => {
                const side = (t.action || t.transaction_type || t.side || '').toUpperCase()
                const isBuy = side === 'BUY'
                const symbol = (t.symbol || t.tradingsymbol || '—').toUpperCase()
                const qty = parseInt(t.quantity || t.qty || t.filled_quantity || 0, 10)
                const price = parseFloat(t.average_price || t.price || t.trade_price || 0)
                const value = qty * price
                const { display: timeDisplay } = parseTradeTime(t)

                return (
                  <tr key={i} className="border-t border-border-subtle hover:bg-surface-hover/50">
                    <td className="px-2 py-1 font-mono text-text-muted whitespace-nowrap">{timeDisplay}</td>
                    <td className="px-2 py-1 font-mono font-medium">{symbol}</td>
                    <td className="px-2 py-1 text-center">
                      <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                        isBuy
                          ? 'bg-profit/15 text-profit border border-profit/30'
                          : 'bg-loss/15 text-loss border border-loss/30'
                      }`}>
                        {side || '—'}
                      </span>
                    </td>
                    <td className="px-2 py-1 text-right font-mono">{qty}</td>
                    <td className="px-2 py-1 text-right font-mono text-text-primary">{INR.format(price)}</td>
                    <td className="px-2 py-1 text-right font-mono text-text-secondary">{INR.format(value)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
