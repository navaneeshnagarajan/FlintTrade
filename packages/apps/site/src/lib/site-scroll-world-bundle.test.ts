import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import {
  THREE_RUNTIME_GZIP_LIMIT,
  TOTAL_ENHANCEMENT_GZIP_LIMIT,
  assertPayloadBudgets,
  auditArtifacts,
} from '../../scripts/audit-scroll-world-bundle.mjs';

const sitePackage = JSON.parse(readFileSync(resolve(process.cwd(), 'package.json'), 'utf8')) as {
  scripts: Record<string, string>;
};

describe('optional scroll-world payload gate', () => {
  it('encodes the hard 170 KiB Three and 320 KiB total gzip budgets in the production build', () => {
    expect(THREE_RUNTIME_GZIP_LIMIT).toBe(174_080);
    expect(TOTAL_ENHANCEMENT_GZIP_LIMIT).toBe(327_680);
    expect(sitePackage.scripts.build).toContain('audit-scroll-world-bundle.mjs');
  });

  it('classifies pilot, Three runtime and CSS artifacts and rejects either budget overrun', () => {
    const report = auditArtifacts([
      { path: 'pilot.js', bytes: Buffer.from('p95FrameMs missing-chapters') },
      { path: 'three.js', bytes: Buffer.from('WebGLRenderer WebGLProgram REVISION:"185"') },
      { path: 'world.css', bytes: Buffer.from('html.ft-scroll-world-on') },
    ]);

    expect(report.pilotFiles).toEqual(['pilot.js']);
    expect(report.threeFiles).toEqual(['three.js']);
    expect(report.cssFiles).toEqual(['world.css']);
    expect(() => assertPayloadBudgets({ ...report, threeRuntimeGzip: 174_081 })).toThrow(/Three runtime/);
    expect(() => assertPayloadBudgets({ ...report, totalEnhancementGzip: 327_681 })).toThrow(/total enhancement/);
  });
});
