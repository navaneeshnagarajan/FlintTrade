import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readVersionInventory } from "../../vite.versionInventory";
let root: string;
let terminal: string;
function json(file: string, value: unknown) { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, JSON.stringify(value)); }
beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), "ft-versions-"));
  terminal = path.join(root, "packages/apps/terminal");
  json(path.join(terminal, "package.json"), { dependencies: { react: "^19.2.8", "react-dom": "^19.2.8" } });
  json(path.join(terminal, "node_modules/react/package.json"), { name: "react", version: "19.3.0", exports: "./index.js" });
  json(path.join(terminal, "node_modules/react-dom/package.json"), { name: "react-dom", version: "/invalid/path" });
  fs.writeFileSync(path.join(terminal, "node_modules/react/index.js"), 'throw new Error("must not execute package");');
  json(path.join(root, "package.json"), { packageManager: "pnpm@10.34.5+sha512.example" });
  json(path.join(root, "packages/apps/desktop/package.json"), { devDependencies: { electron: "44.4.1" } });
  json(path.join(root, "packages/apps/desktop/resources/bootstrap/tool-manifest.json"), { node: { version: "22.23.2", secret: "not exposed" }, uv: { version: "0.11.16" } });
});
afterEach(() => { fs.rmSync(root, { recursive: true, force: true }); vi.unstubAllEnvs(); });
describe("build inventory", () => {
  it("resolves exact installed metadata separately from ranges without importing package code", () => {
    const result = readVersionInventory(terminal);
    expect(result.libraries[0]).toEqual({ name: "react", installed: "19.3.0", declared: "^19.2.8" });
    expect(result.libraries[1]).toEqual({ name: "react-dom", installed: null, declared: "^19.2.8" });
    expect(result.pins).toContainEqual({ name: "pnpm", version: "10.34.5" });
    expect(result.pins).toContainEqual({ name: "uv bootstrap", version: "0.11.16" });
    expect(JSON.stringify(result)).not.toContain(root);
    expect(JSON.stringify(result)).not.toContain("not exposed");
  });
  it("treats non-object optional manifests as unavailable", () => {
    json(path.join(root, "packages/apps/desktop/resources/bootstrap/tool-manifest.json"), null);
    json(path.join(root, "packages/apps/desktop/package.json"), []);
    expect(readVersionInventory(terminal).pins).toContainEqual({ name: "uv bootstrap", version: null });
    expect(readVersionInventory(terminal).pins).toContainEqual({ name: "Electron shell", version: null });
  });
  it("accepts only existing full build commit hashes and reports missing pins honestly", () => {
    vi.stubEnv("VERCEL_GIT_COMMIT_SHA", "/private/path");
    fs.unlinkSync(path.join(root, "packages/apps/desktop/resources/bootstrap/tool-manifest.json"));
    expect(readVersionInventory(terminal).commit).toBeNull();
    expect(readVersionInventory(terminal).pins[0].version).toBeNull();
    vi.stubEnv("VERCEL_GIT_COMMIT_SHA", "a".repeat(40));
    expect(readVersionInventory(terminal).commit).toBe("a".repeat(40));
  });
});
