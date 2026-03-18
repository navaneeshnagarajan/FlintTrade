import { Grid3x3 } from 'lucide-react'

export default function OptionChainWidget({ node }) {
  return (
    <div className="h-full flex items-center justify-center text-text-muted">
      <div className="text-center">
        <Grid3x3 size={32} className="mx-auto mb-2 text-accent" />
        <div className="text-sm font-medium text-text-primary">Option Chain</div>
        <div className="text-xs mt-1">Full chain with OI/Greeks/IV — Phase 2</div>
      </div>
    </div>
  )
}
