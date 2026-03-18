import { useRef, useCallback, useImperativeHandle, forwardRef } from 'react'
import { Layout, Actions, DockLocation } from 'flexlayout-react'
import 'flexlayout-react/style/dark.css'
import { widgetFactory } from './widgetFactory'

const LayoutManager = forwardRef(function LayoutManager({ model, onModelChange }, ref) {
  const layoutRef = useRef(null)

  // Expose addWidget method to parent
  useImperativeHandle(ref, () => ({
    addWidget(componentId, name) {
      if (!model) return
      try {
        // Try active tabset first
        const activeTabset = model.getActiveTabset()
        if (activeTabset) {
          model.doAction(Actions.addNode(
            { type: 'tab', name, component: componentId },
            activeTabset.getId(),
            DockLocation.CENTER,
            -1,
            true
          ))
          return
        }
      } catch { /* fallback below */ }

      // Fallback: find first tabset in the model
      const root = model.getRoot()
      const firstTabset = _findFirstTabset(root)
      if (firstTabset) {
        model.doAction(Actions.addNode(
          { type: 'tab', name, component: componentId },
          firstTabset.getId(),
          DockLocation.CENTER,
          -1,
          true
        ))
      }
    }
  }), [model])

  const factory = useCallback((node) => {
    return widgetFactory(node)
  }, [])

  return (
    <div className="flex-1 relative overflow-hidden">
      <Layout
        ref={layoutRef}
        model={model}
        factory={factory}
        onModelChange={onModelChange}
        font={{ size: '12px', family: 'Inter, system-ui, sans-serif' }}
      />
    </div>
  )
})

/** Recursively find the first tabset node in the FlexLayout model tree. */
function _findFirstTabset(node) {
  if (node.getType() === 'tabset') return node
  if (node.getChildren) {
    for (const child of node.getChildren()) {
      const found = _findFirstTabset(child)
      if (found) return found
    }
  }
  return null
}

export default LayoutManager
