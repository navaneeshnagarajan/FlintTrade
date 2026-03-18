import { X, Settings } from 'lucide-react'

const SECTIONS = [
  'General',
  'Trading Defaults',
  'Risk',
  'API',
  'LLM',
  'Telegram',
  'Ditto',
  'Automation',
  'Layouts',
]

export default function SettingsTool({ onClose }) {
  return (
    <div className="h-full flex flex-col bg-surface-base">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-default bg-surface-card">
        <div className="flex items-center gap-2">
          <Settings size={18} className="text-accent" />
          <h1 className="text-sm font-semibold text-text-primary">Settings</h1>
        </div>
        <button onClick={onClose} className="text-text-muted hover:text-text-primary">
          <X size={16} />
        </button>
      </div>
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <Settings size={48} className="mx-auto mb-3 text-text-muted" />
          <div className="text-lg text-text-primary font-medium">Settings</div>
          <div className="text-sm text-text-secondary mt-1">
            Configure all aspects of FlintTrade
          </div>
          <div className="flex flex-wrap justify-center gap-2 mt-4 max-w-sm">
            {SECTIONS.map((section) => (
              <span
                key={section}
                className="px-2 py-1 rounded text-xs text-text-muted border border-border-default bg-surface-card"
              >
                {section}
              </span>
            ))}
          </div>
          <div className="text-xs text-text-muted mt-4">Coming in Phase 3-4</div>
        </div>
      </div>
    </div>
  )
}
