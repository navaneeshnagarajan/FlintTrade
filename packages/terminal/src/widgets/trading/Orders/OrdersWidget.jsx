import { useState, useEffect, useCallback } from 'react'
import { RefreshCw } from 'lucide-react'
import { getOrderbook } from '../../../services/api'

export default function OrdersWidget({ node }) {
  const [orders, setOrders] = useState([])
  const [stats, setStats] = useState(null)

  const fetch = useCallback(async () => {
    try {
      const ob = await getOrderbook()
      setOrders(ob?.orders || [])
      setStats(ob?.statistics || null)
    } catch { setOrders([]) }
  }, [])

  useEffect(() => {
    fetch()
    const id = setInterval(fetch, 10000)
    return () => clearInterval(id)
  }, [fetch])

  return (
    <div className="h-full flex flex-col overflow-hidden text-xs">
      <div className="flex items-center justify-between px-2 py-1 border-b border-border-default shrink-0">
        <span className="text-text-muted uppercase tracking-wider text-[10px]">
          Orders{stats ? ` — ${stats.total_completed_orders || 0} filled` : ''}
        </span>
        <button onClick={fetch} className="text-text-muted hover:text-text-primary">
          <RefreshCw size={12} />
        </button>
      </div>
      {orders.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-text-muted">No orders</div>
      ) : (
        <div className="flex-1 overflow-auto">
          <table className="w-full">
            <thead className="sticky top-0 bg-surface-card">
              <tr className="text-[10px] text-text-muted uppercase tracking-wider">
                <th className="px-2 py-1 text-left">Symbol</th>
                <th className="px-2 py-1 text-center">Side</th>
                <th className="px-2 py-1 text-right">Qty</th>
                <th className="px-2 py-1 text-right">Price</th>
                <th className="px-2 py-1 text-center">Status</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o, i) => (
                <tr key={i} className="border-t border-border-subtle hover:bg-surface-hover/50">
                  <td className="px-2 py-1 font-mono font-medium">{o.symbol}</td>
                  <td className={`px-2 py-1 text-center font-medium ${o.action === 'BUY' ? 'text-profit' : 'text-loss'}`}>{o.action}</td>
                  <td className="px-2 py-1 text-right font-mono">{o.quantity}</td>
                  <td className="px-2 py-1 text-right font-mono">{o.price || 'MKT'}</td>
                  <td className="px-2 py-1 text-center">
                    <span className={`px-1 py-0.5 rounded text-[10px] font-medium ${
                      o.order_status === 'complete' ? 'bg-profit/10 text-profit' :
                      o.order_status === 'rejected' ? 'bg-loss/10 text-loss' :
                      'bg-warning/10 text-warning'
                    }`}>{o.order_status || '—'}</span>
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
