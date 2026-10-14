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
  "node-v26.11.1-SHASUMS256.txt",
);
const uvChecksums = path.join(
  desktopRoot,
  "resources",
  "bootstrap",
  "checksums",
  "uv-0.13.1-sha256.sum",
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
    pnpm: { sha256: string; snapshot: string; sources: string[] };
  };
  node: { assets: Record<string, ManifestAsset>; version: string };
  pnpm: { assets: Record<string, ManifestAsset>; integrity: string; packageManager: string; version: string };
  schemaVersion: number;
  uv: { assets: Record<string, ManifestAsset>; version: string };
}

describe("bootstrap tool manifest", () => {
  it("covers the release matrix with pinned authoritative digests", () => {
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as ToolManifest;
    const targets = ["darwin-arm64", "darwin-x64", "linux-arm64", "linux-x64", "win32-x64"];

    expect(manifest.schemaVersion).toBe(1);
    expect(manifest.node.version).toBe("26.11.1");
    expect(manifest.uv.version).toBe("0.13.1");
    expect(Object.keys(manifest.node.assets).sort()).toEqual(targets);
    expect(Object.keys(manifest.uv.assets).sort()).toEqual(targets);
    expect(Object.keys(manifest.pnpm.assets).sort()).toEqual(targets);
    expect(manifest.pnpm).toMatchObject({
      integrity: "sha512-25a51652a196785af5f28bda6dfe8dc582ebefa4ac1d180221ce1390231c5fb76637822ea4b6e4633ce74acdcb0a77f725af11bad38177fdeddaee818a955cb9",
      packageManager: "pnpm@12.11.2+sha512.25a51652a196785af5f28bda6dfe8dc582ebefa4ac1d180221ce1390231c5fb76637822ea4b6e4633ce74acdcb0a77f725af11bad38177fdeddaee818a955cb9",
      version: "12.11.2",
    });
    expect(manifest.generatedFrom).toMatchObject({
      node: {
        sha256: "75ff0c104acddb008964dd5feb88f58844b652820cb1cb01696f95031372b293",
        signature: {
          fingerprint: "5BE8A3F6C8A5C01D106C0AD820B1A390B168D356",
          keySha256: "5115095e2f8010c75da052ecb1cfb3af630e084f0f8daa93a863557b01b0f90a",
          sha256: "671e48de01184d7b0aa3df79c7aaa373ede2374231099973643a20311ed372f9",
        },
      },
      uv: { sha256: "8804e68a18189ed9750e6330db95c49310f320adb89e66dd429c92058f25e1e1" },
      pnpm: { sha256: "5e7a55df966ff3301e84eccfbd3bd6fe939d07415c1f4e96eed96dfc888fae1d" },
    });
    for (const asset of [...Object.values(manifest.node.assets), ...Object.values(manifest.uv.assets), ...Object.values(manifest.pnpm.assets)]) {
      expect(asset.sha256).toMatch(/^[0-9a-f]{64}$/);
      expect(asset.url).toMatch(/^https:\/\/(nodejs\.org|github\.com|registry\.npmjs\.org)\//);
      expect(asset.executable).not.toContain("..");
    }
  });

  it("labels the pnpm archive table as an app-owned derived snapshot", () => {
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    expect(manifest.generatedFrom.pnpm.snapshot).toBe("checksums/pnpm-12.11.2-assets.json");
    expect(manifest.generatedFrom.pnpm.sources).toEqual([
      "https://registry.npmjs.org/pnpm/12.11.2",
      ...["darwin-arm64", "darwin-x64", "linux-arm64", "linux-x64", "win32-x64"].map(
        (target) => `https://registry.npmjs.org/@pnpm/exe.${target}/12.11.2`,
      ),
    ]);
    expect(manifest.generatedFrom.pnpm.url).toBeUndefined();
  });

  it("is reproducible from the checked-in authoritative checksum snapshots", () => {
    expect(() => execFileSync(process.execPath, [generatorPath, "--check"], { cwd: desktopRoot })).not.toThrow();
  });

  it("packages the matching checksum, signature and native manager snapshots", () => {
    const verifier = readFileSync(path.join(desktopRoot, "scripts/verify-electron-package.mjs"), "utf8");
    for (const resource of [
      "checksums/node-release-key.asc",
      "checksums/node-v26.11.1-SHASUMS256.txt",
      "checksums/node-v26.11.1-SHASUMS256.txt.sig",
      "checksums/uv-0.13.1-sha256.sum",
      "checksums/pnpm-12.11.2-assets.json",
    ]) expect(verifier).toContain(JSON.stringify(resource));
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

  it("rejects altered native pnpm asset provenance before generation", () => {
    const scratch = mkdtempSync(path.join(tmpdir(), "flinttrade-pnpm-manifest-"));
    try {
      const snapshot = path.join(scratch, "pnpm-assets.json");
      const original = readFileSync(path.join(desktopRoot, "resources/bootstrap/checksums/pnpm-12.11.2-assets.json"), "utf8");
      writeFileSync(snapshot, original.replace("package/pnpm", "outside/pnpm"));
      const result = spawnSync(process.execPath, [generatorPath, "--check", "--pnpm-assets", snapshot], { encoding: "utf8" });
      expect(result.status).not.toBe(0);
      expect(result.stderr).toContain("pnpm asset snapshot does not match");
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

    for (const [target, asset] of Object.entries(manifest.pnpm.assets)) {
      expect(asset.archive).toBe("tar.gz");
      expect(asset.executable).toBe(target === "win32-x64" ? "package/pnpm.exe" : "package/pnpm");
      expect(asset.url).toBe(`https://registry.npmjs.org/@pnpm/exe.${target}/-/exe.${target}-12.11.2.tgz`);
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
