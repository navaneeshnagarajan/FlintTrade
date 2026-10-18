import { useState } from "react";
import { useSkillStore } from "@/stores/skillStore";
import { Button } from "@/components/ui/button";
import { SpotlightTour } from "./SpotlightTour";
import { TOUR_DEFINITIONS } from "@/lib/tourDefinitions";
export function HelpPreferences() {
  const prefs = useSkillStore(s => s.helpPrefs);
  const set = useSkillStore(s => s.setHelpPref);
  const [tour, setTour] = useState("");
  function reset(prefix: string) { Object.keys(localStorage).filter(key => key.startsWith(prefix)).forEach(key => localStorage.removeItem(key)); }
  return <section className="space-y-3"><h3 className="text-sm font-medium">Help and guidance</h3>
    {([['inlineHints', 'Inline hints'], ['spotlightTours', 'Guided tours'], ['aiTutor', 'AI companion']] as const).map(([key, name]) => <label key={key} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={prefs[key]} onChange={event => set(key, event.target.checked)} />{name}</label>)}
    <Button size="sm" variant="outline" onClick={() => reset("ft-hint-dismissed-")}>Reset hints</Button>
    <label className="block text-xs">Replay a tour <select aria-label="Replay a tour" className="rounded bg-surface-card p-2" value={tour} onChange={event => { reset("ft-tour-completed-"); set('spotlightTours', true); setTour(event.target.value); }}><option value="">Choose a tour</option>{Object.keys(TOUR_DEFINITIONS).map(id => <option key={id}>{id}</option>)}</select></label>
    {tour && <SpotlightTour key={tour} tourId={tour} steps={TOUR_DEFINITIONS[tour] ?? []} />}
  </section>;
}
