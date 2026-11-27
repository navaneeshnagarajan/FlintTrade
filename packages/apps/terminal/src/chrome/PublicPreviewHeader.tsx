import { Link } from "react-router";
import { PREVIEW_AS_OF } from "@/lib/publicPreview";
import { BUILD_VERSIONS } from "@/lib/versionInventory";
export function PublicPreviewHeader() {
  return <div className="ft-public-preview" data-testid="public-preview-header">
    <strong className="text-sm">FlintTrade</strong><span className="text-warning">Example · frozen simulation</span>
  </div>;
}
export function PublicPreviewSafety() {
  return <div className="ft-preview-safety text-xs">
    <span>No accounts, sign-in, provider connections or real orders.</span>
    <details className="ft-preview-provenance"><summary>Snapshot details</summary><div className="ft-preview-details"><p>As of {PREVIEW_AS_OF} · build {BUILD_VERSIONS.commit?.slice(0, 12) ?? "source snapshot"}</p><Link to="/learn" className="text-accent">Learn</Link><a href="https://flinttrade.com/docs" className="text-accent">Install FlintTrade</a></div></details>
  </div>;
}
