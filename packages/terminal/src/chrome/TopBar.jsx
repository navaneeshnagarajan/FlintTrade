import { useState, useEffect } from 'react'
import { Wrench, Grid3x3 } from 'lucide-react'
import { ping } from '../services/api'

function ISTClock() {
  const [time, setTime] = useState('')

  useEffect(() => {
    const tick = () =>
      setTime(
        new Date().toLocaleTimeString('en-IN', {
          timeZone: 'Asia/Kolkata',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false,
        })
      )
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <span className="font-mono text-xs text-text-secondary tabular-nums">
      {time} IST
    </span>
  )
}

/**
 * TopBar — always-visible chrome bar at h-10.
 *
 * Props:
 *   layoutTabs   — array of { id, name }
 *   activeTab    — id of the currently active tab
 *   onTabSelect  — (id) => void
 *   onNewLayout  — () => void
 *   onWidgetPicker — () => void   opens WidgetPicker modal
 *   onToolsMenu  — () => void   toggles ToolsDropdown
 */
export default function TopBar({
  layoutTabs = [],
  activeTab,
  onTabSelect,
  onNewLayout,
  onWidgetPicker,
  onToolsMenu,
}) {
  const [connected, setConnected] = useState(false)
  const [broker, setBroker] = useState('')

  useEffect(() => {
    const check = async () => {
      try {
        const res = await ping()
        setConnected(true)
        setBroker(res?.broker || '')
      } catch {
        setConnected(false)
        setBroker('')
      }
    }
    check()
    const id = setInterval(check, 10000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="h-10 bg-surface-card border-b border-border-default flex items-center justify-between px-3 select-none shrink-0">
      {/* Left: Logo + Layout Tabs */}
      <div className="flex items-center gap-3">
        <span className="text-profit font-bold text-lg tracking-tight leading-none">
          FT
        </span>

        <div className="flex items-center gap-1">
          {layoutTabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => onTabSelect?.(tab.id)}
              className={`px-3 py-1 text-xs rounded transition-colors ${
                tab.id === activeTab
                  ? 'bg-surface-hover text-text-primary'
                  : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'
              }`}
            >
              {tab.name}
            </button>
          ))}

          <button
            onClick={onNewLayout}
            title="New layout"
            className="px-2 py-1 text-xs text-text-muted hover:text-text-primary transition-colors"
          >
            +
          </button>
        </div>
      </div>

      {/* Right: TOOLS + WIDGETS + Connection status + Clock */}
      <div className="flex items-center gap-3">
        <button
          onClick={onToolsMenu}
          className="flex items-center gap-1 text-xs text-text-secondary hover:text-text-primary transition-colors"
        >
          <Wrench size={14} />
          TOOLS
        </button>

        <button
          onClick={onWidgetPicker}
          className="flex items-center gap-1 text-xs text-text-secondary hover:text-text-primary transition-colors"
        >
          <Grid3x3 size={14} />
          WIDGETS
        </button>

        <div className="flex items-center gap-1.5">
          <div
            className={`w-1.5 h-1.5 rounded-full transition-colors ${
              connected ? 'bg-profit' : 'bg-loss'
            }`}
          />
          <span className="text-xs text-text-secondary">
            {connected && broker ? broker : connected ? 'Connected' : 'Disconnected'}
          </span>
        </div>

        <ISTClock />
      </div>
    </div>
  )
}
