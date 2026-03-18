import { useState, useEffect } from 'react'
import { getHoldings } from '../../../services/api'

export default function HoldingsWidget({ node }) {
  const [holdings, setHoldings] = useState([])

  useEffect(() => {
    getHoldings().then(h => setHoldings(Array.isArray(h) ? h : [])).catch(() => {})
  }, [])

  return (
    <div className="h-full flex flex-col overflow-hidden text-xs">
      <div className="px-2 py-1 border-b border-border-default shrink-0">
        <span className="text-text-muted uppercase tracking-wider text-[10px]">Holdings ({holdings.length})</span>
      </div>
      {holdings.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-text-muted">No holdings</div>
      ) : (
        <div className="flex-1 overflow-auto">
          {holdings.map((h, i) => (
            <div key={i} className="flex justify-between px-2 py-1.5 border-b border-border-subtle hover:bg-surface-hover/50">
              <span className="font-mono font-medium">{h.symbol || h.tradingsymbol}</span>
              <span className="font-mono text-text-secondary">{h.quantity} @ ₹{h.average_price}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
