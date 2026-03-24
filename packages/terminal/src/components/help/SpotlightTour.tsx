/**
 * SpotlightTour.tsx
 *
 * Step-by-step guided tour overlay. Highlights page elements via
 * `data-tour-target` attributes and shows a floating instruction card.
 *
 * Status: stub — full implementation in Task 7 (Sub-project 5 / Guided Onboarding).
 * Tour definitions live in lib/tourDefinitions.ts.
 *
 * Only renders when skillStore.helpPrefs.spotlightTours === true.
 */

import type { TourStep } from "@/lib/tourDefinitions";
import { useSkillStore } from "@/stores/skillStore";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SpotlightTourProps {
  /** The registered tourId from TOUR_DEFINITIONS in lib/tourDefinitions.ts */
  tourId: string;
  /** Tour steps — typically from TOUR_DEFINITIONS[tourId] */
  steps: TourStep[];
  /** Called when the user completes or dismisses the tour */
  onComplete?: () => void;
}

// ---------------------------------------------------------------------------
// Component — stub until Task 7 wires the full overlay engine
// ---------------------------------------------------------------------------

export function SpotlightTour({ tourId: _tourId, steps: _steps, onComplete: _onComplete }: SpotlightTourProps) {
  const spotlightEnabled = useSkillStore((state) => state.helpPrefs.spotlightTours);

  // Not rendered until the spotlight overlay engine is implemented (Task 7)
  if (!spotlightEnabled) return null;
  return null;
}

export default SpotlightTour;
