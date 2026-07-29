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
  generatedFrom: {
    node: {
      sha256: string;
      signature: { fingerprint: string; keySha256: string; sha256: string; url: string };
      url: string;
    };
    uv: { sha256: string; url: string };
  };
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
    expect(manifest.generatedFrom).toMatchObject({
      node: {
        sha256: "158f2e2c580c610b9cef2853f3444c7369b84cc23e7ad764e3c40e9d60d82ea0",
        signature: {
          fingerprint: "890C08DB8579162FEE0DF9DB8BEAB4DFCF555EF4",
          keySha256: "05a4080f671246086a2590bfad78965dcceaa823df1786f4ef52d58e5e3362b8",
          sha256: "259516b9d4fe69474373c02ac684edfe20c7675e6070e26a55fb514016f138d9",
        },
      },
      uv: { sha256: "8ef7fe76d67be3330e18e8d6ecbbb68f7a1ae46fe31198008170e911ad025c6a" },
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

  it.runIf(Boolean(spawnSync("gpg", ["--version"]).status === 0))(
    "verifies the Node checksum signature against the pinned release fingerprint",
    () => {
      expect(() =>
        execFileSync(process.execPath, [generatorPath, "--check", "--verify-signature"], { cwd: desktopRoot }),
      ).not.toThrow();
    },
  );

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
      expect(result.stderr).toContain("does not match the pinned authoritative file digest");
    } finally {
      rmSync(scratch, { force: true, recursive: true });
    }
  });

  it("records each tool's real in-archive layout, which differs between uv and Node", () => {
    // A wrong `executable` path is invisible to every other gate: the download
    // still matches its pinned SHA-256, and the failure only appears after
    // extraction, on the user's machine. That is exactly how a Windows
    // bootstrap shipped failing with "The verified uv archive did not contain
    // its expected executable".
    //
    // Node nests on every platform (`node-v<ver>-<target>/...`). uv nests in
    // its Unix tarballs but ships a FLAT Windows zip: uv.exe, uvw.exe and
    // uvx.exe sit at the archive root. Verified against the published
    // artefacts for the pinned versions.
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as ToolManifest;

    for (const [target, asset] of Object.entries(manifest.node.assets)) {
      expect(asset.executable, `node/${target} must nest under the archive basename`).toMatch(
        /^node-v[\d.]+-[a-z0-9-]+\//,
      );
    }

    for (const [target, asset] of Object.entries(manifest.uv.assets)) {
      if (target.startsWith("win32-")) {
        expect(asset.executable, `uv/${target} zip is flat — no directory prefix`).toBe("uv.exe");
      } else {
        expect(asset.executable, `uv/${target} tarball nests under the archive basename`).toMatch(
          /^uv-[a-z0-9_]+-[a-z0-9-]+\/uv$/,
        );
      }
    }
  });
});
