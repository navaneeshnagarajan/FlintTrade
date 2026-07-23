import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const expectedHermesLicence = `MIT License

Copyright (c) 2025 Nous Research

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
`;

describe("hermes-agent attribution", () => {
  it("retains the exact upstream MIT licence and commit attribution", () => {
    const packageRoot = path.resolve(import.meta.dirname, "..");
    const licence = readFileSync(path.join(packageRoot, "resources", "licenses", "hermes-agent-LICENSE"), "utf8");
    const notice = readFileSync(path.resolve(packageRoot, "..", "..", "..", "notice"), "utf8");

    expect(licence).toBe(expectedHermesLicence);
    expect(notice).toContain("adapted from commit 7651764ce.");
    expect(notice).toContain(expectedHermesLicence.trimEnd());
  });
});
