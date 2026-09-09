import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import {
  descriptionDuplicatesOpeningBody,
  descriptionFromMarkdown,
  shouldHidePageDescription,
  shouldRenderDocsDescription,
} from './docs-description.mjs';

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..');

const docsReadme = readFileSync(join(repoRoot, 'docs/README.md'), 'utf8');
const userGuide = readFileSync(join(repoRoot, 'docs/USER_GUIDE.md'), 'utf8');

function bodyAfterTitle(markdown) {
  return markdown.replace(/^#\s+.+\n+/, '').trimStart();
}

describe('descriptionFromMarkdown', () => {
  it('lifts the first body paragraph and truncates it', () => {
    const description = descriptionFromMarkdown(docsReadme, 'Project documentation index');

    expect(description.startsWith('Welcome to the FlintTrade documentation.')).toBe(true);
    expect(description.length).toBeLessThanOrEqual(180);
    expect(description).not.toBe('Project documentation index');
  });

  it('returns the fallback when there is no body paragraph', () => {
    expect(descriptionFromMarkdown('# Title only\n', 'Catalogue blurb')).toBe('Catalogue blurb');
  });
});

describe('descriptionDuplicatesOpeningBody', () => {
  it('treats the docs README extract as a duplicate of the opening body paragraph', () => {
    const extracted = descriptionFromMarkdown(docsReadme, 'Project documentation index');
    const body = bodyAfterTitle(docsReadme);

    expect(descriptionDuplicatesOpeningBody(extracted, body)).toBe(true);
    expect(shouldHidePageDescription(extracted, body)).toBe(true);
  });

  it('treats a truncated extract as a duplicate of the longer opening paragraph', () => {
    const body = 'Welcome to the FlintTrade documentation. FlintTrade is a beta-stage workstation.';
    const truncated = body.slice(0, 40);

    expect(descriptionDuplicatesOpeningBody(truncated, body)).toBe(true);
  });

  it('does not treat a distinct catalogue blurb as a duplicate', () => {
    const body = bodyAfterTitle(docsReadme);

    expect(descriptionDuplicatesOpeningBody('Project documentation index', body)).toBe(false);
    expect(shouldHidePageDescription('Project documentation index', body)).toBe(false);
  });

  it('does not hide a page whose description is not the opening paragraph', () => {
    const description = 'Read-only MCP surfaces for development, documentation, and contribution workflows.';
    const body =
      'The FlintTrade docs MCP is a read-only development assistant. It exposes repository documentation.';

    expect(descriptionDuplicatesOpeningBody(description, body)).toBe(false);
    expect(shouldHidePageDescription(description, body)).toBe(false);
  });

  it('detects the user-guide opening paragraph after the title is stripped', () => {
    const extracted = descriptionFromMarkdown(userGuide, 'User guide for local setup and FlintTrade workspaces');
    const body = bodyAfterTitle(userGuide);

    expect(extracted.startsWith('This guide walks you from a fresh install')).toBe(true);
    expect(descriptionDuplicatesOpeningBody(extracted, body)).toBe(true);
  });
});

describe('shouldRenderDocsDescription', () => {
  it('hides the on-page summary when the generator marks it as a body duplicate', () => {
    expect(shouldRenderDocsDescription({ description: 'Welcome to FlintTrade', hideDescription: true })).toBe(
      false,
    );
  });

  it('keeps a distinct catalogue subtitle when hideDescription is false', () => {
    expect(
      shouldRenderDocsDescription({
        description: 'Project documentation index',
        hideDescription: false,
      }),
    ).toBe(true);
  });

  it('fails closed when hideDescription is missing so a stripped field cannot re-duplicate', () => {
    expect(shouldRenderDocsDescription({ description: 'Welcome to the FlintTrade documentation.' })).toBe(false);
    expect(shouldRenderDocsDescription({ description: 'Welcome to the FlintTrade documentation.', hideDescription: undefined })).toBe(
      false,
    );
  });

  it('does not render an empty description', () => {
    expect(shouldRenderDocsDescription({ description: '   ', hideDescription: false })).toBe(false);
    expect(shouldRenderDocsDescription({ hideDescription: false })).toBe(false);
  });
});
