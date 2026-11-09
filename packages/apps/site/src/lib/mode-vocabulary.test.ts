/**
 * Public docs keep the session claim, the visible Mode, broker connectivity,
 * the lock, and Laya readiness apart, and they quote only labels the desk ships.
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

const repoRoot = resolve(process.cwd(), '..', '..', '..');

function readRepo(relativePath: string): string {
  return readFileSync(resolve(repoRoot, relativePath), 'utf8');
}

describe('public mode vocabulary', () => {
  const modes = readRepo('docs/product-modes.mdx');
  const architecture = readRepo('docs/ARCHITECTURE.md');
  const api = readRepo('docs/API.md');
  const guide = readRepo('docs/USER_GUIDE.md');
  const glossary = readRepo('docs/GLOSSARY.md');

  it('maps claim identifiers to visible labels without merging the other facts', () => {
    expect(modes).toContain('JWT `mode` is `explore`, `practice`, or `live`');
    expect(modes).toContain('**Example** is not a Mode');
    expect(modes).toContain('**Connected (read)** is not a claim');
    expect(modes).toContain('Idle headings `Practice desk locked`');
    expect(modes).toContain('Laya is the shipped name of this row');
    expect(api).toContain('| `explore` | **Example**');
    expect(api).toContain('| `practice` | **Practice**');
    expect(api).toContain('| `live` | **Live**');
    expect(glossary).toContain('Its JWT claim is `explore`');
  });

  it('sends Guest to Setup and does not draw that choice as a mode downgrade', () => {
    expect(modes).toContain('Choosing **Practice** while signed in as **Guest** opens Setup');
    expect(modes).toContain('does not call `POST /v1/auth/mode`');
    expect(architecture).toContain('Guest --> Setup: Mode menu Practice');
    expect(architecture).not.toContain('ExampleData --> Practice');
    expect(guide).toContain('Choosing **Practice** opens Setup and does not');
    expect(guide).toContain('call `POST /v1/auth/mode`');
  });

  it('states the broker freeze instead of offering a connect step', () => {
    expect(modes).toContain('A broker session cannot be started from the terminal today');
    expect(modes).toContain('Broker-account writes return HTTP 503');
    expect(modes).toContain('native HTTP reads return HTTP 409');
    expect(modes).toContain('not a setup step');
    expect(guide).toContain('not an available connection action');
    expect(guide).toContain('that label is not a setup step');
  });

  it('names Downloading, and names Transition only on the revised clock', () => {
    expect(modes).toContain('**Downloading**');
    expect(guide).toContain('can also read **Transition**');
    expect(guide).toContain('Transition 15:45–15:50');
    expect(guide).toContain('no Transition phase');
  });

  it('names the Practice sandbox instead of paper trading', () => {
    expect(api).toContain('### Practice sandbox (`/ft-api/v1/sandbox/*`)');
    expect(api).not.toContain('paper trading');
    expect(glossary).not.toContain('paper trading');
    expect(glossary).toContain('A scoped period of Live or Practice');
  });
});
