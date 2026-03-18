import { useRef, useCallback, useImperativeHandle, forwardRef } from 'react'
import { Layout, Actions } from 'flexlayout-react'
import 'flexlayout-react/style/dark.css'
import { widgetFactory } from './widgetFactory'

const LayoutManager = forwardRef(function LayoutManager({ model, onModelChange }, ref) {
  const layoutRef = useRef(null)

  // Expose addWidget method to parent
  useImperativeHandle(ref, () => ({
    addWidget(componentId, name) {
      if (!layoutRef.current) return
      layoutRef.current.addTabToActiveTabSet({
        type: 'tab',
        name,
        component: componentId,
      })
    }
  }), [])

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

export default LayoutManager
