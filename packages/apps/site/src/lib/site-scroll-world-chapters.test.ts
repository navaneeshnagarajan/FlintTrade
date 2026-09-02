import { describe, expect, it } from 'vitest';

import {
  chapters,
  interpolateChapterState,
  progressFromScroll,
  reachableChapterStops,
} from './site-scroll-world-chapters';

describe('Spark Path chapter ledger', () => {
  it('defines every existing homepage chapter exactly once from 0 through 5', () => {
    expect(chapters.map((chapter) => chapter.id)).toEqual([0, 1, 2, 3, 4, 5]);
    expect(chapters.map((chapter) => chapter.anchor)).toEqual([
      'hero',
      'source',
      'docs',
      'mcp',
      'packages',
      'footer',
    ]);
    expect(chapters.map((chapter) => chapter.label)).toEqual([
      'Hero / Flint facet ignition',
      'Source / built for people who read the source',
      'Docs, API, and contribution paths',
      'MCP for development, not trading',
      'Package map at contributor speed',
      'Close / spark recedes',
    ]);
    expect(new Set(chapters.map((chapter) => chapter.anchor)).size).toBe(6);
  });

  it('maps scroll piecewise between reachable chapter stops', () => {
    const tops = [0, 100, 300, 600, 1000, 1500];
    const scrollHeight = 2400;
    const viewportHeight = 900;

    expect(progressFromScroll(-20, tops, scrollHeight, viewportHeight)).toBe(0);
    expect(progressFromScroll(50, tops, scrollHeight, viewportHeight)).toBeCloseTo(0.5);
    expect(progressFromScroll(200, tops, scrollHeight, viewportHeight)).toBeCloseTo(1.5);
    expect(progressFromScroll(800, tops, scrollHeight, viewportHeight)).toBeCloseTo(3.5);
    expect(progressFromScroll(scrollHeight - viewportHeight, tops, scrollHeight, viewportHeight)).toBe(5);
  });

  it('fits ordered anchors into the real bounded document range so normal max scroll reaches chapter 5', () => {
    const tops = [80, 520, 980, 1540, 2110, 2520];
    const scrollHeight = 2600;
    const viewportHeight = 900;
    const maxScroll = scrollHeight - viewportHeight;
    const stops = reachableChapterStops(tops, scrollHeight, viewportHeight);

    expect(stops[0]).toBe(0);
    expect(stops.at(-1)).toBe(maxScroll);
    expect(stops.every((stop, index) => index === 0 || stop > stops[index - 1])).toBe(true);
    for (let chapter = 0; chapter < stops.length; chapter += 1) {
      expect(progressFromScroll(stops[chapter], tops, scrollHeight, viewportHeight)).toBeCloseTo(chapter);
    }
    expect(progressFromScroll(maxScroll, tops, scrollHeight, viewportHeight)).toBe(5);
  });

  it('interpolates camera, target, fov, fog, light and ember density between chapters', () => {
    const state = interpolateChapterState(0.5);
    expect(state.position[0]).toBeCloseTo(2);
    expect(state.position[1]).toBeCloseTo(1.75);
    expect(state.position[2]).toBeCloseTo(7);
    expect(state.target[2]).toBeCloseTo(-1);
    expect(state.fov).toBeCloseTo(52.5);
    expect(state.fog).toBeCloseTo(0.0135);
    expect(state.key).toBeCloseTo(0.125);
    expect(state.embers).toBe(250);
  });
});
