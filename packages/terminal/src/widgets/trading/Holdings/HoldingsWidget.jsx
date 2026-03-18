import { useState, useEffect, useCallback, useMemo } from 'react'
import { Clock, Search, ChevronUp, ChevronDown, ChevronsUpDown, RefreshCw } from 'lucide-react'
import { getHoldings, getMultiQuotes } from '../../../services/api'

const INR = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 })

function isMarketHours() {
  const now = new Date()
  const ist = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
  const mins = ist.getHours() * 60 + ist.getMinutes()
  const day = ist.getDay()
  if (day === 0 || day === 6) return false
  return mins >= 555 && mins <= 930
}

function SortIcon({ col, sortCol, sortDir }) {
  if (sortCol !== col) return <ChevronsUpDown size={10} className="opacity-40" />
  return sortDir === 'asc'
    ? <ChevronUp size={10} className="text-text-primary" />
    : <ChevronDown size={10} className="text-text-primary" />
}

export default function HoldingsWidget({ node }) {
  const [holdings, setHoldings] = useState([])
  const [ltpMap, setLtpMap] = useState({})
  const [lastFetch, setLastFetch] = useState(null)
  const [loading, setLoading] = useState(false)
  const [sortCol, setSortCol] = useState('symbol')
  const [sortDir, setSortDir] = useState('asc')
  const [search, setSearch] = useState('')

  const fetchHoldings = useCallback(async () => {
    setLoading(true)
    try {
      const raw = await getHoldings()
      const list = Array.isArray(raw) ? raw : []
      setHoldings(list)
      setLastFetch(new Date())

      // Fetch LTP for all holdings that don't carry it
      const needsLtp = list.filter(h => !h.ltp && !h.close_price)
      if (needsLtp.length > 0) {
        try {
          const symbols = needsLtp.map(h => ({
            symbol: h.symbol || h.tradingsymbol,
            exchange: h.exchange || 'NSE',
          }))
          const quotes = await getMultiQuotes(symbols)
          const map = {}
          if (Array.isArray(quotes)) {
            quotes.forEach(q => {
              map[q.symbol] = parseFloat(q.ltp || q.close || 0)
            })
          }
          setLtpMap(map)
        } catch {
          // LTP fetch failed — use avg_price as fallback
        }
      }
    } catch {
      setHoldings([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchHoldings()
    // Holdings don't change during the day — 60s is fine regardless of market hours
    const id = setInterval(fetchHoldings, 60000)
    return () => clearInterval(id)
  }, [fetchHoldings])

  // Resolve LTP for a holding: prefer API-provided ltp, then our map, then avg_price
  const ltp = useCallback((h) => {
    const sym = h.symbol || h.tradingsymbol
    if (h.ltp) return parseFloat(h.ltp)
    if (h.close_price) return parseFloat(h.close_price)
    if (ltpMap[sym]) return ltpMap[sym]
    return parseFloat(h.average_price || h.avg_price || 0)
  }, [ltpMap])

  const enriched = useMemo(() => holdings.map(h => {
    const qty = parseInt(h.quantity || h.qty || 0, 10)
    const avgPrice = parseFloat(h.average_price || h.avg_price || 0)
    const currentLtp = ltp(h)
    const invested = qty * avgPrice
    const currentVal = qty * currentLtp
    const pnl = currentVal - invested
    const pnlPct = invested > 0 ? (pnl / invested) * 100 : 0
    return {
      ...h,
      _qty: qty,
      _avgPrice: avgPrice,
      _ltp: currentLtp,
      _invested: invested,
      _currentVal: currentVal,
      _pnl: pnl,
      _pnlPct: pnlPct,
      _symbol: (h.symbol || h.tradingsymbol || '').toUpperCase(),
    }
  }), [holdings, ltp])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return enriched
    return enriched.filter(h => h._symbol.toLowerCase().includes(q))
  }, [enriched, search])

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      let aVal, bVal
      switch (sortCol) {
        case 'symbol':   aVal = a._symbol;      bVal = b._symbol;      break
        case 'qty':      aVal = a._qty;          bVal = b._qty;          break
        case 'avg':      aVal = a._avgPrice;     bVal = b._avgPrice;     break
        case 'ltp':      aVal = a._ltp;          bVal = b._ltp;          break
        case 'value':    aVal = a._currentVal;   bVal = b._currentVal;   break
        case 'pnl':      aVal = a._pnl;          bVal = b._pnl;          break
        case 'pnlpct':   aVal = a._pnlPct;       bVal = b._pnlPct;       break
        default:         aVal = a._symbol;        bVal = b._symbol
      }
      if (typeof aVal === 'string') {
        return sortDir === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal)
      }
      return sortDir === 'asc' ? aVal - bVal : bVal - aVal
    })
  }, [filtered, sortCol, sortDir])

  const totals = useMemo(() => ({
    invested: enriched.reduce((s, h) => s + h._invested, 0),
    currentVal: enriched.reduce((s, h) => s + h._currentVal, 0),
    pnl: enriched.reduce((s, h) => s + h._pnl, 0),
  }), [enriched])

  function handleSort(col) {
    if (sortCol === col) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortCol(col)
      setSortDir('asc')
    }
  }

  function ThCell({ col, label, align = 'right' }) {
    return (
      <th
        className={`px-2 py-1 text-${align} cursor-pointer select-none hover:text-text-primary whitespace-nowrap`}
        onClick={() => handleSort(col)}
      >
        <span className="inline-flex items-center gap-0.5 justify-end">
          {label}
          <SortIcon col={col} sortCol={sortCol} sortDir={sortDir} />
        </span>
      </th>
    )
  }

  return (
    <div className="h-full flex flex-col overflow-hidden text-xs">
      {/* Header */}
      <div className="flex items-center justify-between px-2 py-1 border-b border-border-default shrink-0 gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-text-muted uppercase tracking-wider text-[10px]">
            HOLDINGS
          </span>
          <span className="text-[10px] text-text-secondary font-mono">
            ({holdings.length})
          </span>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <span className="font-mono text-[10px] text-text-secondary">
            Inv: ₹{INR.format(totals.invested)}
          </span>
          <span className="font-mono text-[10px] text-text-secondary">
            Val: ₹{INR.format(totals.currentVal)}
          </span>
          <span className={`font-mono text-[10px] font-medium ${totals.pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
            P&L: {totals.pnl >= 0 ? '+' : ''}₹{INR.format(Math.abs(totals.pnl))}
          </span>
          {lastFetch && (
            <span className="text-[10px] text-text-muted flex items-center gap-0.5">
              <Clock size={8} />
              {lastFetch.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false })}
            </span>
          )}
          <button
            onClick={fetchHoldings}
            disabled={loading}
            className="text-text-muted hover:text-text-primary disabled:opacity-40"
          >
            <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="px-2 py-1 border-b border-border-default shrink-0">
        <div className="flex items-center gap-1 bg-surface-base rounded px-1.5 py-0.5">
          <Search size={10} className="text-text-muted shrink-0" />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Filter symbol…"
            className="bg-transparent text-text-primary placeholder-text-muted outline-none text-xs w-full font-mono"
          />
        </div>
      </div>

      {/* Body */}
      {sorted.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-text-muted">
          {holdings.length === 0 ? 'No holdings' : 'No matches'}
        </div>
      ) : (
        <div className="flex-1 overflow-auto">
          <table className="w-full">
            <thead className="sticky top-0 bg-surface-card z-10">
              <tr className="text-[10px] text-text-muted uppercase tracking-wider">
                <ThCell col="symbol"  label="Symbol"  align="left" />
                <ThCell col="qty"     label="Qty" />
                <ThCell col="avg"     label="Avg" />
                <ThCell col="ltp"     label="LTP" />
                <ThCell col="value"   label="Value" />
                <ThCell col="pnl"     label="P&L" />
                <ThCell col="pnlpct"  label="P&L%" />
              </tr>
            </thead>
            <tbody>
              {sorted.map((h, i) => (
                <tr key={i} className="border-t border-border-subtle hover:bg-surface-hover/50">
                  <td className="px-2 py-1 font-mono font-medium text-left">{h._symbol}</td>
                  <td className="px-2 py-1 text-right font-mono text-text-secondary">{h._qty}</td>
                  <td className="px-2 py-1 text-right font-mono text-text-secondary">{INR.format(h._avgPrice)}</td>
                  <td className="px-2 py-1 text-right font-mono text-text-primary">{INR.format(h._ltp)}</td>
                  <td className="px-2 py-1 text-right font-mono text-text-secondary">{INR.format(h._currentVal)}</td>
                  <td className={`px-2 py-1 text-right font-mono font-medium ${h._pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
                    {h._pnl >= 0 ? '+' : ''}₹{INR.format(Math.abs(h._pnl))}
                  </td>
                  <td className={`px-2 py-1 text-right font-mono font-medium ${h._pnlPct >= 0 ? 'text-profit' : 'text-loss'}`}>
                    {h._pnlPct >= 0 ? '+' : ''}{h._pnlPct.toFixed(2)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
