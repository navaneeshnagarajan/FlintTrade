/**
 * Spark Path chapter ledger — pure data, no three import.
 * Maps existing Graphite Continuity bands to camera/world state for the scroll conductor.
 * Restrained depth, market/data/risk abstract geometry (no live numbers, no broker data).
 * TDD: this file supports the policy tests and page enrichment.
 */

export type ChapterId = 0 | 1 | 2 | 3 | 4 | 5;

export interface ChapterSpec {
  id: ChapterId;
  anchor: string;
  scrollWeight: number;
  camera: {
    position: [number, number, number];
    target: [number, number, number];
    fov: number;
  };
  world: {
    key: number;
    fog: number;
    embers: number;
    grade: 'graphite' | 'emerald' | 'horizon';
  };
  label: string; // for a11y/debug
}

export const chapters: ChapterSpec[] = [
  {
    id: 0,
    anchor: 'hero',
    scrollWeight: 1.0,
    camera: { position: [0, 1.5, 8], target: [0, 0.5, 0], fov: 55 },
    world: { key: 0.0, fog: 0.015, embers: 300, grade: 'graphite' },
    label: 'Hero / Flint facet ignition',
  },
  {
    id: 1,
    anchor: 'self-hosted',
    scrollWeight: 1.2,
    camera: { position: [4, 2, 6], target: [0, 1, -2], fov: 50 },
    world: { key: 0.25, fog: 0.012, embers: 200, grade: 'emerald' },
    label: 'Self-hosted workspace plates',
  },
  {
    id: 2,
    anchor: 'safety',
    scrollWeight: 0.9,
    camera: { position: [0, 3, 5], target: [0, 1.5, -4], fov: 48 },
    world: { key: 0.5, fog: 0.01, embers: 150, grade: 'emerald' },
    label: 'Safety arches (Explore/Practice/Live)',
  },
  {
    id: 3,
    anchor: 'evaluate',
    scrollWeight: 1.1,
    camera: { position: [-3, 2.5, 7], target: [0, 0.5, -6], fov: 52 },
    world: { key: 0.75, fog: 0.008, embers: 100, grade: 'horizon' },
    label: 'Evaluate horizon desk',
  },
  {
    id: 4,
    anchor: 'contributor',
    scrollWeight: 0.7,
    camera: { position: [0, 4, 4], target: [0, 2, -3], fov: 45 },
    world: { key: 0.9, fog: 0.02, embers: 50, grade: 'graphite' },
    label: 'Contributor alcove',
  },
  {
    id: 5,
    anchor: 'footer',
    scrollWeight: 0.6,
    camera: { position: [0, 1, 10], target: [0, 0, 0], fov: 60 },
    world: { key: 1.0, fog: 0.025, embers: 20, grade: 'graphite' },
    label: 'Close / recede',
  },
];

export function getChapterById(id: ChapterId): ChapterSpec | undefined {
  return chapters.find((c) => c.id === id);
}

export function progressFromScroll(scrollY: number, sectionTops: number[]): number {
  // Returns fractional chapter progress; deterministic forward/reverse
  if (!sectionTops.length) return 0;
  const total = sectionTops[sectionTops.length - 1] - sectionTops[0] || 1;
  const p = Math.max(0, Math.min(1, (scrollY - sectionTops[0]) / total));
  return p * (chapters.length - 1);
}
