/**
 * OrderPadWidget — standalone order entry pad for FlintTrade terminal.
 *
 * Features:
 *   - Debounced symbol search with autocomplete dropdown (searchSymbol API)
 *   - Exchange badge on selected symbol
 *   - Order type pills: MARKET | LIMIT | SL | SL-M
 *   - Transaction toggle: BUY (green) / SELL (red)
 *   - Product type pills: MIS | NRML | CNC
 *   - Quantity with +/- lot stepper
 *   - Price input (enabled only for LIMIT / SL)
 *   - Trigger Price input (enabled only for SL / SL-M)
 *   - Disclosed Qty optional input
 *   - Place Order button — color matches action, shows spinner while pending
 *   - Success / error toast after placement
 *   - Default: NIFTY, NSE, BUY, MIS, MARKET, qty 1
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Search, X, Plus, Minus, Loader2, CheckCircle2, AlertCircle, FileEdit,
} from 'lucide-react'
import { searchSymbol, placeOrder } from '../../../services/api'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ORDER_TYPES   = ['MARKET', 'LIMIT', 'SL', 'SL-M']
const PRODUCT_TYPES = ['MIS', 'NRML', 'CNC']

const PRICE_ENABLED   = new Set(['LIMIT', 'SL'])
const TRIGGER_ENABLED = new Set(['SL', 'SL-M'])

const DEBOUNCE_MS = 300

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isMarketHours() {
  const now = new Date()
  const ist = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
  const day = ist.getDay()
  if (day === 0 || day === 6) return false
  const mins = ist.getHours() * 60 + ist.getMinutes()
  return mins >= 555 && mins <= 930
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Pill toggle group — single selection from options array. */
function PillGroup({ value, options, onChange, className = '' }) {
  return (
    <div className={`flex border border-border-default rounded overflow-hidden ${className}`}>
      {options.map((opt) => (
        <button
          key={opt}
          type="button"
          onClick={() => onChange(opt)}
          className={`flex-1 h-6 text-[11px] font-medium transition-colors ${
            value === opt
              ? 'bg-accent text-white'
              : 'bg-surface-hover text-text-secondary hover:text-text-primary hover:bg-surface-card'
          }`}
        >
          {opt}
        </button>
      ))}
    </div>
  )
}

/** A number input with inline +/- step buttons. */
function StepInput({ label, value, onChange, min = 0, step = 1, disabled = false, placeholder = '' }) {
  function dec() {
    const n = parseFloat(value) || 0
    const next = Math.max(min, n - step)
    onChange(String(next))
  }
  function inc() {
    const n = parseFloat(value) || 0
    onChange(String(n + step))
  }

  return (
    <div className="flex flex-col gap-0.5">
      <label className="text-[10px] text-text-muted uppercase tracking-wider">{label}</label>
      <div className="flex items-stretch h-7">
        <button
          type="button"
          onClick={dec}
          disabled={disabled}
          className="w-7 flex items-center justify-center bg-surface-hover border border-r-0 border-border-default rounded-l text-text-muted hover:text-text-primary hover:bg-surface-card transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Minus size={10} />
        </button>
        <input
          type="number"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          min={min}
          step={step}
          placeholder={placeholder}
          className="flex-1 min-w-0 bg-surface-hover border-y border-border-default px-2 text-[12px] font-mono text-text-primary text-center focus:outline-none focus:border-accent disabled:opacity-40 disabled:cursor-not-allowed placeholder-text-muted"
        />
        <button
          type="button"
          onClick={inc}
          disabled={disabled}
          className="w-7 flex items-center justify-center bg-surface-hover border border-l-0 border-border-default rounded-r text-text-muted hover:text-text-primary hover:bg-surface-card transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Plus size={10} />
        </button>
      </div>
    </div>
  )
}

/** Plain labelled number input (no stepper). */
function NumField({ label, value, onChange, disabled = false, placeholder = '' }) {
  return (
    <div className="flex flex-col gap-0.5">
      <label className="text-[10px] text-text-muted uppercase tracking-wider">{label}</label>
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        placeholder={placeholder}
        className="h-7 w-full bg-surface-hover border border-border-default rounded px-2 text-[12px] font-mono text-text-primary focus:outline-none focus:border-accent disabled:opacity-30 disabled:cursor-not-allowed placeholder-text-muted transition-colors"
      />
    </div>
  )
}

/** Exchange badge pill. */
function ExchangeBadge({ exchange }) {
  return (
    <span className="px-1.5 py-0.5 text-[9px] font-semibold rounded bg-accent/10 border border-accent/20 text-accent uppercase tracking-wider">
      {exchange}
    </span>
  )
}

/** Toast notification at the bottom of the pad. */
function Toast({ msg }) {
  if (!msg) return null
  const ok = msg.type === 'success'
  return (
    <div className={`flex items-center gap-2 px-3 py-2 text-xs border-t ${
      ok
        ? 'bg-profit/10 border-profit/20 text-profit'
        : 'bg-loss/10 border-loss/20 text-loss'
    }`}>
      {ok ? <CheckCircle2 size={13} /> : <AlertCircle size={13} />}
      <span className="flex-1 leading-tight">{msg.text}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

export default function OrderPadWidget({ node }) {
  // ── symbol search ──
  const [query,       setQuery]       = useState('NIFTY')
  const [symbol,      setSymbol]      = useState('NIFTY')
  const [exchange,    setExchange]    = useState('NSE')
  const [suggestions, setSuggestions] = useState([])
  const [searchOpen,  setSearchOpen]  = useState(false)
  const [searching,   setSearching]   = useState(false)

  // ── order fields ──
  const [action,      setAction]      = useState('BUY')
  const [orderType,   setOrderType]   = useState('MARKET')
  const [product,     setProduct]     = useState('MIS')
  const [qty,         setQty]         = useState('1')
  const [price,       setPrice]       = useState('')
  const [trigPrice,   setTrigPrice]   = useState('')
  const [discQty,     setDiscQty]     = useState('')

  // ── submission ──
  const [loading,  setLoading]  = useState(false)
  const [toast,    setToast]    = useState(null)  // { type: 'success'|'error', text: string }

  const searchRef  = useRef(null)
  const debounceRef = useRef(null)

  // Derived flags
  const priceEnabled   = PRICE_ENABLED.has(orderType)
  const triggerEnabled = TRIGGER_ENABLED.has(orderType)

  // ── close dropdown on outside click ──
  useEffect(() => {
    function onOutside(e) {
      if (searchRef.current && !searchRef.current.contains(e.target)) {
        setSearchOpen(false)
      }
    }
    document.addEventListener('mousedown', onOutside)
    return () => document.removeEventListener('mousedown', onOutside)
  }, [])

  // ── debounced symbol search ──
  useEffect(() => {
    clearTimeout(debounceRef.current)
    const q = query.trim()
    if (!q || q === symbol) {
      setSuggestions([])
      setSearchOpen(false)
      return
    }

    debounceRef.current = setTimeout(async () => {
      setSearching(true)
      try {
        const result = await searchSymbol(q)
        // result may be an array or { data: [...] }
        const list = Array.isArray(result) ? result : (result?.data ?? result?.results ?? [])
        setSuggestions(list.slice(0, 8))
        setSearchOpen(list.length > 0)
      } catch {
        setSuggestions([])
        setSearchOpen(false)
      } finally {
        setSearching(false)
      }
    }, DEBOUNCE_MS)

    return () => clearTimeout(debounceRef.current)
  }, [query, symbol])

  // Clear price/trigger when order type changes to non-requiring types
  useEffect(() => {
    if (!priceEnabled)   setPrice('')
    if (!triggerEnabled) setTrigPrice('')
  }, [orderType, priceEnabled, triggerEnabled])

  // ── select a suggestion ──
  const handleSelect = useCallback((item) => {
    // OpenAlgo search returns objects like { symbol, exchange, name, ... }
    const sym  = item.symbol ?? item.ticker ?? item.tradingsymbol ?? item
    const exch = item.exchange ?? item.exch_seg ?? 'NSE'
    setSymbol(sym)
    setExchange(exch)
    setQuery(sym)
    setSuggestions([])
    setSearchOpen(false)
  }, [])

  // ── clear symbol search ──
  const handleClearSearch = useCallback(() => {
    setQuery('')
    setSuggestions([])
    setSearchOpen(false)
  }, [])

  // ── show toast and auto-dismiss ──
  const showToast = useCallback((type, text, ms = 4000) => {
    setToast({ type, text })
    setTimeout(() => setToast(null), ms)
  }, [])

  // ── place order ──
  const handleSubmit = useCallback(async (e) => {
    e.preventDefault()
    const quantity = parseInt(qty, 10)
    if (!symbol || !quantity || quantity < 1) {
      showToast('error', 'Invalid symbol or quantity')
      return
    }

    const params = {
      strategy:           'FlintOrderPad',
      symbol,
      exchange,
      action,
      product,
      pricetype:          orderType,
      quantity,
      price:              priceEnabled   ? parseFloat(price)    || 0 : 0,
      trigger_price:      triggerEnabled ? parseFloat(trigPrice) || 0 : 0,
      disclosed_quantity: discQty ? parseInt(discQty, 10) : 0,
    }

    setLoading(true)
    try {
      const result = await placeOrder(params)
      const orderId = result?.orderid ?? result?.order_id ?? ''
      showToast('success', `Order placed${orderId ? ` · ID: ${orderId}` : ''}`)
    } catch (err) {
      showToast('error', err.message || 'Order failed')
    } finally {
      setLoading(false)
    }
  }, [
    symbol, exchange, action, product, orderType, qty,
    price, trigPrice, discQty, priceEnabled, triggerEnabled, showToast,
  ])

  // ── button appearance ──
  const isBuy = action === 'BUY'
  const btnBase = 'flex items-center justify-center gap-2 w-full h-9 rounded font-semibold text-sm transition-colors disabled:opacity-60 disabled:cursor-not-allowed'
  const btnColor = isBuy
    ? 'bg-profit hover:bg-profit/85 active:bg-profit/70 text-white'
    : 'bg-loss hover:bg-loss/85 active:bg-loss/70 text-white'

  return (
    <div className="h-full flex flex-col bg-surface-base text-text-primary overflow-hidden">

      {/* ── Header ── */}
      <div className="flex-none bg-surface-card border-b border-border-default px-3 py-2 flex items-center gap-2">
        <FileEdit size={13} className="text-accent shrink-0" />
        <span className="text-xs font-semibold text-text-primary uppercase tracking-wider">Order Pad</span>
        {isMarketHours() && (
          <span className="ml-auto text-[9px] px-1.5 py-0.5 rounded bg-profit/10 border border-profit/20 text-profit font-medium">
            MARKET OPEN
          </span>
        )}
      </div>

      {/* ── Form body ── */}
      <form
        onSubmit={handleSubmit}
        className="flex-1 flex flex-col gap-3 px-3 py-3 overflow-y-auto"
      >
        {/* Symbol search */}
        <div className="flex flex-col gap-0.5" ref={searchRef}>
          <label className="text-[10px] text-text-muted uppercase tracking-wider">Symbol</label>
          <div className="relative">
            <div className="flex items-center gap-1.5 h-8 bg-surface-hover border border-border-default rounded px-2 focus-within:border-accent transition-colors">
              <Search size={12} className="text-text-muted shrink-0" />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value.toUpperCase())}
                onFocus={() => query !== symbol && suggestions.length > 0 && setSearchOpen(true)}
                placeholder="Search symbol…"
                className="flex-1 bg-transparent text-[12px] font-mono text-text-primary focus:outline-none placeholder-text-muted"
                autoComplete="off"
                spellCheck={false}
              />
              {searching && <Loader2 size={11} className="text-text-muted animate-spin shrink-0" />}
              {query && !searching && (
                <button type="button" onClick={handleClearSearch} className="text-text-muted hover:text-text-primary transition-colors">
                  <X size={11} />
                </button>
              )}
              <ExchangeBadge exchange={exchange} />
            </div>

            {/* Autocomplete dropdown */}
            {searchOpen && suggestions.length > 0 && (
              <div className="absolute top-full left-0 right-0 mt-0.5 z-50 bg-surface-card border border-border-default rounded shadow-xl overflow-hidden">
                {suggestions.map((item, idx) => {
                  const sym  = item.symbol ?? item.ticker ?? item.tradingsymbol ?? String(item)
                  const exch = item.exchange ?? item.exch_seg ?? ''
                  const name = item.name ?? item.company_name ?? ''
                  return (
                    <button
                      key={`${sym}-${idx}`}
                      type="button"
                      onClick={() => handleSelect(item)}
                      className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-surface-hover transition-colors"
                    >
                      <span className="font-mono text-xs text-text-primary font-medium">{sym}</span>
                      {exch && <ExchangeBadge exchange={exch} />}
                      {name && <span className="text-[10px] text-text-muted truncate">{name}</span>}
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        {/* BUY / SELL toggle */}
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setAction('BUY')}
            className={`flex-1 h-8 rounded font-semibold text-sm transition-colors border ${
              action === 'BUY'
                ? 'bg-profit/15 border-profit/50 text-profit'
                : 'bg-surface-hover border-border-default text-text-secondary hover:text-text-primary'
            }`}
          >
            BUY
          </button>
          <button
            type="button"
            onClick={() => setAction('SELL')}
            className={`flex-1 h-8 rounded font-semibold text-sm transition-colors border ${
              action === 'SELL'
                ? 'bg-loss/15 border-loss/50 text-loss'
                : 'bg-surface-hover border-border-default text-text-secondary hover:text-text-primary'
            }`}
          >
            SELL
          </button>
        </div>

        {/* Order type */}
        <div className="flex flex-col gap-0.5">
          <label className="text-[10px] text-text-muted uppercase tracking-wider">Order Type</label>
          <PillGroup value={orderType} options={ORDER_TYPES} onChange={setOrderType} />
        </div>

        {/* Product type */}
        <div className="flex flex-col gap-0.5">
          <label className="text-[10px] text-text-muted uppercase tracking-wider">Product</label>
          <PillGroup value={product} options={PRODUCT_TYPES} onChange={setProduct} />
        </div>

        {/* Qty + Price row */}
        <div className="grid grid-cols-2 gap-3">
          <StepInput
            label="Quantity"
            value={qty}
            onChange={setQty}
            min={1}
            step={1}
          />
          <NumField
            label="Price"
            value={price}
            onChange={setPrice}
            disabled={!priceEnabled}
            placeholder={priceEnabled ? '0.00' : 'N/A'}
          />
        </div>

        {/* Trigger + Disclosed row */}
        <div className="grid grid-cols-2 gap-3">
          <NumField
            label="Trigger Price"
            value={trigPrice}
            onChange={setTrigPrice}
            disabled={!triggerEnabled}
            placeholder={triggerEnabled ? '0.00' : 'N/A'}
          />
          <NumField
            label="Disclosed Qty"
            value={discQty}
            onChange={setDiscQty}
            placeholder="Optional"
          />
        </div>

        {/* Order summary preview */}
        <div className="rounded border border-border-default bg-surface-card px-3 py-2 space-y-1">
          <div className="flex justify-between text-[11px]">
            <span className="text-text-muted">Symbol</span>
            <span className="font-mono text-text-primary font-semibold">{symbol}</span>
          </div>
          <div className="flex justify-between text-[11px]">
            <span className="text-text-muted">Exchange</span>
            <span className="font-mono text-text-primary">{exchange}</span>
          </div>
          <div className="flex justify-between text-[11px]">
            <span className="text-text-muted">Action</span>
            <span className={`font-semibold ${isBuy ? 'text-profit' : 'text-loss'}`}>{action}</span>
          </div>
          <div className="flex justify-between text-[11px]">
            <span className="text-text-muted">Qty / Product</span>
            <span className="font-mono text-text-primary">{qty} · {product}</span>
          </div>
          <div className="flex justify-between text-[11px]">
            <span className="text-text-muted">Type</span>
            <span className="font-mono text-text-primary">{orderType}</span>
          </div>
          {priceEnabled && price && (
            <div className="flex justify-between text-[11px]">
              <span className="text-text-muted">Price</span>
              <span className="font-mono text-text-primary">{price}</span>
            </div>
          )}
          {triggerEnabled && trigPrice && (
            <div className="flex justify-between text-[11px]">
              <span className="text-text-muted">Trigger</span>
              <span className="font-mono text-text-primary">{trigPrice}</span>
            </div>
          )}
        </div>

        {/* Submit button */}
        <button
          type="submit"
          disabled={loading || !symbol || !qty}
          className={`${btnBase} ${btnColor}`}
        >
          {loading ? (
            <Loader2 size={15} className="animate-spin" />
          ) : null}
          {loading ? 'Placing…' : `Place ${action} Order`}
        </button>
      </form>

      {/* ── Toast ── */}
      <Toast msg={toast} />
    </div>
  )
}
