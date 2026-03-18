import { useState, useEffect, useCallback } from 'react'
import { Clock, X } from 'lucide-react'
import { getPositionbook, closePosition } from '../../../services/api'

const INR = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 })

function isMarketHours() {
  const now = new Date()
  const ist = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
  const mins = ist.getHours() * 60 + ist.getMinutes()
  const day = ist.getDay()
  if (day === 0 || day === 6) return false
  return mins >= 555 && mins <= 930
}

export default function PositionsWidget({ node }) {
  const [positions, setPositions] = useState([])
  const [lastFetch, setLastFetch] = useState(null)

  const fetch = useCallback(async () => {
    try {
      const p = await getPositionbook()
      setPositions(Array.isArray(p) ? p : [])
      setLastFetch(new Date())
    } catch { setPositions([]) }
  }, [])

  useEffect(() => {
    fetch()
    const ms = isMarketHours() ? 5000 : 60000
    const id = setInterval(fetch, ms)
    return () => clearInterval(id)
  }, [fetch])

  const totalPnl = positions.reduce((s, p) => s + parseFloat(p.pnl || 0), 0)

  return (
    <div className="h-full flex flex-col overflow-hidden text-xs">
      <div className="flex items-center justify-between px-2 py-1 border-b border-border-default shrink-0">
        <span className="text-text-muted uppercase tracking-wider text-[10px]">
          {positions.length} position{positions.length !== 1 ? 's' : ''}
        </span>
        <div className="flex items-center gap-2">
          <span className={`font-mono font-medium ${totalPnl >= 0 ? 'text-profit' : 'text-loss'}`}>
            P&L: {totalPnl >= 0 ? '+' : ''}₹{INR.format(Math.abs(totalPnl))}
          </span>
          {lastFetch && (
            <span className="text-[10px] text-text-muted flex items-center gap-0.5">
              <Clock size={8} />
              {lastFetch.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false })}
            </span>
          )}
        </div>
      </div>
      {positions.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-text-muted">No positions</div>
      ) : (
        <div className="flex-1 overflow-auto">
          <table className="w-full">
            <thead className="sticky top-0 bg-surface-card">
              <tr className="text-[10px] text-text-muted uppercase tracking-wider">
                <th className="px-2 py-1 text-left">Symbol</th>
                <th className="px-2 py-1 text-right">Qty</th>
                <th className="px-2 py-1 text-right">LTP</th>
                <th className="px-2 py-1 text-right">P&L</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p, i) => {
                const pnl = parseFloat(p.pnl || 0)
                const qty = parseInt(p.quantity || 0, 10)
                const ltp = parseFloat(p.ltp || 0)
                return (
                  <tr key={i} className="border-t border-border-subtle hover:bg-surface-hover/50">
                    <td className="px-2 py-1 font-mono font-medium">{p.symbol}</td>
                    <td className={`px-2 py-1 text-right font-mono ${qty > 0 ? 'text-profit' : 'text-loss'}`}>{qty}</td>
                    <td className="px-2 py-1 text-right font-mono text-text-secondary">{INR.format(ltp)}</td>
                    <td className={`px-2 py-1 text-right font-mono font-medium ${pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
                      {pnl >= 0 ? '+' : ''}₹{INR.format(Math.abs(pnl))}
                    </td>
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
