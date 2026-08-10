#!/usr/bin/env node

import { readdir, readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { gzipSync } from 'node:zlib';

export const THREE_RUNTIME_GZIP_LIMIT = 174_080;
export const TOTAL_ENHANCEMENT_GZIP_LIMIT = 327_680;

const PILOT_MARKERS = ['p95FrameMs', 'missing-chapters'];
const THREE_MARKERS = ['WebGLRenderer', 'WebGLProgram', 'REVISION:"185"'];
const CSS_MARKER = 'ft-scroll-world-on';

function gzipBytes(bytes) {
  return gzipSync(bytes, { level: 9 }).byteLength;
}

export function auditArtifacts(artifacts) {
  const decoded = artifacts.map((artifact) => ({
    ...artifact,
    text: artifact.bytes.toString('utf8'),
    gzip: gzipBytes(artifact.bytes),
  }));
  const pilot = decoded.filter(
    ({ path, text }) => path.endsWith('.js') && PILOT_MARKERS.some((marker) => text.includes(marker)),
  );
  const three = decoded.filter(
    ({ path, text }) => path.endsWith('.js') && THREE_MARKERS.some((marker) => text.includes(marker)),
  );
  const css = decoded.filter(({ path, text }) => path.endsWith('.css') && text.includes(CSS_MARKER));

  if (!pilot.length) throw new Error('Scroll-world payload gate found no pilot JavaScript chunk');
  if (!three.length) throw new Error('Scroll-world payload gate found no Three runtime chunk');
  if (!css.length) throw new Error('Scroll-world payload gate found no pilot CSS artifact');

  const union = new Map();
  for (const artifact of [...pilot, ...three, ...css]) union.set(artifact.path, artifact);

  return {
    pilotFiles: pilot.map(({ path }) => path).sort(),
    threeFiles: three.map(({ path }) => path).sort(),
    cssFiles: css.map(({ path }) => path).sort(),
    threeRuntimeGzip: three.reduce((total, artifact) => total + artifact.gzip, 0),
    totalEnhancementGzip: [...union.values()].reduce((total, artifact) => total + artifact.gzip, 0),
    files: [...union.values()]
      .map(({ path, bytes, gzip }) => ({ path, raw: bytes.byteLength, gzip }))
      .sort((left, right) => left.path.localeCompare(right.path)),
  };
}

export function assertPayloadBudgets(report) {
  if (report.threeRuntimeGzip > THREE_RUNTIME_GZIP_LIMIT) {
    throw new Error(
      `Three runtime gzip ${report.threeRuntimeGzip} B exceeds ${THREE_RUNTIME_GZIP_LIMIT} B`,
    );
  }
  if (report.totalEnhancementGzip > TOTAL_ENHANCEMENT_GZIP_LIMIT) {
    throw new Error(
      `Scroll-world total enhancement gzip ${report.totalEnhancementGzip} B exceeds ${TOTAL_ENHANCEMENT_GZIP_LIMIT} B`,
    );
  }
}

async function collectArtifacts(directory, root = directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const artifacts = [];
  for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
    const absolute = resolve(directory, entry.name);
    if (entry.isDirectory()) artifacts.push(...await collectArtifacts(absolute, root));
    else if (entry.name.endsWith('.js') || entry.name.endsWith('.css')) {
      artifacts.push({ path: absolute.slice(root.length + 1), bytes: await readFile(absolute) });
    }
  }
  return artifacts;
}

export async function auditScrollWorldBuild(staticDirectory = resolve(process.cwd(), '.next', 'static')) {
  const report = auditArtifacts(await collectArtifacts(staticDirectory));
  assertPayloadBudgets(report);
  return report;
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : '';
if (import.meta.url === invokedPath) {
  try {
    const report = await auditScrollWorldBuild();
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  }
}
