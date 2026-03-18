import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import {
  Zap, ZapOff, Plus, Minus, TrendingUp, TrendingDown,
  ChevronUp, ChevronDown, X, RefreshCw, AlertTriangle,
} from 'lucide-react'
import Chart from '../../../components/Chart'
import {
  placeOrder,
  cancelAllOrders,
  closePosition,
  getPositionbook,
  getExpiry,
  getOptionChain,
  getQuotes,
} from '../../../services/api'
import useWebSocket from '../../../hooks/useWebSocket'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const INDEX_CONFIG = {
  NIFTY:       { exchange: 'NSE_INDEX', optExchange: 'NFO',  lotSize: 75,  step: 50  },
  BANKNIFTY:   { exchange: 'NSE_INDEX', optExchange: 'NFO',  lotSize: 30,  step: 100 },
  FINNIFTY:    { exchange: 'NSE_INDEX', optExchange: 'NFO',  lotSize: 40,  step: 50  },
  MIDCPNIFTY:  { exchange: 'NSE_INDEX', optExchange: 'NFO',  lotSize: 50,  step: 25  },
  SENSEX:      { exchange: 'BSE_INDEX', optExchange: 'BFO',  lotSize: 10,  step: 100 },
  BANKEX:      { exchange: 'BSE_INDEX', optExchange: 'BFO',  lotSize: 15,  step: 100 },
}

const SYMBOLS = Object.keys(INDEX_CONFIG)
const DEFAULT_SYMBOL = 'NIFTY'

// ---------------------------------------------------------------------------
// Tiny helpers
// ---------------------------------------------------------------------------

const fmt2 = (n) => (n == null || isNaN(n) ? '—' : Number(n).toFixed(2))
const fmtInt = (n) => (n == null || isNaN(n) ? '—' : Math.round(n).toLocaleString('en-IN'))

function roundToStrike(price, step) {
  return Math.round(price / step) * step
}

function buildOptionSymbol(base, expiry, strike, type) {
  // NFO format: NIFTY24DEC23000CE  (broker symbol from OpenAlgo)
  // We pass expiry as returned by API (e.g. "24DEC2024"), strip to "24DEC24"
  if (!expiry) return null
  // expiry may arrive as "2024-12-26" or "26DEC2024" — normalise both
  let exp = expiry
  if (exp.includes('-')) {
    const d = new Date(exp)
    const day = String(d.getDate()).padStart(2, '0')
    const mon = d.toLocaleString('en-US', { month: 'short' }).toUpperCase()
    const yr  = String(d.getFullYear()).slice(2)
    exp = `${day}${mon}${yr}`
  }
  return `${base}${exp}${strike}${type}`
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function LtpBlock({ label, symbol, exchange, ticks, className = '' }) {
  const key   = `${exchange}:${symbol}`
  const tick  = ticks[key]
  const ltp   = tick?.ltp ?? tick?.close ?? null
  const close = tick?.prev_close ?? tick?.close ?? null
  const chg   = ltp != null && close ? ltp - close : null
  const pct   = chg != null && close ? (chg / close) * 100 : null
  const up    = chg == null ? null : chg >= 0

  return (
    <div className={`flex items-baseline gap-1.5 ${className}`}>
      <span className="text-[10px] text-text-muted uppercase tracking-wider">{label}</span>
      <span className="font-mono text-xs font-semibold text-text-primary">
        {ltp != null ? fmtInt(ltp) : '—'}
      </span>
      {chg != null && (
        <span className={`font-mono text-[10px] ${up ? 'text-profit' : 'text-loss'}`}>
          {up ? '+' : ''}{fmt2(chg)} ({up ? '+' : ''}{fmt2(pct)}%)
        </span>
      )}
    </div>
  )
}

function Stepper({ label, value, onDec, onInc, className = '' }) {
  return (
    <div className={`flex items-center gap-0 ${className}`}>
      <span className="text-[10px] text-text-muted mr-1 uppercase tracking-wider">{label}</span>
      <button
        onClick={onDec}
        className="w-4 h-5 flex items-center justify-center text-text-muted hover:text-text-primary bg-surface-hover border border-border-default rounded-l hover:bg-surface-card transition-colors"
      >
        <Minus size={8} />
      </button>
      <span className="font-mono text-[10px] text-text-primary bg-surface-hover border-y border-border-default px-1.5 h-5 flex items-center min-w-11 justify-center">
        {value}
      </span>
      <button
        onClick={onInc}
        className="w-4 h-5 flex items-center justify-center text-text-muted hover:text-text-primary bg-surface-hover border border-border-default rounded-r hover:bg-surface-card transition-colors"
      >
        <Plus size={8} />
      </button>
    </div>
  )
}

function NumberInput({ label, value, onChange, min = 0, placeholder, className = '' }) {
  return (
    <div className={`flex items-center gap-1 ${className}`}>
      <span className="text-[10px] text-text-muted uppercase tracking-wider whitespace-nowrap">{label}</span>
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        min={min}
        placeholder={placeholder}
        className="w-14 h-5 bg-surface-hover border border-border-default rounded px-1.5 text-[10px] font-mono text-text-primary focus:outline-none focus:border-accent placeholder-text-muted"
      />
    </div>
  )
}

function ToggleGroup({ value, options, onChange, className = '' }) {
  return (
    <div className={`flex border border-border-default rounded overflow-hidden ${className}`}>
      {options.map((opt) => (
        <button
          key={opt}
          onClick={() => onChange(opt)}
          className={`px-2 h-5 text-[10px] font-medium transition-colors ${
            value === opt
              ? 'bg-accent text-white'
              : 'bg-surface-hover text-text-secondary hover:text-text-primary'
          }`}
        >
          {opt}
        </button>
      ))}
    </div>
  )
}

function StatusPill({ message, type = 'idle' }) {
  if (!message) return null
  const colors = {
    success: 'text-profit bg-profit/10 border-profit/30',
    error:   'text-loss bg-loss/10 border-loss/30',
    pending: 'text-warning bg-warning/10 border-warning/30',
    idle:    'text-text-muted bg-surface-hover border-border-default',
  }
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-mono ${colors[type]}`}>
      {type === 'pending' && <RefreshCw size={8} className="animate-spin" />}
      {type === 'error'   && <AlertTriangle size={8} />}
      {message}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

export default function ScalperWidget({ node }) {
  // --- Config state ---
  const [symbol,    setSymbol]    = useState(DEFAULT_SYMBOL)
  const [lots,      setLots]      = useState(1)
  const [product,   setProduct]   = useState('MIS')
  const [orderType, setOrderType] = useState('MARKET')
  const [sl,        setSl]        = useState('')
  const [target,    setTarget]    = useState('')
  const [oneClick,  setOneClick]  = useState(false)
  const [interval,  setInterval_] = useState('5m')

  // --- Expiry / strike state ---
  const [expiries,    setExpiries]    = useState([])
  const [expiry,      setExpiry]      = useState('')
  const [atmStrike,   setAtmStrike]   = useState(null)
  const [ceOffset,    setCeOffset]    = useState(0)
  const [peOffset,    setPeOffset]    = useState(0)

  // --- Status ---
  const [status, setStatus] = useState({ message: '', type: 'idle' })

  // --- Order confirmation modal for non-one-click ---
  const [pendingOrder, setPendingOrder] = useState(null)

  // --- Focus ---
  const containerRef = useRef(null)
  const [focused, setFocused] = useState(false)

  // Derived config
  const cfg         = INDEX_CONFIG[symbol] ?? INDEX_CONFIG.NIFTY
  const step        = cfg.step
  const lotSize     = cfg.lotSize
  const spotExch    = cfg.exchange
  const optExch     = cfg.optExchange

  // ATM + offsets → CE/PE strikes
  const ceStrike = atmStrike != null ? atmStrike + ceOffset * step : null
  const peStrike = atmStrike != null ? atmStrike + peOffset * step : null

  // Build option symbols
  const ceSymbol = ceStrike ? buildOptionSymbol(symbol, expiry, ceStrike, 'CE') : null
  const peSymbol = peStrike ? buildOptionSymbol(symbol, expiry, peStrike, 'PE') : null

  // WebSocket instruments
  const instruments = useMemo(() => {
    const list = [{ symbol, exchange: spotExch }]
    if (ceSymbol) list.push({ symbol: ceSymbol, exchange: optExch })
    if (peSymbol) list.push({ symbol: peSymbol, exchange: optExch })
    return list
  }, [symbol, spotExch, ceSymbol, peSymbol, optExch])

  const { ticks } = useWebSocket(instruments, 'quote')

  // Spot LTP for ATM calculation
  const spotKey = `${spotExch}:${symbol}`
  const spotTick = ticks[spotKey]
  const spotLtp  = spotTick?.ltp ?? spotTick?.close ?? null

  // ---------------------------------------------------------------------------
  // Fetch expiries on symbol change
  // ---------------------------------------------------------------------------

  useEffect(() => {
    let cancelled = false
    setExpiries([])
    setExpiry('')
    setAtmStrike(null)

    async function fetchExpiries() {
      try {
        const data = await getExpiry(symbol, optExch)
        if (cancelled) return
        // data may be { expiry: [...] } or an array
        const list = Array.isArray(data) ? data : (data?.expiry ?? [])
        setExpiries(list)
        if (list.length > 0) setExpiry(list[0])
      } catch {
        // silently ignore — API may be offline
      }
    }

    fetchExpiries()
    return () => { cancelled = true }
  }, [symbol, optExch])

  // ---------------------------------------------------------------------------
  // Resolve ATM from spot or option chain
  // ---------------------------------------------------------------------------

  // First attempt: derive from spot tick (fast)
  useEffect(() => {
    if (spotLtp != null) {
      setAtmStrike(roundToStrike(spotLtp, step))
    }
  }, [spotLtp, step])

  // Fallback: fetch from API once if tick not yet available
  useEffect(() => {
    if (spotLtp != null || !symbol) return
    let cancelled = false

    async function fetchSpot() {
      try {
        const q = await getQuotes(symbol, spotExch)
        if (cancelled) return
        const ltp = q?.ltp ?? q?.close ?? null
        if (ltp) setAtmStrike(roundToStrike(ltp, step))
      } catch {}
    }

    fetchSpot()
    return () => { cancelled = true }
  }, [symbol, spotExch, spotLtp, step])

  // ---------------------------------------------------------------------------
  // Order execution
  // ---------------------------------------------------------------------------

  const showStatus = useCallback((message, type = 'success', ms = 3000) => {
    setStatus({ message, type })
    if (ms) setTimeout(() => setStatus({ message: '', type: 'idle' }), ms)
  }, [])

  const executeOrder = useCallback(async (sym, exch, action) => {
    if (!sym) { showStatus('Strike not resolved', 'error'); return }
    const qty = lots * lotSize

    const params = {
      symbol:        sym,
      exchange:      exch,
      action,
      quantity:      qty,
      pricetype:     orderType,
      product,
      price:         0,
      disclosed_qty: 0,
      trigger_price: 0,
      strategy:      'FlintScalper',
    }

    showStatus(`${action} ${sym} × ${qty}…`, 'pending', 0)
    try {
      await placeOrder(params)
      showStatus(`${action} ${sym} filled`, 'success')
    } catch (err) {
      showStatus(err.message || 'Order failed', 'error')
    }
  }, [lots, lotSize, orderType, product, showStatus])

  const handleOrder = useCallback((sym, exch, action) => {
    if (oneClick) {
      executeOrder(sym, exch, action)
    } else {
      setPendingOrder({ sym, exch, action })
    }
  }, [oneClick, executeOrder])

  const confirmOrder = useCallback(() => {
    if (pendingOrder) {
      executeOrder(pendingOrder.sym, pendingOrder.exch, pendingOrder.action)
      setPendingOrder(null)
    }
  }, [pendingOrder, executeOrder])

  const handleCloseAll = useCallback(async () => {
    showStatus('Closing all…', 'pending', 0)
    try {
      await closePosition('FlintScalper')
      showStatus('All positions closed', 'success')
    } catch (err) {
      showStatus(err.message || 'Close failed', 'error')
    }
  }, [showStatus])

  const handleCancelAll = useCallback(async () => {
    showStatus('Cancelling…', 'pending', 0)
    try {
      await cancelAllOrders('FlintScalper')
      showStatus('All orders cancelled', 'success')
    } catch (err) {
      showStatus(err.message || 'Cancel failed', 'error')
    }
  }, [showStatus])

  // ---------------------------------------------------------------------------
  // Keyboard shortcuts — only when focused
  // ---------------------------------------------------------------------------

  useEffect(() => {
    const handler = (e) => {
      if (!focused) return
      // Shift + Arrow keys
      if (!e.shiftKey) return
      switch (e.key) {
        case 'ArrowLeft':
          e.preventDefault()
          handleOrder(ceSymbol, optExch, 'SELL')
          break
        case 'ArrowUp':
          e.preventDefault()
          handleOrder(ceSymbol, optExch, 'BUY')
          break
        case 'ArrowRight':
          e.preventDefault()
          handleOrder(peSymbol, optExch, 'SELL')
          break
        case 'ArrowDown':
          e.preventDefault()
          handleOrder(peSymbol, optExch, 'BUY')
          break
        case 'Escape':
          e.preventDefault()
          setPendingOrder(null)
          break
        default:
          break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [focused, ceSymbol, peSymbol, optExch, handleOrder])

  // ---------------------------------------------------------------------------
  // Chart heights — responsive to container
  // ---------------------------------------------------------------------------

  const chartHeight = 120

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      onFocus={() => setFocused(true)}
      onBlur={(e) => {
        if (!containerRef.current?.contains(e.relatedTarget)) setFocused(false)
      }}
      className="h-full flex flex-col bg-surface-base text-text-primary focus:outline-none overflow-hidden"
    >
      {/* ================================================================
          CONFIG BAR — Row 1: Symbol, Expiry, Strikes
          ================================================================ */}
      <div className="shrink-0 border-b border-border-default bg-surface-card">
        <div className="flex items-center gap-2 px-2 py-1 flex-wrap">
          {/* Symbol */}
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-text-muted uppercase tracking-wider">Index</span>
            <select
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              className="h-5 bg-surface-hover border border-border-default rounded px-1 text-[10px] font-mono text-text-primary focus:outline-none focus:border-accent"
            >
              {SYMBOLS.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>

          {/* Expiry */}
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-text-muted uppercase tracking-wider">Exp</span>
            <select
              value={expiry}
              onChange={(e) => setExpiry(e.target.value)}
              className="h-5 bg-surface-hover border border-border-default rounded px-1 text-[10px] font-mono text-text-primary focus:outline-none focus:border-accent"
            >
              {expiries.length === 0
                ? <option value="">loading…</option>
                : expiries.map((ex) => <option key={ex} value={ex}>{ex}</option>)
              }
            </select>
          </div>

          {/* CE Strike */}
          <Stepper
            label="CE"
            value={ceStrike != null ? `${ceStrike}` : '—'}
            onDec={() => setCeOffset((o) => o - 1)}
            onInc={() => setCeOffset((o) => o + 1)}
          />

          {/* PE Strike */}
          <Stepper
            label="PE"
            value={peStrike != null ? `${peStrike}` : '—'}
            onDec={() => setPeOffset((o) => o - 1)}
            onInc={() => setPeOffset((o) => o + 1)}
          />

          {/* Spacer */}
          <div className="flex-1" />

          {/* Status pill */}
          <StatusPill message={status.message} type={status.type} />

          {/* Keyboard hint */}
          {focused && (
            <span className="text-[9px] text-text-muted border border-border-subtle rounded px-1 py-0.5 hidden lg:block">
              Shift+↑↓←→ to trade
            </span>
          )}
        </div>

        {/* Row 2: Qty, Product, OrderType, SL, Target, One-click */}
        <div className="flex items-center gap-2 px-2 py-1 border-t border-border-subtle flex-wrap">
          {/* Lots */}
          <Stepper
            label={`Lot ×${lotSize}`}
            value={`${lots} (${lots * lotSize})`}
            onDec={() => setLots((l) => Math.max(1, l - 1))}
            onInc={() => setLots((l) => l + 1)}
          />

          {/* Product */}
          <ToggleGroup
            value={product}
            options={['MIS', 'NRML']}
            onChange={setProduct}
          />

          {/* Order type */}
          <ToggleGroup
            value={orderType}
            options={['MARKET', 'LIMIT']}
            onChange={setOrderType}
          />

          {/* Interval */}
          <ToggleGroup
            value={interval}
            options={['1m', '3m', '5m', '15m']}
            onChange={setInterval_}
          />

          {/* SL */}
          <NumberInput
            label="SL"
            value={sl}
            onChange={setSl}
            min={0}
            placeholder="pts"
          />

          {/* Target */}
          <NumberInput
            label="Tgt"
            value={target}
            onChange={setTarget}
            min={0}
            placeholder="pts"
          />

          {/* Spacer */}
          <div className="flex-1" />

          {/* One-click toggle */}
          <button
            onClick={() => setOneClick((v) => !v)}
            title={oneClick ? 'One-click ON — click to disable' : 'One-click OFF — click to enable'}
            className={`flex items-center gap-1 px-2 h-5 rounded border text-[10px] font-medium transition-colors ${
              oneClick
                ? 'bg-warning/20 border-warning/60 text-warning'
                : 'bg-surface-hover border-border-default text-text-muted hover:text-text-primary'
            }`}
          >
            {oneClick ? <Zap size={10} /> : <ZapOff size={10} />}
            {oneClick ? '1-CLICK ON' : '1-CLICK'}
          </button>
        </div>
      </div>

      {/* ================================================================
          3-PANEL MAIN AREA
          ================================================================ */}
      <div className="flex-1 flex min-h-0 overflow-hidden">

        {/* ---- CE PANEL ---- */}
        <div className="flex flex-col border-r border-border-default" style={{ width: '28%', minWidth: 0 }}>
          {/* CE header */}
          <div className="shrink-0 px-2 py-1 bg-surface-card border-b border-border-subtle">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-mono text-text-muted uppercase tracking-wider">
                {ceSymbol ?? `${symbol} CE`}
              </span>
              <span className="text-[9px] text-text-muted">CALL</span>
            </div>
            <LtpBlock
              label="LTP"
              symbol={ceSymbol ?? ''}
              exchange={optExch}
              ticks={ticks}
            />
          </div>

          {/* CE Chart */}
          <div className="flex-1 overflow-hidden min-h-0">
            {ceSymbol ? (
              <Chart
                symbol={ceSymbol}
                exchange={optExch}
                interval={interval}
                height={chartHeight}
                className="h-full"
              />
            ) : (
              <div className="h-full flex items-center justify-center text-[10px] text-text-muted">
                Select expiry
              </div>
            )}
          </div>

          {/* CE action buttons */}
          <div className="shrink-0 flex border-t border-border-default">
            <button
              onClick={() => handleOrder(ceSymbol, optExch, 'SELL')}
              disabled={!ceSymbol}
              title="Sell CE (Shift+←)"
              className="flex-1 flex items-center justify-center gap-1 py-1.5 bg-loss/10 hover:bg-loss/20 text-loss text-[11px] font-semibold border-r border-border-subtle transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <TrendingDown size={11} />
              Sell CE
              <span className="text-[9px] opacity-60 ml-0.5">S+←</span>
            </button>
            <button
              onClick={() => handleOrder(ceSymbol, optExch, 'BUY')}
              disabled={!ceSymbol}
              title="Buy CE (Shift+↑)"
              className="flex-1 flex items-center justify-center gap-1 py-1.5 bg-profit/10 hover:bg-profit/20 text-profit text-[11px] font-semibold transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <TrendingUp size={11} />
              Buy CE
              <span className="text-[9px] opacity-60 ml-0.5">S+↑</span>
            </button>
          </div>
        </div>

        {/* ---- SPOT PANEL ---- */}
        <div className="flex flex-col" style={{ width: '44%', minWidth: 0 }}>
          {/* Spot header */}
          <div className="shrink-0 px-2 py-1 bg-surface-card border-b border-border-subtle">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-mono font-semibold text-text-primary uppercase tracking-wider">
                {symbol}
              </span>
              <span className="text-[9px] text-text-muted">{spotExch}</span>
            </div>
            <LtpBlock
              label="SPOT"
              symbol={symbol}
              exchange={spotExch}
              ticks={ticks}
            />
            {atmStrike != null && (
              <div className="flex items-center gap-1 mt-0.5">
                <span className="text-[9px] text-text-muted">ATM</span>
                <span className="font-mono text-[10px] text-accent">{fmtInt(atmStrike)}</span>
              </div>
            )}
          </div>

          {/* Spot Chart */}
          <div className="flex-1 overflow-hidden min-h-0">
            <Chart
              symbol={symbol}
              exchange={spotExch}
              interval={interval}
              height={chartHeight}
              className="h-full"
            />
          </div>

          {/* Centre control buttons */}
          <div className="shrink-0 flex border-t border-border-default">
            <button
              onClick={handleCloseAll}
              title="Close all positions (F6)"
              className="flex-1 flex items-center justify-center gap-1 py-1.5 bg-warning/10 hover:bg-warning/20 text-warning text-[11px] font-semibold border-r border-border-subtle transition-colors"
            >
              <X size={11} />
              Close All
              <span className="text-[9px] opacity-60 ml-0.5">F6</span>
            </button>
            <button
              onClick={handleCancelAll}
              title="Cancel all orders (F7)"
              className="flex-1 flex items-center justify-center gap-1 py-1.5 bg-surface-hover hover:bg-surface-card text-text-secondary text-[11px] font-semibold transition-colors"
            >
              <RefreshCw size={11} />
              Cancel All
              <span className="text-[9px] opacity-60 ml-0.5">F7</span>
            </button>
          </div>
        </div>

        {/* ---- PE PANEL ---- */}
        <div className="flex flex-col border-l border-border-default" style={{ width: '28%', minWidth: 0 }}>
          {/* PE header */}
          <div className="shrink-0 px-2 py-1 bg-surface-card border-b border-border-subtle">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-mono text-text-muted uppercase tracking-wider">
                {peSymbol ?? `${symbol} PE`}
              </span>
              <span className="text-[9px] text-text-muted">PUT</span>
            </div>
            <LtpBlock
              label="LTP"
              symbol={peSymbol ?? ''}
              exchange={optExch}
              ticks={ticks}
            />
          </div>

          {/* PE Chart */}
          <div className="flex-1 overflow-hidden min-h-0">
            {peSymbol ? (
              <Chart
                symbol={peSymbol}
                exchange={optExch}
                interval={interval}
                height={chartHeight}
                className="h-full"
              />
            ) : (
              <div className="h-full flex items-center justify-center text-[10px] text-text-muted">
                Select expiry
              </div>
            )}
          </div>

          {/* PE action buttons */}
          <div className="shrink-0 flex border-t border-border-default">
            <button
              onClick={() => handleOrder(peSymbol, optExch, 'BUY')}
              disabled={!peSymbol}
              title="Buy Put (Shift+↓)"
              className="flex-1 flex items-center justify-center gap-1 py-1.5 bg-profit/10 hover:bg-profit/20 text-profit text-[11px] font-semibold border-r border-border-subtle transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <TrendingUp size={11} />
              Buy PE
              <span className="text-[9px] opacity-60 ml-0.5">S+↓</span>
            </button>
            <button
              onClick={() => handleOrder(peSymbol, optExch, 'SELL')}
              disabled={!peSymbol}
              title="Sell Put (Shift+→)"
              className="flex-1 flex items-center justify-center gap-1 py-1.5 bg-loss/10 hover:bg-loss/20 text-loss text-[11px] font-semibold transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <TrendingDown size={11} />
              Sell PE
              <span className="text-[9px] opacity-60 ml-0.5">S+→</span>
            </button>
          </div>
        </div>
      </div>

      {/* ================================================================
          ORDER CONFIRMATION MODAL (non-one-click)
          ================================================================ */}
      {pendingOrder && (
        <div className="absolute inset-0 flex items-center justify-center bg-surface-base/80 backdrop-blur-sm z-50">
          <div className="bg-surface-card border border-border-default rounded-lg p-4 min-w-60 shadow-2xl">
            <div className="text-xs font-semibold text-text-primary mb-3">Confirm Order</div>
            <div className="space-y-1 mb-4">
              <div className="flex justify-between text-[11px]">
                <span className="text-text-muted">Symbol</span>
                <span className="font-mono text-text-primary">{pendingOrder.sym}</span>
              </div>
              <div className="flex justify-between text-[11px]">
                <span className="text-text-muted">Action</span>
                <span className={`font-semibold ${pendingOrder.action === 'BUY' ? 'text-profit' : 'text-loss'}`}>
                  {pendingOrder.action}
                </span>
              </div>
              <div className="flex justify-between text-[11px]">
                <span className="text-text-muted">Qty</span>
                <span className="font-mono text-text-primary">{lots * lotSize} ({lots} lot{lots > 1 ? 's' : ''})</span>
              </div>
              <div className="flex justify-between text-[11px]">
                <span className="text-text-muted">Product</span>
                <span className="font-mono text-text-primary">{product} · {orderType}</span>
              </div>
              {sl && (
                <div className="flex justify-between text-[11px]">
                  <span className="text-text-muted">SL</span>
                  <span className="font-mono text-loss">{sl} pts</span>
                </div>
              )}
              {target && (
                <div className="flex justify-between text-[11px]">
                  <span className="text-text-muted">Target</span>
                  <span className="font-mono text-profit">{target} pts</span>
                </div>
              )}
            </div>
            <div className="flex gap-2">
              <button
                onClick={confirmOrder}
                className={`flex-1 py-1.5 rounded text-[11px] font-semibold transition-colors ${
                  pendingOrder.action === 'BUY'
                    ? 'bg-profit hover:bg-profit/80 text-white'
                    : 'bg-loss hover:bg-loss/80 text-white'
                }`}
              >
                Confirm {pendingOrder.action}
              </button>
              <button
                onClick={() => setPendingOrder(null)}
                className="flex-1 py-1.5 rounded text-[11px] font-medium bg-surface-hover hover:bg-surface-card text-text-secondary border border-border-default transition-colors"
              >
                Cancel (Esc)
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
