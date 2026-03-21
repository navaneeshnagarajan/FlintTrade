/**
 * SettingsRoute — standalone /settings page.
 *
 * Wraps the SettingsTool in a full-page layout with a back button.
 * Accessible from any route (Welcome, Explore, or the app itself).
 */

import { lazy, Suspense } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { LogoIcon } from "@/components/brand/Logo";

const SettingsTool = lazy(() => import("@/tools/Settings/SettingsTool"));

export default function SettingsRoute() {
  const navigate = useNavigate();

  return (
    <div className="fixed inset-0 bg-surface-base flex flex-col overflow-hidden">
      {/* Slim header */}
      <div className="flex items-center gap-3 px-4 h-10 border-b border-border-subtle shrink-0">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="flex items-center gap-1.5 text-text-muted hover:text-text-primary text-xs transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back
        </button>
        <div className="w-px h-4 bg-border-subtle" />
        <div className="flex items-center gap-1.5">
          <LogoIcon size={16} />
          <span className="font-heading font-semibold text-xs text-text-secondary">Settings</span>
        </div>
      </div>

      {/* Settings content — fills remaining space */}
      <div className="flex-1 overflow-y-auto">
        <Suspense
          fallback={
            <div className="flex items-center justify-center h-full">
              <div className="text-text-muted text-sm">Loading settings...</div>
            </div>
          }
        >
          <SettingsTool />
        </Suspense>
      </div>
    </div>
  );
}
