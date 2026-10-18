import { useSyncExternalStore } from "react";
import { isPublicDemoBuild } from "@/lib/demoSession";
const KEY = "flinttrade:developer:v1";
const EVENT = "flinttrade:developer-preference";
export function developerEnabled(): boolean { return !isPublicDemoBuild() && localStorage.getItem(KEY) === "enabled"; }
function subscribe(listener: () => void) {
  window.addEventListener(EVENT, listener); window.addEventListener("storage", listener);
  return () => { window.removeEventListener(EVENT, listener); window.removeEventListener("storage", listener); };
}
export function useDeveloperEnabled() { return useSyncExternalStore(subscribe, developerEnabled, () => false); }
export function DeveloperPreference() {
  const enabled = useDeveloperEnabled();
  if (isPublicDemoBuild()) return null;
  return <section className="space-y-2 rounded border border-border-default p-3">
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={enabled} onChange={event => { localStorage.setItem(KEY, event.target.checked ? "enabled" : "disabled"); window.dispatchEvent(new Event(EVENT)); }} />Enable Developer features</label>
    <p className="text-xs text-text-muted">Installed-only experimental visibility. This does not arm Live, change accounts, bypass qualification or grant permission.</p>
  </section>;
}
