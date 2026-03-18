/**
 * WatchlistWidget — production watchlist for FlintTrade terminal.
 *
 * Features:
 *   - Persisted to localStorage key `flinttrade:watchlist`
 *   - Batch quote polling: 5s market hours, 60s off-hours
 *   - Debounced symbol search (300ms) with dropdown autocomplete
 *   - Per-row sparkline built from last 20 LTP samples
 *   - Right-click context menu to remove a symbol
 *   - Click publishes { symbol, exchange } to DataBus `watchlist:select`
 *   - Dense dark layout matching FlintTrade terminal theme
 */

import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import {
  Plus, X, Search, MoreVertical, Trash2,
  TrendingUp, TrendingDown,
} from 'lucide-react'
import { getMultiQuotes, searchSymbol } from '../../../services/api'
import { dataBus } from '../../../services/dataBus'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const LS_KEY = 'flinttrade:watchlist'

const DEFAULT_SYMBOLS = [
  { symbol: 'NIFTY',     exchange: 'NSE_INDEX' },
  { symbol: 'BANKNIFTY', exchange: 'NSE_INDEX' },
  { symbol: 'SBIN',      exchange: 'NSE'       },
  { symbol: 'RELIANCE',  exchange: 'NSE'       },
  { symbol: 'HDFCBANK',  exchange: 'NSE'       },
]

// Max sparkline history samples per symbol
const SPARK_MAX = 20

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** True during NSE/BSE market hours: Mon–Fri 09:15–15:30 IST. */
function isMarketHours() {
  const now = new Date()
  const ist = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
  const day = ist.getDay()
  if (day === 0 || day === 6) return false
  const mins = ist.getHours() * 60 + ist.getMinutes()
  return mins >= 555 && mins <= 930 // 09:15 – 15:30
}

const FMT = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2, minimumFractionDigits: 2 })

function fmtPrice(v) {
  if (v == null || isNaN(v)) return '—'
  return FMT.format(Number(v))
}

function fmtChange(v) {
  if (v == null || isNaN(v)) return null
  const n = Number(v)
  return (n >= 0 ? '+' : '') + FMT.format(n)
}

function fmtPct(v) {
  if (v == null || isNaN(v)) return null
  const n = Number(v)
  return (n >= 0 ? '+' : '') + n.toFixed(2) + '%'
}

/** Load watchlist from localStorage, fallback to defaults. */
function loadWatchlist() {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed) && parsed.length > 0) return parsed
    }
  } catch {}
  return DEFAULT_SYMBOLS
}

/** Persist watchlist to localStorage. */
function saveWatchlist(list) {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(list))
  } catch {}
}

// ---------------------------------------------------------------------------
// Sparkline SVG
// ---------------------------------------------------------------------------

function Sparkline({ prices, positive }) {
  if (!prices || prices.length < 2) {
    return (
      <div className="w-10 h-4 flex items-center justify-center">
        {positive === true  && <TrendingUp  size={10} className="text-profit" />}
        {positive === false && <TrendingDown size={10} className="text-loss"  />}
        {positive == null  && <span className="text-[8px] text-text-muted">—</span>}
      </div>
    )
  }

  const W = 40
  const H = 16
  const min = Math.min(...prices)
  const max = Math.max(...prices)
  const range = max - min || 1

  const pts = prices.map((p, i) => {
    const x = (i / (prices.length - 1)) * W
    const y = H - ((p - min) / range) * H
    return `${x},${y}`
  })

  const color = positive === false ? '#ef4444' : '#22c55e'

  return (
    <svg width={W} height={H} className="shrink-0">
      <polyline
        points={pts.join(' ')}
        fill="none"
        stroke={color}
        strokeWidth="1.2"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Search dropdown
// ---------------------------------------------------------------------------

function SearchDialog({ onAdd, onClose }) {
  const [query, setQuery]       = useState('')
  const [results, setResults]   = useState([])
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)
  const debounceRef             = useRef(null)
  const inputRef                = useRef(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleQuery = useCallback((val) => {
    setQuery(val)
    setError(null)
    clearTimeout(debounceRef.current)

    if (!val.trim()) {
      setResults([])
      return
    }

    debounceRef.current = setTimeout(async () => {
      setLoading(true)
      try {
        const data = await searchSymbol(val.trim())
        // OpenAlgo returns array of { symbol, exchange, name } or similar
        const list = Array.isArray(data) ? data : (data?.results ?? data?.data ?? [])
        setResults(list.slice(0, 12))
      } catch (err) {
        setError(err.message || 'Search failed')
        setResults([])
      } finally {
        setLoading(false)
      }
    }, 300)
  }, [])

  // Cleanup debounce on unmount
  useEffect(() => () => clearTimeout(debounceRef.current), [])

  const handleSelect = useCallback((item) => {
    onAdd({ symbol: item.symbol, exchange: item.exchange })
    onClose()
  }, [onAdd, onClose])

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Escape') onClose()
  }, [onClose])

  return (
    <div
      className="absolute inset-0 z-50 flex flex-col bg-surface-base/90 backdrop-blur-sm"
      onKeyDown={handleKeyDown}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-2 py-1.5 border-b border-border-default bg-surface-card shrink-0">
        <Search size={11} className="text-text-muted shrink-0" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => handleQuery(e.target.value)}
          placeholder="Search symbol... e.g. SBIN, TCS"
          className="flex-1 bg-transparent text-xs text-text-primary placeholder-text-muted focus:outline-none"
        />
        <button
          onClick={onClose}
          className="text-text-muted hover:text-text-primary transition-colors"
          aria-label="Close search"
        >
          <X size={11} />
        </button>
      </div>

      {/* Results */}
      <div className="flex-1 overflow-auto">
        {loading && (
          <div className="px-3 py-2 text-[10px] text-text-muted">Searching…</div>
        )}
        {error && !loading && (
          <div className="px-3 py-2 text-[10px] text-loss">{error}</div>
        )}
        {!loading && !error && results.length === 0 && query.trim() && (
          <div className="px-3 py-2 text-[10px] text-text-muted">No results for "{query}"</div>
        )}
        {!loading && !error && results.length === 0 && !query.trim() && (
          <div className="px-3 py-2 text-[10px] text-text-muted">Type to search symbols</div>
        )}
        {results.map((item, idx) => (
          <button
            key={`${item.symbol}-${item.exchange}-${idx}`}
            onClick={() => handleSelect(item)}
            className="w-full flex items-center justify-between px-3 py-1.5 hover:bg-surface-hover text-left transition-colors border-b border-border-subtle"
          >
            <div className="flex flex-col min-w-0">
              <span className="text-xs font-medium text-text-primary font-mono truncate">
                {item.symbol}
              </span>
              {item.name && (
                <span className="text-[10px] text-text-muted truncate">{item.name}</span>
              )}
            </div>
            <span className="text-[10px] text-text-muted ml-2 shrink-0 font-mono">
              {item.exchange}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Context menu (right-click)
// ---------------------------------------------------------------------------

function ContextMenu({ x, y, symbol, onRemove, onClose }) {
  const menuRef = useRef(null)

  useEffect(() => {
    function handle(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) onClose()
    }
    document.addEventListener('mousedown', handle)
    document.addEventListener('contextmenu', handle)
    return () => {
      document.removeEventListener('mousedown', handle)
      document.removeEventListener('contextmenu', handle)
    }
  }, [onClose])

  return (
    <div
      ref={menuRef}
      className="fixed z-50 bg-surface-card border border-border-default rounded shadow-2xl py-1 min-w-36"
      style={{ top: y, left: x }}
    >
      <div className="px-3 py-1 border-b border-border-subtle mb-1">
        <span className="text-[10px] text-text-muted font-mono">{symbol}</span>
      </div>
      <button
        onClick={onRemove}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-[11px] text-loss hover:bg-loss/10 transition-colors"
      >
        <Trash2 size={10} />
        Remove
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Symbol row
// ---------------------------------------------------------------------------

function SymbolRow({ item, quote, sparkPrices, onSelect, onRemove }) {
  const ltp      = quote?.ltp   ?? quote?.close ?? null
  const prevClose = quote?.prev_close ?? quote?.close ?? null
  const chgAbs   = ltp != null && prevClose ? ltp - prevClose : null
  const chgPct   = chgAbs != null && prevClose ? (chgAbs / prevClose) * 100 : null
  const isUp     = chgAbs == null ? null : chgAbs >= 0
  const changeColor = isUp === true ? 'text-profit' : isUp === false ? 'text-loss' : 'text-text-muted'

  return (
    <div
      className="flex items-center gap-1.5 px-2 py-1.5 hover:bg-surface-hover cursor-pointer border-b border-border-subtle transition-colors group"
      onClick={() => onSelect(item)}
      onContextMenu={(e) => {
        e.preventDefault()
        onRemove(e, item)
      }}
      title={`${item.symbol} · ${item.exchange} — right-click to remove`}
    >
      {/* Symbol + Exchange */}
      <div className="flex flex-col min-w-0 flex-1">
        <span className="text-xs font-medium text-text-primary font-mono leading-tight truncate">
          {item.symbol}
        </span>
        <span className="text-[9px] text-text-muted leading-tight">{item.exchange}</span>
      </div>

      {/* Sparkline */}
      <Sparkline prices={sparkPrices} positive={isUp} />

      {/* Price block */}
      <div className="flex flex-col items-end shrink-0 min-w-16">
        <span className="text-xs font-mono font-semibold text-text-primary leading-tight">
          {fmtPrice(ltp)}
        </span>
        <span className={`text-[9px] font-mono leading-tight ${changeColor}`}>
          {chgPct != null ? fmtPct(chgPct) : '—'}
        </span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

export default function WatchlistWidget({ node }) {
  const [watchlist, setWatchlist]       = useState(() => loadWatchlist())
  const [quotes, setQuotes]             = useState({})        // key: "SYMBOL:EXCHANGE"
  const [sparkHistory, setSparkHistory] = useState({})        // key: "SYMBOL:EXCHANGE" → number[]
  const [showSearch, setShowSearch]     = useState(false)
  const [showMenu, setShowMenu]         = useState(false)
  const [contextMenu, setContextMenu]   = useState(null)      // { x, y, item }
  const [fetchError, setFetchError]     = useState(null)
  const pollRef                         = useRef(null)
  const menuRef                         = useRef(null)

  // Persist whenever watchlist changes
  useEffect(() => {
    saveWatchlist(watchlist)
  }, [watchlist])

  // ---------------------------------------------------------------------------
  // Quote polling
  // ---------------------------------------------------------------------------

  const fetchQuotes = useCallback(async () => {
    if (watchlist.length === 0) return

    // getMultiQuotes expects array of { symbol, exchange }
    const symbols = watchlist.map((w) => ({ symbol: w.symbol, exchange: w.exchange }))

    try {
      const data = await getMultiQuotes(symbols)
      setFetchError(null)

      // Normalise response — OpenAlgo multiquotes returns an object keyed by
      // "EXCHANGE:SYMBOL" or an array. Handle both.
      if (Array.isArray(data)) {
        const next = {}
        const histNext = {}

        data.forEach((q, idx) => {
          const item = watchlist[idx]
          if (!item) return
          const key = `${item.symbol}:${item.exchange}`
          next[key] = q
          const ltp = q?.ltp ?? q?.close ?? null
          if (ltp != null) {
            histNext[key] = [
              ...(sparkHistory[key] ?? []).slice(-(SPARK_MAX - 1)),
              Number(ltp),
            ]
          }
        })

        setQuotes((prev) => ({ ...prev, ...next }))
        setSparkHistory((prev) => ({ ...prev, ...histNext }))
      } else if (data && typeof data === 'object') {
        // Object form: keys may be "NSE:SBIN", "SBIN", etc.
        // Try to match by symbol name regardless of key format
        const next = {}
        const histNext = {}

        watchlist.forEach((item) => {
          const key = `${item.symbol}:${item.exchange}`
          // Possible response key patterns
          const q =
            data[key] ??
            data[`${item.exchange}:${item.symbol}`] ??
            data[item.symbol] ??
            null

          if (q) {
            next[key] = q
            const ltp = q?.ltp ?? q?.close ?? null
            if (ltp != null) {
              histNext[key] = [
                ...(sparkHistory[key] ?? []).slice(-(SPARK_MAX - 1)),
                Number(ltp),
              ]
            }
          }
        })

        setQuotes((prev) => ({ ...prev, ...next }))
        setSparkHistory((prev) => ({ ...prev, ...histNext }))
      }
    } catch (err) {
      setFetchError(err.message || 'Quote fetch failed')
    }
  }, [watchlist, sparkHistory])

  // Schedule polling — 5s market hours, 60s off-hours
  useEffect(() => {
    fetchQuotes()

    function schedule() {
      const delay = isMarketHours() ? 5000 : 60000
      pollRef.current = setTimeout(() => {
        fetchQuotes()
        schedule()
      }, delay)
    }

    schedule()
    return () => clearTimeout(pollRef.current)
  }, [fetchQuotes])

  // ---------------------------------------------------------------------------
  // Add / remove symbols
  // ---------------------------------------------------------------------------

  const handleAdd = useCallback((item) => {
    setWatchlist((prev) => {
      const exists = prev.some(
        (w) => w.symbol === item.symbol && w.exchange === item.exchange
      )
      if (exists) return prev
      return [...prev, { symbol: item.symbol, exchange: item.exchange }]
    })
  }, [])

  const handleRemove = useCallback((item) => {
    setWatchlist((prev) =>
      prev.filter((w) => !(w.symbol === item.symbol && w.exchange === item.exchange))
    )
    setContextMenu(null)
  }, [])

  const handleClearAll = useCallback(() => {
    setWatchlist([])
    setShowMenu(false)
  }, [])

  const handleResetDefaults = useCallback(() => {
    setWatchlist(DEFAULT_SYMBOLS)
    setShowMenu(false)
  }, [])

  // ---------------------------------------------------------------------------
  // Context menu (right-click)
  // ---------------------------------------------------------------------------

  const openContextMenu = useCallback((e, item) => {
    e.preventDefault()
    setContextMenu({ x: e.clientX, y: e.clientY, item })
  }, [])

  const closeContextMenu = useCallback(() => setContextMenu(null), [])

  // ---------------------------------------------------------------------------
  // Symbol select → DataBus publish
  // ---------------------------------------------------------------------------

  const handleSelect = useCallback((item) => {
    dataBus.publish('watchlist:select', {
      symbol: item.symbol,
      exchange: item.exchange,
    })
  }, [])

  // ---------------------------------------------------------------------------
  // Close overflow menu on outside click
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (!showMenu) return
    function handle(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) setShowMenu(false)
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [showMenu])

  // ---------------------------------------------------------------------------
  // Derived
  // ---------------------------------------------------------------------------

  const count = watchlist.length

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="h-full flex flex-col bg-surface-base text-text-primary overflow-hidden relative">

      {/* ================================================================
          HEADER
          ================================================================ */}
      <div className="flex items-center gap-1.5 px-2 py-1 border-b border-border-default bg-surface-card shrink-0">
        {/* Title */}
        <span className="text-[10px] font-semibold text-text-secondary uppercase tracking-wider">
          Watchlist
        </span>

        {/* Count badge */}
        {count > 0 && (
          <span className="text-[9px] font-mono bg-surface-hover text-text-muted border border-border-default rounded px-1 leading-4">
            {count}
          </span>
        )}

        {/* Fetch error dot */}
        {fetchError && (
          <span
            title={fetchError}
            className="w-1.5 h-1.5 rounded-full bg-loss shrink-0"
          />
        )}

        <div className="flex-1" />

        {/* Add button */}
        <button
          onClick={() => setShowSearch(true)}
          title="Add symbol"
          className="w-5 h-5 flex items-center justify-center text-text-muted hover:text-text-primary hover:bg-surface-hover rounded transition-colors"
          aria-label="Add symbol"
        >
          <Plus size={11} />
        </button>

        {/* Overflow menu button */}
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setShowMenu((v) => !v)}
            title="More options"
            className="w-5 h-5 flex items-center justify-center text-text-muted hover:text-text-primary hover:bg-surface-hover rounded transition-colors"
            aria-label="More options"
          >
            <MoreVertical size={11} />
          </button>

          {showMenu && (
            <div className="absolute right-0 top-6 z-40 bg-surface-card border border-border-default rounded shadow-2xl py-1 min-w-40">
              <button
                onClick={() => { setShowSearch(true); setShowMenu(false) }}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-[11px] text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
              >
                <Plus size={10} />
                Add symbol
              </button>
              <button
                onClick={handleResetDefaults}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-[11px] text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
              >
                <TrendingUp size={10} />
                Reset to defaults
              </button>
              <div className="border-t border-border-subtle my-1" />
              <button
                onClick={handleClearAll}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-[11px] text-loss hover:bg-loss/10 transition-colors"
              >
                <Trash2 size={10} />
                Clear all
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ================================================================
          SYMBOL LIST
          ================================================================ */}
      <div className="flex-1 overflow-auto">
        {watchlist.length === 0 ? (
          /* Empty state */
          <div className="h-full flex flex-col items-center justify-center gap-3 px-4">
            <TrendingUp size={24} className="text-text-muted" />
            <div className="text-center">
              <p className="text-xs text-text-secondary">Add symbols to your watchlist</p>
              <p className="text-[10px] text-text-muted mt-0.5">Track prices in real-time</p>
            </div>
            <button
              onClick={() => setShowSearch(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-accent/10 hover:bg-accent/20 text-accent border border-accent/30 rounded text-xs font-medium transition-colors"
            >
              <Plus size={11} />
              Add symbol
            </button>
          </div>
        ) : (
          watchlist.map((item) => {
            const key = `${item.symbol}:${item.exchange}`
            return (
              <SymbolRow
                key={key}
                item={item}
                quote={quotes[key] ?? null}
                sparkPrices={sparkHistory[key] ?? []}
                onSelect={handleSelect}
                onRemove={openContextMenu}
              />
            )
          })
        )}
      </div>

      {/* ================================================================
          SEARCH DIALOG (overlaid)
          ================================================================ */}
      {showSearch && (
        <SearchDialog
          onAdd={handleAdd}
          onClose={() => setShowSearch(false)}
        />
      )}

      {/* ================================================================
          CONTEXT MENU
          ================================================================ */}
      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          symbol={contextMenu.item.symbol}
          onRemove={() => handleRemove(contextMenu.item)}
          onClose={closeContextMenu}
        />
      )}
    </div>
  )
}
