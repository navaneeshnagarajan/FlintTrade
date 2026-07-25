import type { SkillLevel } from "@/types/skill";

export type GateStatus = "visible" | "preview" | "locked";

export const FEATURE_GATES: Record<string, Record<SkillLevel, GateStatus>> = {
  // ---------------------------------------------------------------
  // Core widgets — always visible at every skill level
  // ---------------------------------------------------------------
  "widget:dashboard":   { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "widget:chart":       { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "widget:watchlist":   { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "widget:orderpad":    { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "widget:positions":   { beginner: "visible", intermediate: "visible", advanced: "visible" },

  // ---------------------------------------------------------------
  // Intermediate-unlock widgets
  // ---------------------------------------------------------------
  "widget:orders":      { beginner: "preview", intermediate: "visible", advanced: "visible" },
  "widget:holdings":    { beginner: "preview", intermediate: "visible", advanced: "visible" },
  "widget:tradebook":   { beginner: "preview", intermediate: "visible", advanced: "visible" },
  "widget:scalper":     { beginner: "locked",  intermediate: "visible", advanced: "visible" },
  "widget:optionchain": { beginner: "locked",  intermediate: "visible", advanced: "visible" },
  "widget:oichart":     { beginner: "locked",  intermediate: "visible", advanced: "visible" },
  "widget:straddle":    { beginner: "locked",  intermediate: "visible", advanced: "visible" },
  "widget:depth":       { beginner: "locked",  intermediate: "visible", advanced: "visible" },
  "widget:news":        { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "widget:ticker":      { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "widget:calculator":  { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "widget:aiadvisor":   { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "widget:mtmmonitor":  { beginner: "locked",  intermediate: "visible", advanced: "visible" },
  // NOTE: `widget:riskpanel` removed with the Risk merge. The canonical
  // (riskdashboard) is deliberately left UNGATED — a margin and daily-stop
  // readout is the last thing to hide from a beginner.
  "widget:actioncenter":{ beginner: "locked",  intermediate: "preview", advanced: "visible" },

  // ---------------------------------------------------------------
  // Analysis widgets — advanced-only or advanced-unlock
  // ---------------------------------------------------------------
  "widget:sectormap":   { beginner: "locked",  intermediate: "preview", advanced: "visible" },
  "widget:greeks":      { beginner: "locked",  intermediate: "locked",  advanced: "visible" },
  // NOTE: `widget:gex` was removed when GEX merged into Dealer Gamma
  // (`gammadensity`). The canonical is deliberately left UNGATED: gammadensity
  // was already visible at every level, so adopting GEX's advanced-only gate
  // would have TAKEN a surface away from beginners. That is the opposite
  // direction from the Order Flow merge, where the canonical was already the
  // stricter of the two.
  "widget:volsurface":  { beginner: "locked",  intermediate: "locked",  advanced: "visible" },
  // Retired id — resolves to `ivsmile`, which is advanced-only. Without its
  // own row an absent widget: id defaults to visible, so a saved `ivskew`
  // panel would bypass the gate its canonical carries.
  // The Greeks Matrix derives greeks client-side and labels them Live, while
  // its own IV source (widget:ivsmile) and sibling widget:volsurface are
  // advanced-only. Gating it closes that asymmetry; the retired id needs the
  // same row or a saved panel bypasses it.
  "widget:greeksheatmap": { beginner: "locked", intermediate: "locked", advanced: "visible" },
  "widget:greekssurface": { beginner: "locked", intermediate: "locked", advanced: "visible" },
  // The ladder absorbed Depth's real level-2 book and is rapid click-to-trade
  // order entry; its nearest sibling widget:scalper is already beginner-locked.
  // The two inputs were locked (depth) and ungated-by-omission (ladder), and
  // the omission reads as accidental rather than decided.
  "widget:orderladder": { beginner: "locked", intermediate: "visible", advanced: "visible" },
  // Retired id resolving to the gated straddle canonical.
  "widget:impliedmove": { beginner: "locked", intermediate: "visible", advanced: "visible" },
  "widget:ivskew":      { beginner: "locked",  intermediate: "locked",  advanced: "visible" },
  "widget:ivsmile":     { beginner: "locked",  intermediate: "locked",  advanced: "visible" },
  "widget:straddlepnl": { beginner: "locked",  intermediate: "locked",  advanced: "visible" },
  // Retired ids folded into `oichart`; each keeps a row so a saved panel
  // cannot bypass the canonical's gate. oiprofile was the strictest of the
  // four and keeps its own setting.
  "widget:oiheatmap":   { beginner: "locked",  intermediate: "visible", advanced: "visible" },
  "widget:oisignals":   { beginner: "locked",  intermediate: "visible", advanced: "visible" },
  "widget:oiprofile":   { beginner: "locked",  intermediate: "locked",  advanced: "visible" },
  // Merged canonical. Order Flow absorbed Footprint, which was locked to
  // advanced; an absent widget: id resolves to visible at every level, so
  // leaving this out would hand beginners a microstructure surface that was
  // advanced-only before the merge. The footprint entry stays because its
  // own gate test pins it and the retired id still resolves.
  "widget:orderflow": { beginner: "locked", intermediate: "locked", advanced: "visible" },
  "widget:footprint":   { beginner: "locked",  intermediate: "locked",  advanced: "visible" },
  "widget:domheatmap":  { beginner: "locked",  intermediate: "locked",  advanced: "visible" },

  // ---------------------------------------------------------------
  // Route-level gates
  // ---------------------------------------------------------------
  "route:trade":        { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "route:invest":       { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "route:learn":        { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "route:lab":          { beginner: "preview", intermediate: "visible", advanced: "visible" },
  "route:automate":     { beginner: "locked",  intermediate: "preview", advanced: "visible" },
  "route:ai":           { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "route:settings":     { beginner: "visible", intermediate: "visible", advanced: "visible" },

  // ---------------------------------------------------------------
  // Feature-level gates (within routes)
  // ---------------------------------------------------------------
  "feature:order-confirm":       { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "feature:basket-orders":       { beginner: "locked",  intermediate: "preview", advanced: "visible" },
  "feature:split-orders":        { beginner: "locked",  intermediate: "locked",  advanced: "visible" },
  "feature:options-multi-order": { beginner: "locked",  intermediate: "preview", advanced: "visible" },
  "feature:python-strategy":     { beginner: "locked",  intermediate: "locked",  advanced: "visible" },
  "feature:multi-account":       { beginner: "locked",  intermediate: "locked",  advanced: "visible" },
  "feature:monte-carlo":         { beginner: "locked",  intermediate: "locked",  advanced: "visible" },
  "feature:rag-pipeline":        { beginner: "locked",  intermediate: "preview", advanced: "visible" },
  "feature:keyboard-shortcuts":  { beginner: "preview", intermediate: "visible", advanced: "visible" },
};
