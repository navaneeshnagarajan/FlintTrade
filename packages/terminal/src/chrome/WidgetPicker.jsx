import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'
import * as LucideIcons from 'lucide-react'
import { widgetCatalog } from '../layout/widgetFactory'

/**
 * WidgetPicker — modal popup for adding widgets to the FlexLayout canvas.
 *
 * Props:
 *   isOpen      — boolean, controls visibility
 *   onClose     — () => void
 *   onAddWidget — (id: string, name: string) => void
 *
 * Groups widgets by category as defined in widgetCatalog.
 * Click-outside (backdrop) and the X button both close the modal.
 */
export default function WidgetPicker({ isOpen, onClose, onAddWidget }) {
  const panelRef = useRef(null)

  // Close on Escape key
  useEffect(() => {
    if (!isOpen) return
    const handleKey = (e) => {
      if (e.key === 'Escape') onClose?.()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [isOpen, onClose])

  if (!isOpen) return null

  // Derive unique ordered category list from the catalog
  const categories = []
  for (const w of widgetCatalog) {
    if (!categories.includes(w.category)) categories.push(w.category)
  }

  const handleBackdropClick = () => onClose?.()

  const handlePanelClick = (e) => e.stopPropagation()

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={handleBackdropClick}
    >
      <div
        ref={panelRef}
        className="bg-surface-card border border-border-default rounded-lg shadow-2xl w-[520px] max-h-[80vh] flex flex-col"
        onClick={handlePanelClick}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-default shrink-0">
          <h2 className="text-sm font-semibold text-text-primary tracking-wide">
            Add Widget
          </h2>
          <button
            onClick={onClose}
            className="text-text-secondary hover:text-text-primary transition-colors"
            aria-label="Close widget picker"
          >
            <X size={16} />
          </button>
        </div>

        {/* Widget grid grouped by category */}
        <div className="overflow-y-auto p-6 space-y-6">
          {categories.map((category) => {
            const widgets = widgetCatalog.filter((w) => w.category === category)
            return (
              <div key={category}>
                <h3 className="text-xs font-medium text-text-muted uppercase tracking-widest mb-3">
                  {category}
                </h3>
                <div className="grid grid-cols-4 gap-2">
                  {widgets.map((widget) => {
                    const Icon = LucideIcons[widget.icon] || LucideIcons.Box
                    return (
                      <button
                        key={widget.id}
                        onClick={() => {
                          onAddWidget?.(widget.id, widget.name)
                          onClose?.()
                        }}
                        className="flex flex-col items-center gap-2 p-3 rounded hover:bg-surface-hover transition-colors group"
                      >
                        <Icon
                          size={22}
                          className="text-text-secondary group-hover:text-text-primary transition-colors"
                        />
                        <span className="text-xs text-text-secondary group-hover:text-text-primary transition-colors text-center leading-tight">
                          {widget.name}
                        </span>
                      </button>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
