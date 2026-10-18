import { Link } from "react-router";
import { PREVIEW_AS_OF } from "@/lib/publicPreview";
import { BUILD_VERSIONS } from "@/lib/versionInventory";
export function PublicPreviewHeader() {
  return <div className="flex flex-wrap items-center gap-3 border-b border-border-default bg-surface-base px-3 py-2 text-xs" data-testid="public-preview-header">
    <strong className="text-sm">FlintTrade</strong><span className="text-warning">Example · frozen simulation</span>
    <span>As of {PREVIEW_AS_OF} · build {BUILD_VERSIONS.commit?.slice(0, 12) ?? "source snapshot"}</span>
    <span>No accounts, sign-in, provider connections or real orders.</span>
    <Link to="/learn" className="text-accent">Learn</Link><a href="https://flinttrade.com/docs" className="ml-auto text-accent">Install FlintTrade</a>
  </div>;
}
