import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { describe, expect, it } from "vitest";

const desktopRoot = path.resolve(import.meta.dirname, "..");
const manifestPath = path.join(desktopRoot, "resources", "bootstrap", "tool-manifest.json");
const generatorPath = path.join(desktopRoot, "scripts", "generate-bootstrap-tool-manifest.mjs");
const nodeChecksums = path.join(
  desktopRoot,
  "resources",
  "bootstrap",
  "checksums",
  "node-v22.23.1-SHASUMS256.txt",
);
const uvChecksums = path.join(
  desktopRoot,
  "resources",
  "bootstrap",
  "checksums",
  "uv-0.11.16-sha256.sum",
);

interface ManifestAsset {
  archive: "tar.gz" | "zip";
  executable: string;
  sha256: string;
  url: string;
}

interface ToolManifest {
  node: { assets: Record<string, ManifestAsset>; version: string };
  pnpm: { integrity: string; packageManager: string; version: string };
  schemaVersion: number;
  uv: { assets: Record<string, ManifestAsset>; version: string };
}

describe("bootstrap tool manifest", () => {
  it("covers the release matrix with pinned authoritative digests", () => {
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as ToolManifest;
    const targets = ["darwin-arm64", "darwin-x64", "linux-arm64", "linux-x64", "win32-x64"];

    expect(manifest.schemaVersion).toBe(1);
    expect(manifest.node.version).toBe("22.23.1");
    expect(manifest.uv.version).toBe("0.11.16");
    expect(Object.keys(manifest.node.assets).sort()).toEqual(targets);
    expect(Object.keys(manifest.uv.assets).sort()).toEqual(targets);
    expect(manifest.pnpm).toEqual({
      integrity: "sha512-76e2379760a4328ec4415815bcd6628dee727af3779aaa4c914e3944156c4299921a89f976381ee107d41f12cfa4b66681ca9c718f0668fa0831ed4c6d8ba56c",
      packageManager: "pnpm@9.15.0+sha512.76e2379760a4328ec4415815bcd6628dee727af3779aaa4c914e3944156c4299921a89f976381ee107d41f12cfa4b66681ca9c718f0668fa0831ed4c6d8ba56c",
      version: "9.15.0",
    });
    for (const asset of [...Object.values(manifest.node.assets), ...Object.values(manifest.uv.assets)]) {
      expect(asset.sha256).toMatch(/^[0-9a-f]{64}$/);
      expect(asset.url).toMatch(/^https:\/\/(nodejs\.org|github\.com)\//);
      expect(asset.executable).not.toContain("..");
    }
  });

  it("is reproducible from the checked-in authoritative checksum snapshots", () => {
    expect(() => execFileSync(process.execPath, [generatorPath, "--check"], { cwd: desktopRoot })).not.toThrow();
  });

  it("rejects a checksum snapshot that does not match the committed manifest", () => {
    const scratch = mkdtempSync(path.join(tmpdir(), "flinttrade-manifest-test-"));
    try {
      const tamperedNode = path.join(scratch, "SHASUMS256.txt");
      writeFileSync(
        tamperedNode,
        readFileSync(nodeChecksums, "utf8").replace(/^[0-9a-f]{64}/m, "0".repeat(64)),
      );
      const result = spawnSync(
        process.execPath,
        [
          generatorPath,
          "--check",
          "--node-checksums",
          tamperedNode,
          "--uv-checksums",
          uvChecksums,
          "--manifest",
          manifestPath,
        ],
        { cwd: desktopRoot, encoding: "utf8" },
      );

      expect(result.status).not.toBe(0);
      expect(result.stderr).toContain("out of date");
    } finally {
      rmSync(scratch, { force: true, recursive: true });
    }
  });
});
