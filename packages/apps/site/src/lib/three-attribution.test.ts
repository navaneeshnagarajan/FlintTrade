import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const expectedThreeLicence = `The MIT License

Copyright © 2010-2026 three.js authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
`;

describe('Three.js bundled-library attribution', () => {
  it('ships the exact Three.js r185 MIT licence and names it in the human NOTICE', () => {
    const repoRoot = resolve(process.cwd(), '..', '..', '..');
    const licencePath = resolve(process.cwd(), 'public', 'licenses', 'three-LICENSE');
    const noticePath = resolve(repoRoot, 'notice');

    expect(existsSync(licencePath)).toBe(true);
    if (!existsSync(licencePath)) return;

    expect(readFileSync(licencePath, 'utf8')).toBe(expectedThreeLicence);
    const notice = readFileSync(noticePath, 'utf8');
    expect(notice).toContain('- Three.js r185 (MIT) — Copyright © 2010-2026 three.js authors');
    expect(notice).toContain('`packages/apps/site/public/licenses/three-LICENSE`');
  });
});
