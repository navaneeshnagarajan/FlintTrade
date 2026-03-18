import { useState } from 'react'
import { Star, Plus } from 'lucide-react'

const DEFAULT_SYMBOLS = [
  { symbol: 'NIFTY', exchange: 'NSE_INDEX', name: 'NIFTY 50' },
  { symbol: 'BANKNIFTY', exchange: 'NSE_INDEX', name: 'BANK NIFTY' },
  { symbol: 'SBIN', exchange: 'NSE', name: 'SBI' },
  { symbol: 'RELIANCE', exchange: 'NSE', name: 'Reliance' },
  { symbol: 'TCS', exchange: 'NSE', name: 'TCS' },
  { symbol: 'HDFCBANK', exchange: 'NSE', name: 'HDFC Bank' },
  { symbol: 'INFY', exchange: 'NSE', name: 'Infosys' },
  { symbol: 'ITC', exchange: 'NSE', name: 'ITC' },
]

export default function WatchlistWidget({ node }) {
  const [symbols] = useState(DEFAULT_SYMBOLS)

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex items-center justify-between px-2 py-1 border-b border-border-default shrink-0">
        <div className="flex items-center gap-1">
          <Star size={11} className="text-warning" />
          <span className="text-[10px] text-text-muted uppercase tracking-wider">Watchlist</span>
        </div>
        <button className="text-text-muted hover:text-text-primary">
          <Plus size={12} />
        </button>
      </div>
      <div className="flex-1 overflow-auto">
        {symbols.map(s => (
          <div key={s.symbol} className="flex justify-between items-center py-1.5 px-2 hover:bg-surface-hover cursor-pointer text-xs border-b border-border-subtle">
            <div>
              <span className="text-text-primary font-medium">{s.name}</span>
              <span className="text-text-muted ml-1 text-[10px]">{s.exchange}</span>
            </div>
            <span className="font-mono text-text-secondary">—</span>
          </div>
        ))}
      </div>
    </div>
  )
}
