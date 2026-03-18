import { Zap } from 'lucide-react'

export default function ScalperWidget({ node }) {
  return (
    <div className="h-full flex items-center justify-center text-text-muted">
      <div className="text-center">
        <Zap size={32} className="mx-auto mb-2 text-warning" />
        <div className="text-sm font-medium text-text-primary">Scalper</div>
        <div className="text-xs mt-1">3-panel chart trading — Phase 2</div>
      </div>
    </div>
  )
}
