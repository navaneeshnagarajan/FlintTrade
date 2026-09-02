/**
 * Spark Path chapter ledger. Pure data and interpolation; no Three.js import.
 * Each entry maps to an existing semantic homepage anchor.
 */

export type ChapterId = 0 | 1 | 2 | 3 | 4 | 5;
export type ChapterGrade = 'graphite' | 'emerald' | 'horizon';
export type Vector3Tuple = [number, number, number];

export interface ChapterSpec {
  id: ChapterId;
  anchor: string;
  scrollWeight: number;
  camera: {
    position: Vector3Tuple;
    target: Vector3Tuple;
    fov: number;
  };
  world: {
    key: number;
    fog: number;
    embers: number;
    grade: ChapterGrade;
  };
  label: string;
}

export interface InterpolatedChapterState {
  position: Vector3Tuple;
  target: Vector3Tuple;
  fov: number;
  key: number;
  fog: number;
  embers: number;
  grade: ChapterGrade;
}

export const chapters: readonly ChapterSpec[] = [
  {
    id: 0,
    anchor: 'hero',
    scrollWeight: 1,
    camera: { position: [0, 1.5, 8], target: [0, 0.5, 0], fov: 55 },
    world: { key: 0, fog: 0.015, embers: 300, grade: 'graphite' },
    label: 'Hero / Flint facet ignition',
  },
  {
    id: 1,
    anchor: 'source',
    scrollWeight: 1.2,
    camera: { position: [4, 2, 6], target: [0, 1, -2], fov: 50 },
    world: { key: 0.25, fog: 0.012, embers: 200, grade: 'emerald' },
    label: 'Source / built for people who read the source',
  },
  {
    id: 2,
    anchor: 'docs',
    scrollWeight: 0.9,
    camera: { position: [0, 3, 5], target: [0, 1.5, -4], fov: 48 },
    world: { key: 0.5, fog: 0.01, embers: 150, grade: 'emerald' },
    label: 'Docs, API, and contribution paths',
  },
  {
    id: 3,
    anchor: 'mcp',
    scrollWeight: 1.1,
    camera: { position: [-3, 2.5, 7], target: [0, 0.5, -6], fov: 52 },
    world: { key: 0.75, fog: 0.008, embers: 100, grade: 'horizon' },
    label: 'MCP for development, not trading',
  },
  {
    id: 4,
    anchor: 'packages',
    scrollWeight: 0.7,
    camera: { position: [0, 4, 4], target: [0, 2, -3], fov: 45 },
    world: { key: 0.9, fog: 0.02, embers: 50, grade: 'graphite' },
    label: 'Package map at contributor speed',
  },
  {
    id: 5,
    anchor: 'footer',
    scrollWeight: 0.6,
    camera: { position: [0, 1, 10], target: [0, 0, 0], fov: 60 },
    world: { key: 1, fog: 0.025, embers: 20, grade: 'graphite' },
    label: 'Close / spark recedes',
  },
];

function lerp(start: number, end: number, amount: number): number {
  return start + (end - start) * amount;
}

function lerpVector(start: Vector3Tuple, end: Vector3Tuple, amount: number): Vector3Tuple {
  return [
    lerp(start[0], end[0], amount),
    lerp(start[1], end[1], amount),
    lerp(start[2], end[2], amount),
  ];
}

export function reachableChapterStops(
  sectionTops: readonly number[],
  scrollHeight: number,
  viewportHeight: number,
): number[] {
  if (!sectionTops.length) return [];
  const maxScroll = Math.max(0, scrollHeight - viewportHeight);
  const firstTop = sectionTops[0];
  const lastTop = sectionTops.at(-1) ?? firstTop;
  const anchorSpan = Math.max(1, lastTop - firstTop);

  return sectionTops.map((top, index) => {
    if (index === 0) return 0;
    if (index === sectionTops.length - 1) return maxScroll;
    return Math.max(0, Math.min(maxScroll, ((top - firstTop) / anchorSpan) * maxScroll));
  });
}

export function progressFromScroll(
  scrollY: number,
  sectionTops: readonly number[],
  scrollHeight: number,
  viewportHeight: number,
): number {
  const stops = reachableChapterStops(sectionTops, scrollHeight, viewportHeight);
  if (stops.length < 2 || scrollY <= stops[0]) return 0;
  const lastIndex = stops.length - 1;
  if (scrollY >= stops[lastIndex]) return lastIndex;

  for (let index = 0; index < lastIndex; index += 1) {
    const start = stops[index];
    const end = stops[index + 1];
    if (scrollY <= end) {
      const distance = Math.max(1, end - start);
      return index + (scrollY - start) / distance;
    }
  }
  return lastIndex;
}

export function interpolateChapterState(progress: number): InterpolatedChapterState {
  const bounded = Math.max(0, Math.min(chapters.length - 1, progress));
  const startIndex = Math.floor(bounded);
  const endIndex = Math.min(chapters.length - 1, startIndex + 1);
  const amount = bounded - startIndex;
  const start = chapters[startIndex];
  const end = chapters[endIndex];

  return {
    position: lerpVector(start.camera.position, end.camera.position, amount),
    target: lerpVector(start.camera.target, end.camera.target, amount),
    fov: lerp(start.camera.fov, end.camera.fov, amount),
    key: lerp(start.world.key, end.world.key, amount),
    fog: lerp(start.world.fog, end.world.fog, amount),
    embers: Math.round(lerp(start.world.embers, end.world.embers, amount)),
    grade: amount < 0.5 ? start.world.grade : end.world.grade,
  };
}
