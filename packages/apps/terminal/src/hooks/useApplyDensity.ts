/**
 * Mirror Compact / Comfortable onto <html> from first paint.
 */

import { useEffect } from "react";
import { applyDensityToDocument } from "@/lib/applyDensity";
import { useSettingsStore } from "@/stores/settingsStore";

export function useApplyDensity(): void {
  const density = useSettingsStore((s) => s.density);

  useEffect(() => {
    applyDensityToDocument(density);
  }, [density]);
}
