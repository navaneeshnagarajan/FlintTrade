import { useRef, useEffect } from 'react'
import { PieChart, Brain, BarChart3, FlaskConical, Workflow, BookOpen, Settings } from 'lucide-react'

/**
 * Full-page tools available from the TOOLS button in TopBar.
 * Each tool replaces the FlexLayout canvas when selected.
 */
const TOOLS = [
  { id: 'pnl-dashboard', name: 'P&L Dashboard', icon: PieChart },
  { id: 'strategy-builder', name: 'Strategy Builder', icon: Brain },
  { id: 'market-intelligence', name: 'Market Intelligence', icon: BarChart3 },
  { id: 'backtest-lab', name: 'Backtest Lab', icon: FlaskConical },
  { id: 'flow-builder', name: 'Flow Builder', icon: Workflow },
  { id: 'trade-journal', name: 'Trade Journal', icon: BookOpen },
  { id: 'settings', name: 'Settings', icon: Settings },
]

/**
 * ToolsDropdown — absolute-positioned dropdown listing full-page tools.
 *
 * Props:
 *   isOpen       — boolean, controls visibility
 *   onClose      — () => void
 *   onSelectTool — (toolId: string) => void
 *
 * Closes when clicking outside the panel (mousedown listener).
 * Positioned right-24 top-10 to sit beneath the TOOLS button in TopBar.
 */
export default function ToolsDropdown({ isOpen, onClose, onSelectTool }) {
  const ref = useRef(null)

  useEffect(() => {
    if (!isOpen) return
    const handleMouseDown = (e) => {
      if (ref.current && !ref.current.contains(e.target)) {
        onClose?.()
      }
    }
    document.addEventListener('mousedown', handleMouseDown)
    return () => document.removeEventListener('mousedown', handleMouseDown)
  }, [isOpen, onClose])

  if (!isOpen) return null

  return (
    <div
      ref={ref}
      className="absolute right-24 top-10 z-40 bg-surface-card border border-border-default rounded-lg shadow-xl py-1 w-52"
    >
      {TOOLS.map((tool) => {
        const Icon = tool.icon
        return (
          <button
            key={tool.id}
            onClick={() => {
              onSelectTool?.(tool.id)
              onClose?.()
            }}
            className="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
          >
            <Icon size={15} className="shrink-0" />
            <span>{tool.name}</span>
          </button>
        )
      })}
    </div>
  )
}
