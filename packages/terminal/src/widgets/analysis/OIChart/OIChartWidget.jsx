import { BarChart3 } from 'lucide-react'

export default function OIChartWidget({ node }) {
  return (
    <div className="h-full flex items-center justify-center text-text-muted">
      <div className="text-center">
        <BarChart3 size={32} className="mx-auto mb-2 text-accent" />
        <div className="text-sm font-medium text-text-primary">OI Chart</div>
        <div className="text-xs mt-1">Open Interest analysis — Phase 3</div>
      </div>
    </div>
  )
}
