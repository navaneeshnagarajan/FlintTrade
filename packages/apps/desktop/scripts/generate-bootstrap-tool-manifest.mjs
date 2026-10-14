#!/usr/bin/env node

import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const desktopRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const nodeVersion = "26.11.1";
const uvVersion = "0.13.0";
const pnpmVersion = "12.11.2";
const authoritativeChecksumDigests = Object.freeze({
  node: "75ff0c104acddb008964dd5feb88f58844b652820cb1cb01696f95031372b293",
  uv: "dc052c54b83ec8a6c04899ce4ee66f9e7fda667bc56145747b78099d23ca22c7",
  pnpm: "5e7a55df966ff3301e84eccfbd3bd6fe939d07415c1f4e96eed96dfc888fae1d",
});
// Node releases are signed by whichever release manager cut them, so the pinned
// key travels WITH the pinned version - it is not a stable repository constant.
// Verify the current release's signature with its exact release-team key;
// a previously trusted key does not authorise a different release signature.
const nodeSignature = Object.freeze({
  fingerprint: "5BE8A3F6C8A5C01D106C0AD820B1A390B168D356",
  keySha256: "5115095e2f8010c75da052ecb1cfb3af630e084f0f8daa93a863557b01b0f90a",
  sha256: "671e48de01184d7b0aa3df79c7aaa373ede2374231099973643a20311ed372f9",
  url: `https://nodejs.org/dist/v${nodeVersion}/SHASUMS256.txt.sig`,
});
const targetFiles = {
  "darwin-arm64": {
    node: `node-v${nodeVersion}-darwin-arm64.tar.gz`,
    uv: "uv-aarch64-apple-darwin.tar.gz",
  },
  "darwin-x64": {
    node: `node-v${nodeVersion}-darwin-x64.tar.gz`,
    uv: "uv-x86_64-apple-darwin.tar.gz",
  },
  "linux-arm64": {
    node: `node-v${nodeVersion}-linux-arm64.tar.gz`,
    uv: "uv-aarch64-unknown-linux-gnu.tar.gz",
  },
  "linux-x64": {
    node: `node-v${nodeVersion}-linux-x64.tar.gz`,
    uv: "uv-x86_64-unknown-linux-gnu.tar.gz",
  },
  "win32-x64": {
    node: `node-v${nodeVersion}-win-x64.zip`,
    uv: "uv-x86_64-pc-windows-msvc.zip",
  },
};

function parseArgs(argv) {
  const options = {
    check: false,
    manifest: path.join(desktopRoot, "resources", "bootstrap", "tool-manifest.json"),
    nodeChecksums: path.join(
      desktopRoot,
      "resources",
      "bootstrap",
      "checksums",
      `node-v${nodeVersion}-SHASUMS256.txt`,
    ),
    nodeReleaseKey: path.join(desktopRoot, "resources", "bootstrap", "checksums", "node-release-key.asc"),
    nodeSignature: path.join(
      desktopRoot,
      "resources",
      "bootstrap",
      "checksums",
      `node-v${nodeVersion}-SHASUMS256.txt.sig`,
    ),
    uvChecksums: path.join(desktopRoot, "resources", "bootstrap", "checksums", `uv-${uvVersion}-sha256.sum`),
    pnpmAssets: path.join(desktopRoot, "resources", "bootstrap", "checksums", `pnpm-${pnpmVersion}-assets.json`),
    verifySignature: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--check") {
      options.check = true;
      continue;
    }
    if (argument === "--verify-signature") {
      options.verifySignature = true;
      continue;
    }
    const key = {
      "--manifest": "manifest",
      "--node-checksums": "nodeChecksums",
      "--node-release-key": "nodeReleaseKey",
      "--node-signature": "nodeSignature",
      "--uv-checksums": "uvChecksums",
      "--pnpm-assets": "pnpmAssets",
    }[argument];
    if (!key || !argv[index + 1]) throw new Error(`Unknown or incomplete argument: ${argument}`);
    options[key] = path.resolve(argv[index + 1]);
    index += 1;
  }
  return options;
}

function sha256(content) {
  return createHash("sha256").update(content).digest("hex");
}

function checksumTable(content, label) {
  const entries = new Map();
  for (const line of content.trim().split(/\r?\n/)) {
    const match = /^([0-9a-f]{64})\s+\*?(.+)$/.exec(line);
    if (!match) throw new Error(`Malformed ${label} checksum line: ${line}`);
    entries.set(match[2], match[1]);
  }
  return entries;
}

function archiveKind(file) {
  if (file.endsWith(".tar.gz")) return "tar.gz";
  if (file.endsWith(".zip")) return "zip";
  throw new Error(`Unsupported bootstrap archive: ${file}`);
}

function withoutArchiveSuffix(file) {
  return file.replace(/\.(?:tar\.gz|zip)$/, "");
}

function requiredDigest(table, file, label) {
  const digest = table.get(file);
  if (!digest) throw new Error(`${label} checksum source does not contain ${file}`);
  return digest;
}

export function generateManifest({ nodeChecksumContent, nodeReleaseKeyContent, nodeSignatureContent, packageContent, uvChecksumContent, pnpmAssetContent }) {
  if (sha256(nodeChecksumContent) !== authoritativeChecksumDigests.node) {
    throw new Error("Node checksum snapshot does not match the pinned authoritative file digest.");
  }
  if (sha256(uvChecksumContent) !== authoritativeChecksumDigests.uv) {
    throw new Error("uv checksum snapshot does not match the pinned authoritative file digest.");
  }
  if (sha256(pnpmAssetContent) !== authoritativeChecksumDigests.pnpm) {
    throw new Error("pnpm asset snapshot does not match the pinned authoritative file digest.");
  }
  if (sha256(nodeSignatureContent) !== nodeSignature.sha256) {
    throw new Error("Node checksum signature does not match its pinned authoritative digest.");
  }
  if (sha256(nodeReleaseKeyContent) !== nodeSignature.keySha256) {
    throw new Error("Node release key does not match its pinned authoritative digest.");
  }
  const packageMetadata = JSON.parse(packageContent);
  const pnpmSnapshot = JSON.parse(pnpmAssetContent);
  const packageManager = /^pnpm@(\d+\.\d+\.\d+)\+(sha512)\.([0-9a-f]{128})$/.exec(packageMetadata.packageManager ?? "");
  if (!packageManager || packageManager[1] !== pnpmVersion || packageMetadata.packageManager !== pnpmSnapshot.packageManager) {
    throw new Error(`The repository packageManager must integrity-pin the verified pnpm ${pnpmVersion} release.`);
  }
  const nodeChecksums = checksumTable(nodeChecksumContent, "Node");
  const uvChecksums = checksumTable(uvChecksumContent, "uv");
  const nodeAssets = {};
  const uvAssets = {};

  for (const [target, files] of Object.entries(targetFiles)) {
    const windows = target.startsWith("win32-");
    nodeAssets[target] = {
      archive: archiveKind(files.node),
      executable: `${withoutArchiveSuffix(files.node)}/${windows ? "node.exe" : "bin/node"}`,
      sha256: requiredDigest(nodeChecksums, files.node, "Node"),
      url: `https://nodejs.org/dist/v${nodeVersion}/${files.node}`,
    };
    uvAssets[target] = {
      archive: archiveKind(files.uv),
      // uv packages its two archive kinds differently, unlike Node which always
      // nests. The Unix tarballs contain `<archive-basename>/uv`, but the
      // Windows zip is FLAT — `uv.exe`, `uvw.exe` and `uvx.exe` sit at the
      // archive root with no directory prefix. Prefixing the basename on
      // Windows produced a path no extracted tree ever contained, so every
      // Windows bootstrap failed after passing SHA-256 verification with
      // "The verified uv archive did not contain its expected executable".
      executable: windows ? "uv.exe" : `${withoutArchiveSuffix(files.uv)}/uv`,
      sha256: requiredDigest(uvChecksums, files.uv, "uv"),
      url: `https://github.com/astral-sh/uv/releases/download/${uvVersion}/${files.uv}`,
    };
  }

  return {
    schemaVersion: 1,
    generatedFrom: {
      node: {
        sha256: sha256(nodeChecksumContent),
        signature: nodeSignature,
        url: `https://nodejs.org/dist/v${nodeVersion}/SHASUMS256.txt`,
      },
      uv: {
        sha256: sha256(uvChecksumContent),
        url: `https://github.com/astral-sh/uv/releases/download/${uvVersion}/sha256.sum`,
      },
      pnpm: {
        // This table is app-owned, derived from the platform archives checked
        // against npm's published dist.integrity, not an upstream checksum body.
        sha256: sha256(pnpmAssetContent),
        snapshot: `checksums/pnpm-${pnpmVersion}-assets.json`,
        sources: [
          `https://registry.npmjs.org/pnpm/${pnpmVersion}`,
          ...Object.keys(targetFiles).map((target) => `https://registry.npmjs.org/@pnpm/exe.${target}/${pnpmVersion}`),
        ],
      },
    },
    node: { version: nodeVersion, assets: nodeAssets },
    pnpm: {
      assets: pnpmSnapshot.assets,
      version: packageManager[1],
      integrity: `${packageManager[2]}-${packageManager[3]}`,
      packageManager: packageMetadata.packageManager,
    },
    uv: { version: uvVersion, assets: uvAssets },
  };
}

// GnuPG exits 0 and still emits VALIDSIG for a signature made by a key that has
// since expired or been revoked - it reports that condition out of band, as
// EXPKEYSIG or REVKEYSIG *instead of* GOODSIG. So gating on
// "status === 0 && VALIDSIG <fingerprint>" accepted an expired key outright:
// NO_PUBKEY and BADSIG were the only failures it could ever catch.
//
// That is not hypothetical here. The pinned Node release key expired on
// 2026-07-08, and the checked-in v22.23.1 signature verifies against it with
// EXPKEYSIG, VALIDSIG and exit status 0 all present together.
//
// Fail closed instead: require the positive GOODSIG that only a currently-valid
// key produces, require VALIDSIG to name the pinned fingerprint, and reject
// every status line that marks the key or signature as anything else.
const FATAL_GPG_STATUS = Object.freeze([
  "EXPKEYSIG",
  "REVKEYSIG",
  "EXPSIG",
  "ERRSIG",
  "BADSIG",
  "NO_PUBKEY",
  "KEYEXPIRED",
  "KEYREVOKED",
]);

function assertGpgReportedACurrentlyValidKey(verified) {
  const status = verified.stdout ?? "";
  const fatal = FATAL_GPG_STATUS.filter((code) => status.includes(`[GNUPG:] ${code}`));
  if (fatal.length > 0) {
    throw new Error(
      `Node checksum signature was made by a key gpg reports as ${fatal.join(", ")}; ` +
        "refresh the pinned release key rather than bypassing this check.",
    );
  }
  if (!status.includes("[GNUPG:] GOODSIG ")) {
    throw new Error("Node checksum signature produced no GOODSIG; the pinned release key is not currently valid.");
  }
  if (!status.includes(`[GNUPG:] VALIDSIG ${nodeSignature.fingerprint} `)) {
    throw new Error(
      `Node checksum signature did not validate against the pinned release fingerprint ${nodeSignature.fingerprint}.`,
    );
  }
  if (verified.status !== 0) {
    throw new Error(verified.stderr || "gpg exited non-zero while verifying the Node checksum signature.");
  }
}

// Git for Windows ships an MSYS gpg that cannot parse a "C:\..." argument: it
// reads the drive letter as a relative segment, prepends the working directory,
// and dies with "no writable keyring found" before verifying anything. That made
// --verify-signature unusable on a Windows developer host - the one place a
// maintainer would run it by hand - so signature verification only ever ran in
// CI. cygpath performs the conversion that build expects; its absence means gpg
// is a native build that wants the Windows path unchanged.
function gpgHomedirArgument(home) {
  if (process.platform !== "win32") return home;
  const converted = spawnSync("cygpath", ["-u", home], { encoding: "utf8" });
  if (converted.status !== 0 || !converted.stdout?.trim()) return home;
  return converted.stdout.trim();
}

function verifyNodeSignature(options) {
  const home = mkdtempSync(path.join(tmpdir(), "flinttrade-node-signature-"));
  const homeArgument = gpgHomedirArgument(home);
  try {
    const imported = spawnSync(
      "gpg",
      ["--homedir", homeArgument, "--batch", "--status-fd", "1", "--import", options.nodeReleaseKey],
      { encoding: "utf8" },
    );
    if (imported.status !== 0) throw new Error(imported.stderr || "Could not import the pinned Node release key.");
    const verified = spawnSync(
      "gpg",
      [
        "--homedir",
        homeArgument,
        "--batch",
        "--status-fd",
        "1",
        "--verify",
        options.nodeSignature,
        options.nodeChecksums,
      ],
      { encoding: "utf8" },
    );
    assertGpgReportedACurrentlyValidKey(verified);
  } finally {
    rmSync(home, { force: true, recursive: true });
  }
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.verifySignature) verifyNodeSignature(options);
  const output = `${JSON.stringify(
    generateManifest({
      nodeChecksumContent: readFileSync(options.nodeChecksums, "utf8"),
      nodeReleaseKeyContent: readFileSync(options.nodeReleaseKey),
      nodeSignatureContent: readFileSync(options.nodeSignature),
      packageContent: readFileSync(path.resolve(desktopRoot, "../../..", "package.json"), "utf8"),
      uvChecksumContent: readFileSync(options.uvChecksums, "utf8"),
      pnpmAssetContent: readFileSync(options.pnpmAssets, "utf8"),
    }),
    null,
    2,
  )}\n`;

  if (options.check) {
    if (readFileSync(options.manifest, "utf8") !== output) {
      console.error("Bootstrap tool manifest is out of date with its checksum sources.");
      process.exitCode = 1;
    }
    return;
  }
  writeFileSync(options.manifest, output);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
