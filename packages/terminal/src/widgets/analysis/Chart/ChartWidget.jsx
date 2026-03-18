import { useState, useEffect, useRef, useCallback } from 'react'
import { createChart, CandlestickSeries, HistogramSeries } from 'lightweight-charts'
import { Search, X, Minus, TrendingUp, TrendingDown } from 'lucide-react'
import { searchSymbol, getHistory, getQuotes, getIntervals } from '../../../services/api'

// --- constants -----------------------------------------------------------

const DEFAULT_SYMBOL = 'NIFTY'
const DEFAULT_EXCHANGE = 'NSE_INDEX'

const STATIC_INTERVALS = [
  { label: '1m',  value: '1m'  },
  { label: '3m',  value: '3m'  },
  { label: '5m',  value: '5m'  },
  { label: '15m', value: '15m' },
  { label: '30m', value: '30m' },
  { label: '1h',  value: '1h'  },
  { label: '4h',  value: '4h'  },
  { label: '1D',  value: '1D'  },
  { label: '1W',  value: '1W'  },
]

// How many calendar days to look back per interval
const LOOKBACK_DAYS = {
  '1m':  3,
  '3m':  7,
  '5m':  10,
  '15m': 20,
  '30m': 30,
  '1h':  60,
  '4h':  120,
  '1D':  365,
  '1W':  730,
}

// Chart theme — raw hex values intentional (lightweight-charts API, not Tailwind)
const CHART_THEME = {
  layout: {
    background: { color: '#0a0a0a' },
    textColor: '#e5e5e5',
    fontFamily: "'JetBrains Mono', ui-monospace, monospace",
    fontSize: 11,
  },
  localization: { timeZone: 'Asia/Kolkata' },
  grid: {
    vertLines: { color: '#1a1a2e' },
    horzLines: { color: '#1a1a2e' },
  },
  crosshair: { mode: 0 },
  rightPriceScale: { borderColor: '#2a2a3e' },
  timeScale: {
    borderColor: '#2a2a3e',
    timeVisible: true,
    secondsVisible: false,
  },
}

const CANDLE_OPTIONS = {
  upColor: '#22c55e',
  downColor: '#ef4444',
  borderUpColor: '#22c55e',
  borderDownColor: '#ef4444',
  wickUpColor: '#22c55e',
  wickDownColor: '#ef4444',
}

// --- helpers -------------------------------------------------------------

function formatDate(d) {
  return d.toISOString().slice(0, 10)
}

function getStartDate(interval) {
  const d = new Date()
  d.setDate(d.getDate() - (LOOKBACK_DAYS[interval] ?? 30))
  return formatDate(d)
}

function formatPrice(v) {
  if (v == null) return '--'
  return Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatChange(v) {
  if (v == null) return '--'
  const sign = v >= 0 ? '+' : ''
  return `${sign}${Number(v).toFixed(2)}`
}

function formatChangePct(v) {
  if (v == null) return '--'
  const sign = v >= 0 ? '+' : ''
  return `${sign}${Number(v).toFixed(2)}%`
}

function formatVolume(v) {
  if (v == null) return '--'
  if (v >= 1_00_00_000) return `${(v / 1_00_00_000).toFixed(2)}Cr`
  if (v >= 1_00_000)    return `${(v / 1_00_000).toFixed(2)}L`
  if (v >= 1_000)       return `${(v / 1_000).toFixed(1)}K`
  return String(v)
}

// --- sub-components ------------------------------------------------------

function SymbolSearch({ onSelect }) {
  const [query, setQuery]         = useState('')
  const [results, setResults]     = useState([])
  const [open, setOpen]           = useState(false)
  const [loading, setLoading]     = useState(false)
  const [activeIdx, setActiveIdx] = useState(-1)
  const timerRef                  = useRef(null)
  const inputRef                  = useRef(null)
  const dropRef                   = useRef(null)

  // Debounced search
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    if (!query.trim() || query.length < 2) {
      setResults([])
      setOpen(false)
      return
    }
    timerRef.current = setTimeout(async () => {
      setLoading(true)
      try {
        const raw = await searchSymbol(query.trim())
        // OpenAlgo returns array or { data: [...] }
        const list = Array.isArray(raw) ? raw : (raw?.data ?? [])
        setResults(list.slice(0, 12))
        setOpen(list.length > 0)
        setActiveIdx(-1)
      } catch {
        setResults([])
        setOpen(false)
      } finally {
        setLoading(false)
      }
    }, 300)
    return () => clearTimeout(timerRef.current)
  }, [query])

  // Close on outside click
  useEffect(() => {
    function handle(e) {
      if (
        dropRef.current && !dropRef.current.contains(e.target) &&
        inputRef.current && !inputRef.current.contains(e.target)
      ) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [])

  function handleKeyDown(e) {
    if (!open) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx(i => Math.min(i + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter' && activeIdx >= 0) {
      e.preventDefault()
      pick(results[activeIdx])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  function pick(item) {
    setQuery('')
    setOpen(false)
    setResults([])
    onSelect(item)
  }

  function clear() {
    setQuery('')
    setOpen(false)
    setResults([])
    inputRef.current?.focus()
  }

  return (
    <div className="relative flex items-center">
      <div className="flex items-center gap-1 bg-surface-card border border-border-default rounded px-2 py-1 w-52 focus-within:border-accent transition-colors">
        <Search size={12} className="text-text-muted shrink-0" />
        <input
          ref={inputRef}
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => results.length > 0 && setOpen(true)}
          placeholder="Search symbol…"
          className="bg-transparent text-[11px] text-text-primary placeholder-text-muted outline-none w-full font-mono"
          spellCheck={false}
        />
        {loading && (
          <span className="text-text-muted text-[10px] shrink-0 animate-pulse">…</span>
        )}
        {query && !loading && (
          <button onClick={clear} className="text-text-muted hover:text-text-primary transition-colors">
            <X size={11} />
          </button>
        )}
      </div>

      {open && results.length > 0 && (
        <div
          ref={dropRef}
          className="absolute top-full left-0 mt-1 z-50 w-72 bg-surface-card border border-border-default rounded shadow-2xl overflow-hidden"
        >
          {results.map((item, idx) => (
            <button
              key={`${item.symbol}-${item.exchange}-${idx}`}
              onClick={() => pick(item)}
              className={`w-full flex items-center justify-between px-3 py-2 text-left transition-colors ${
                idx === activeIdx
                  ? 'bg-border-default text-text-primary'
                  : 'text-[#a1a1aa] hover:bg-surface-hover hover:text-text-primary'
              }`}
            >
              <span className="flex flex-col gap-0.5">
                <span className="text-[12px] font-mono font-semibold text-text-primary">{item.symbol}</span>
                {item.name && (
                  <span className="text-[10px] text-text-muted truncate max-w-40">{item.name}</span>
                )}
              </span>
              <span className="flex flex-col items-end gap-0.5">
                <span className="text-[10px] font-mono text-accent">{item.exchange}</span>
                {item.instrument_type && (
                  <span className="text-[9px] text-text-muted uppercase">{item.instrument_type}</span>
                )}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function IntervalPills({ intervals, active, onSelect }) {
  return (
    <div className="flex items-center gap-0.5">
      {intervals.map(iv => (
        <button
          key={iv.value}
          onClick={() => onSelect(iv.value)}
          className={`px-2 py-0.5 text-[10px] font-mono rounded transition-colors ${
            active === iv.value
              ? 'bg-accent text-white'
              : 'text-text-secondary hover:text-text-primary hover:bg-border-default'
          }`}
        >
          {iv.label}
        </button>
      ))}
    </div>
  )
}

// --- main component ------------------------------------------------------

export default function ChartWidget({ node }) {
  // symbol / interval state
  const [symbol,    setSymbol]    = useState(DEFAULT_SYMBOL)
  const [exchange,  setExchange]  = useState(DEFAULT_EXCHANGE)
  const [interval,  setInterval]  = useState('5m')
  const [intervals, setIntervals] = useState(STATIC_INTERVALS)

  // quote state (header info)
  const [ltp,       setLtp]       = useState(null)
  const [change,    setChange]    = useState(null)
  const [changePct, setChangePct] = useState(null)

  // crosshair OHLCV legend
  const [legend, setLegend] = useState(null)

  // drawing tools
  const [drawMode, setDrawMode] = useState(null) // 'hline' | null
  const [hlines,   setHlines]   = useState([])   // array of price values
  const hlineSeriesRef = useRef([])

  // chart refs
  const containerRef = useRef(null)
  const chartRef     = useRef(null)
  const candleRef    = useRef(null)
  const volumeRef    = useRef(null)

  // load available intervals from API once
  useEffect(() => {
    getIntervals()
      .then(raw => {
        if (!raw) return
        // Normalise to [{ label, value }]
        let list = []
        if (Array.isArray(raw)) {
          list = raw.map(v => (typeof v === 'string' ? { label: v, value: v } : v))
        } else if (raw.intervals && Array.isArray(raw.intervals)) {
          list = raw.intervals.map(v => (typeof v === 'string' ? { label: v, value: v } : v))
        }
        if (list.length > 0) {
          // Filter to only the static set we support, to maintain pill order
          const apiValues = new Set(list.map(x => x.value))
          const filtered = STATIC_INTERVALS.filter(x => apiValues.has(x.value))
          if (filtered.length > 0) setIntervals(filtered)
        }
      })
      .catch(() => { /* use static fallback */ })
  }, [])

  // --- chart creation (once) -------------------------------------------
  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      ...CHART_THEME,
      width:  containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
    })

    const candleSeries = chart.addSeries(CandlestickSeries, CANDLE_OPTIONS)

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat:  { type: 'volume' },
      priceScaleId: 'vol',
    })
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } })

    chartRef.current  = chart
    candleRef.current = candleSeries
    volumeRef.current = volumeSeries

    // Crosshair OHLCV legend
    chart.subscribeCrosshairMove(param => {
      if (!param || !param.time || !candleSeries) {
        setLegend(null)
        return
      }
      const bar = param.seriesData.get(candleSeries)
      const vol = param.seriesData.get(volumeSeries)
      if (bar) {
        setLegend({
          open:   bar.open,
          high:   bar.high,
          low:    bar.low,
          close:  bar.close,
          volume: vol?.value ?? null,
          bull:   bar.close >= bar.open,
        })
      }
    })

    // ResizeObserver — handles FlexLayout panel resize
    const ro = new ResizeObserver(entries => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect
        chart.applyOptions({ width, height })
      }
    })
    ro.observe(containerRef.current)

    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current        = null
      candleRef.current       = null
      volumeRef.current       = null
      hlineSeriesRef.current  = []
    }
  }, []) // intentionally empty — chart created once

  // Keep drawMode accessible inside the click handler via ref
  const drawModeRef = useRef(drawMode)
  useEffect(() => { drawModeRef.current = drawMode }, [drawMode])

  // Re-subscribe chart click handler whenever drawMode changes so the
  // handler always reads the current value from the ref.
  useEffect(() => {
    const chart  = chartRef.current
    const candle = candleRef.current
    if (!chart || !candle) return

    chart.unsubscribeClick()
    chart.subscribeClick(param => {
      if (!param || !param.point || drawModeRef.current !== 'hline') return
      const price = candle.coordinateToPrice(param.point.y)
      if (price == null) return
      setHlines(prev => [...prev, price])
    })
  }, [drawMode])

  // --- fetch OHLCV data ------------------------------------------------
  useEffect(() => {
    const candle = candleRef.current
    const volume = volumeRef.current
    if (!candle || !volume) return
    let cancelled = false

    ;(async () => {
      try {
        const endDate   = formatDate(new Date())
        const startDate = getStartDate(interval)
        const data = await getHistory(symbol, exchange, interval, startDate, endDate)
        if (cancelled || !Array.isArray(data)) return

        const candles = data.map(b => ({
          time:  Math.floor(new Date(b.timestamp).getTime() / 1000),
          open:  b.open,
          high:  b.high,
          low:   b.low,
          close: b.close,
        }))
        const volumes = data.map(b => ({
          time:  Math.floor(new Date(b.timestamp).getTime() / 1000),
          value: b.volume || 0,
          color: b.close >= b.open ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)',
        }))

        candle.setData(candles)
        volume.setData(volumes)
        chartRef.current?.timeScale().fitContent()
      } catch { /* API unavailable — keep existing data */ }
    })()

    return () => { cancelled = true }
  }, [symbol, exchange, interval])

  // --- fetch quote (LTP / change) --------------------------------------
  useEffect(() => {
    let cancelled = false

    ;(async () => {
      try {
        const q = await getQuotes(symbol, exchange)
        if (cancelled || !q) return
        // OpenAlgo quotes shape: { ltp, open, high, low, close, prev_close, ... }
        const ltpVal    = q.ltp ?? q.last_price ?? null
        const prevClose = q.prev_close ?? q.close ?? null
        const chg       = (ltpVal != null && prevClose != null) ? ltpVal - prevClose : null
        const chgPct    = (chg != null && prevClose)            ? (chg / prevClose) * 100 : null
        if (!cancelled) {
          setLtp(ltpVal)
          setChange(chg)
          setChangePct(chgPct)
        }
      } catch { /* quote unavailable */ }
    })()

    return () => { cancelled = true }
  }, [symbol, exchange])

  // --- live tick updates -----------------------------------------------
  useEffect(() => {
    function onTick(e) {
      const d = e.detail
      if (!d || d.symbol !== symbol || d.exchange !== exchange) return
      if (!d.ltp || !candleRef.current) return

      const now = Math.floor(Date.now() / 1000)
      candleRef.current.update({
        time:  now,
        open:  d.open || d.ltp,
        high:  d.high || d.ltp,
        low:   d.low  || d.ltp,
        close: d.ltp,
      })

      setLtp(d.ltp)
      if (d.change     != null) setChange(d.change)
      if (d.change_pct != null) setChangePct(d.change_pct)
    }
    window.addEventListener('ws:tick', onTick)
    return () => window.removeEventListener('ws:tick', onTick)
  }, [symbol, exchange])

  // --- manage horizontal lines on chart --------------------------------
  useEffect(() => {
    const candle = candleRef.current
    if (!candle) return

    // Remove old price lines
    hlineSeriesRef.current.forEach(ref => {
      try { ref._series.removePriceLine(ref._priceLine) } catch { /* already gone */ }
    })
    hlineSeriesRef.current = []

    // Add one price line per hline using createPriceLine (v5 native API)
    hlines.forEach(price => {
      try {
        const pl = candle.createPriceLine({
          price,
          color:            '#eab308',
          lineWidth:        1,
          lineStyle:        2, // dashed
          axisLabelVisible: true,
          title:            '',
        })
        hlineSeriesRef.current.push({ _priceLine: pl, _series: candle })
      } catch { /* ignore */ }
    })

    return () => {
      hlineSeriesRef.current.forEach(ref => {
        try { ref._series.removePriceLine(ref._priceLine) } catch { /* gone */ }
      })
      hlineSeriesRef.current = []
    }
  }, [hlines])

  // --- event handlers --------------------------------------------------
  const handleSymbolSelect = useCallback(item => {
    setSymbol(item.symbol)
    setExchange(item.exchange)
    setLtp(null)
    setChange(null)
    setChangePct(null)
    setLegend(null)
    setHlines([])
  }, [])

  const handleIntervalChange = useCallback(v => {
    setInterval(v)
  }, [])

  const toggleDrawMode = useCallback(mode => {
    setDrawMode(prev => prev === mode ? null : mode)
  }, [])

  const removeLastHline = useCallback(() => {
    setHlines(prev => prev.slice(0, -1))
  }, [])

  // --- derived display -------------------------------------------------
  const isPositive  = change == null ? null : change >= 0
  const changeColor = change == null
    ? 'text-text-secondary'
    : isPositive ? 'text-profit' : 'text-loss'

  const legendColor = legend
    ? (legend.bull ? 'text-profit' : 'text-loss')
    : 'text-text-primary'

  return (
    <div className="flex flex-col h-full w-full bg-surface-base overflow-hidden">

      {/* ── header row ─────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-2 py-1 bg-surface-base border-b border-border-default shrink-0">

        {/* Left: symbol search + symbol info */}
        <div className="flex items-center gap-3 min-w-0">
          <SymbolSearch onSelect={handleSymbolSelect} />

          {/* Symbol / LTP / change */}
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-[12px] font-mono font-bold text-text-primary leading-none whitespace-nowrap">
              {symbol}
            </span>
            <span className="text-[10px] font-mono text-text-muted whitespace-nowrap">{exchange}</span>
            {ltp != null && (
              <span className="text-[13px] font-mono font-bold text-text-primary leading-none whitespace-nowrap">
                {formatPrice(ltp)}
              </span>
            )}
            {change != null && (
              <span className={`flex items-center gap-0.5 text-[11px] font-mono whitespace-nowrap ${changeColor}`}>
                {isPositive ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
                {formatChange(change)} ({formatChangePct(changePct)})
              </span>
            )}
          </div>
        </div>

        {/* Right: OHLCV legend (crosshair) + interval pills */}
        <div className="flex items-center gap-3 shrink-0">
          {legend && (
            <div className={`flex items-center gap-2 text-[10px] font-mono ${legendColor}`}>
              <span>O <span className="text-text-primary">{formatPrice(legend.open)}</span></span>
              <span>H <span className="text-profit">{formatPrice(legend.high)}</span></span>
              <span>L <span className="text-loss">{formatPrice(legend.low)}</span></span>
              <span>C <span className="text-text-primary">{formatPrice(legend.close)}</span></span>
              {legend.volume != null && (
                <span>V <span className="text-text-secondary">{formatVolume(legend.volume)}</span></span>
              )}
            </div>
          )}
          <IntervalPills
            intervals={intervals}
            active={interval}
            onSelect={handleIntervalChange}
          />
        </div>
      </div>

      {/* ── toolbar ────────────────────────────────────────────────── */}
      <div className="flex items-center gap-1 px-2 py-0.5 bg-surface-base border-b border-border-default shrink-0">
        <span className="text-[9px] text-text-muted uppercase tracking-wider mr-1">Draw</span>

        {/* Horizontal line tool */}
        <button
          onClick={() => toggleDrawMode('hline')}
          title="Horizontal line (click price level on chart)"
          className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] transition-colors ${
            drawMode === 'hline'
              ? 'bg-accent text-white'
              : 'text-text-secondary hover:text-text-primary hover:bg-border-default'
          }`}
        >
          <Minus size={11} />
          <span>H-Line</span>
        </button>

        {/* Remove last line */}
        {hlines.length > 0 && (
          <button
            onClick={removeLastHline}
            title="Remove last horizontal line"
            className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] text-text-secondary hover:text-loss hover:bg-border-default transition-colors"
          >
            <X size={10} />
            <span>Undo</span>
          </button>
        )}

        {drawMode === 'hline' && (
          <span className="text-[9px] text-accent ml-1 animate-pulse">
            Click chart to place line
          </span>
        )}

        {hlines.length > 0 && (
          <span className="text-[9px] text-text-muted ml-auto">
            {hlines.length} line{hlines.length !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* ── chart area ─────────────────────────────────────────────── */}
      <div
        ref={containerRef}
        className="flex-1 w-full min-h-0"
        style={{ cursor: drawMode === 'hline' ? 'crosshair' : 'default' }}
      />
    </div>
  )
}
