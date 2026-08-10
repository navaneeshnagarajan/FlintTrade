import { readFileSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

const repoRoot = path.resolve(process.cwd(), '../../..');
const publicDocPaths = [
  'docs/setup/hostinger-local-staging-prep.md',
  'docs/staging/hostinger-env-health-contract.md',
  'docs/staging/hostinger-local-build-manifest.md',
  'docs/staging/hostinger-local-test-proof.md',
  'docs/staging/hostinger-rollback-teardown-runbook.md',
] as const;

const publicDocs = publicDocPaths.map((relativePath) => ({
  relativePath,
  content: readFileSync(path.join(repoRoot, relativePath), 'utf8'),
}));

const forbiddenProcessPatterns = [
  { label: 'personal machine name', pattern: /ASRock/i },
  { label: 'personal Windows home', pattern: /C:[\\/]Users[\\/]/i },
  { label: 'personal username fragment', pattern: /navan/i },
  { label: 'process identifier', pattern: /\bPIDs?\b/i },
  { label: 'card identifier', pattern: /\bt_[0-9a-f]{6,}\b/i },
  { label: 'task identifier', pattern: /\btask\s+(?:id|identifier)\b|\btask[_-][0-9a-f]{6,}\b/i },
  { label: 'run identifier', pattern: /\brun\s+(?:id|identifier)\b|\brun[_-][0-9a-f]{6,}\b/i },
  { label: 'review bookkeeping', pattern: /\bblockers?\b/i },
  { label: 'specific checkout name', pattern: /\b(?:fix|wt)\/hostinger[-\w/]*|FlintTrade-wt-[\w-]+/i },
  { label: 'bare revision identifier', pattern: /\b[0-9a-f]{7,40}\b/i },
  {
    label: 'authoring metadata',
    pattern: /\b(?:rejected|authoring)\b[^\n]{0,80}\b(?:sha|head|tip|commit)\b|\b(?:sha|head|tip)\b[^\n]{0,80}\b(?:rejected|authoring)\b/i,
  },
  { label: 'raw transcript or log reference', pattern: /\braw\s+(?:transcripts?|logs?)\b/i },
  { label: 'private evidence location', pattern: /\bevidence\s+(?:path|directory|folder)\b/i },
  { label: 'review-fix commentary', pattern: /\bupdated\s+per\b|\bremoved\s+per\b/i },
  { label: 'end-note removal commentary', pattern: /\bend\s+of\b[^\n]*\bremoved\b/i },
] as const;

describe('public Hostinger documentation contract', () => {
  it('contains no personal, internal-review, or process-specific strings', () => {
    const findings = publicDocs.flatMap(({ relativePath, content }) =>
      forbiddenProcessPatterns.flatMap(({ label, pattern }) => {
        const match = content.match(pattern);
        return match ? [`${relativePath}: ${label}: ${match[0]}`] : [];
      }),
    );

    expect(findings).toEqual([]);
  });

  it('uses portable, repository-anchored commands without unsafe relative deletion', () => {
    const findings = publicDocs.flatMap(({ relativePath, content }) => {
      const lines = content.split('\n');
      return lines.flatMap((line, index) => {
        const issues: string[] = [];
        if (line.includes('&&')) issues.push(`${relativePath}:${index + 1}: chained shell command`);
        if (/[ \t]+$/.test(line)) issues.push(`${relativePath}:${index + 1}: trailing whitespace`);
        return issues;
      });
    });
    const rollback = publicDocs.find(({ relativePath }) =>
      relativePath.endsWith('hostinger-rollback-teardown-runbook.md'),
    )?.content;

    expect(rollback).toBeDefined();
    expect(rollback).toContain('export REPO_ROOT="/absolute/path/to/canonical-repository"');
    expect(rollback).not.toContain('cd "$HOME"');
    expect(rollback).not.toMatch(/^\s*rm\s+-rf\s+packages\//m);
    expect(rollback).not.toMatch(/^\s*rm\s+-rf\b/m);

    const gitCommandLines =
      rollback
        ?.split('\n')
        .map((line) => line.trimStart())
        .filter((line) => /^git\b/.test(line)) ?? [];
    expect(gitCommandLines.length).toBeGreaterThan(0);
    expect(gitCommandLines.every((line) => line.startsWith('git -C "$REPO_ROOT" '))).toBe(true);

    for (const command of [
      'git -C "$REPO_ROOT" worktree remove "$PREP_CHECKOUT"',
      'git -C "$REPO_ROOT" show-ref --verify "$PREP_REF"',
      'git -C "$REPO_ROOT" worktree add "$PREP_CHECKOUT" "$PREP_REF"',
      'git -C "$REPO_ROOT" fetch "$ROLLBACK_BUNDLE" "$PREP_REF:$PREP_REF"',
      'git -C "$REPO_ROOT" branch -d "${PREP_REF#refs/heads/}"',
      'git -C "$REPO_ROOT" worktree list',
    ]) {
      expect(rollback).toContain(command);
    }

    expect(findings).toEqual([]);
  });

  it('states the Node-served artifact contract without static-upload advice', () => {
    const corpus = publicDocs.map(({ content }) => content).join('\n');
    const contradictoryAdvice = [
      /\.next\/static/i,
      /\b(?:upload|deploy|publish)\b[^\n]{0,100}\bstatic\b/i,
      /\bstatic\b[^\n]{0,100}\b(?:upload|deploy|publish)\b/i,
      /\bserve@(?:latest|\d+)[^\n]*\bout\b/i,
    ].flatMap((pattern) => {
      const match = corpus.match(pattern);
      return match ? [match[0]] : [];
    });

    expect(corpus).toMatch(/Node-served Next\.js application/i);
    expect(corpus).toMatch(/static export[^\n]*separate(?:ly)? reviewed code/i);
    expect(contradictoryAdvice).toEqual([]);
  });

  it('uses root and demo smoke probes plus a separate service-state check', () => {
    const corpus = publicDocs.map(({ content }) => content).join('\n');

    expect(corpus).not.toMatch(/\/(?:api\/)?health(?:\b|[/?#])/i);
    expect(corpus).toContain('curl --fail --head "$SITE_ORIGIN/"');
    expect(corpus).toContain('curl --fail --head "$SITE_ORIGIN/demo-app/"');
    expect(corpus).toContain('systemctl --user is-active "$SITE_SERVICE_UNIT"');
  });
});
