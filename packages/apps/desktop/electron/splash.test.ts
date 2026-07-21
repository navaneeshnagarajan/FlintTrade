import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const splashDirectory = path.resolve(import.meta.dirname, "..", "splash");
const html = readFileSync(path.join(splashDirectory, "index.html"), "utf8");

describe("packaged splash security policy", () => {
  it("loads only external local CSS and JavaScript under a restrictive CSP", () => {
    expect(html).toContain(
      "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'none'; connect-src 'none'; " +
        "font-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    );
    expect(html).not.toContain("'unsafe-inline'");
    expect(html).not.toMatch(/<style(?:\s|>)/i);
    expect(html).not.toMatch(/<script(?![^>]*\bsrc=)[^>]*>/i);
    expect(html).toContain('<link rel="stylesheet" href="./splash.css" />');
    expect(html).toContain('<script src="./splash.js"></script>');
    expect(readFileSync(path.join(splashDirectory, "splash.css"), "utf8")).toContain(".progress-fill");
    expect(readFileSync(path.join(splashDirectory, "splash.js"), "utf8")).toContain('invoke("bootstrap_status")');
  });
});
