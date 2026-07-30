#!/usr/bin/env node

import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const desktopRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const nodeVersion = "22.23.2";
const uvVersion = "0.11.16";
const authoritativeChecksumDigests = Object.freeze({
  node: "778ac5b2fcdbd68d9c0ae9f4310674faa3af0910bd0d18e7f6597787c40a3e39",
  uv: "8ef7fe76d67be3330e18e8d6ecbbb68f7a1ae46fe31198008170e911ad025c6a",
});
// Node releases are signed by whichever release manager cut them, so the pinned
// key travels WITH the pinned version - it is not a stable repository constant.
// v22.23.1 was signed by Rafael Gonzaga, whose key expired on 2026-07-08; there
// is therefore no currently-valid key for that release, and the only route to a
// verifiable signature is a version signed by a key that has not expired.
// v22.23.2 is signed by Marco Ippolito (key valid to 2034-03), which is why the
// version bump and the key swap are one change rather than two.
const nodeSignature = Object.freeze({
  fingerprint: "CC68F5A3106FF448322E48ED27F5E38D5B0A215F",
  keySha256: "9c51e903b0da945fc21947fd6fce8fb4d72bc20ddf82e8f0aada694e9688447d",
  sha256: "169f1452c14cd653247408352f1534b9f31e3d13f9c6399c3977368095e11eda",
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
    nodeReleaseKey: path.join(desktopRoot, "resources", "bootstrap", "checksums", "node-release-marco-ippolito.asc"),
    nodeSignature: path.join(
      desktopRoot,
      "resources",
      "bootstrap",
      "checksums",
      `node-v${nodeVersion}-SHASUMS256.txt.sig`,
    ),
    uvChecksums: path.join(desktopRoot, "resources", "bootstrap", "checksums", `uv-${uvVersion}-sha256.sum`),
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

export function generateManifest({ nodeChecksumContent, nodeReleaseKeyContent, nodeSignatureContent, packageContent, uvChecksumContent }) {
  if (sha256(nodeChecksumContent) !== authoritativeChecksumDigests.node) {
    throw new Error("Node checksum snapshot does not match the pinned authoritative file digest.");
  }
  if (sha256(uvChecksumContent) !== authoritativeChecksumDigests.uv) {
    throw new Error("uv checksum snapshot does not match the pinned authoritative file digest.");
  }
  if (sha256(nodeSignatureContent) !== nodeSignature.sha256) {
    throw new Error("Node checksum signature does not match its pinned authoritative digest.");
  }
  if (sha256(nodeReleaseKeyContent) !== nodeSignature.keySha256) {
    throw new Error("Node release key does not match its pinned authoritative digest.");
  }
  const packageMetadata = JSON.parse(packageContent);
  const packageManager = /^pnpm@(\d+\.\d+\.\d+)\+(sha512)\.([0-9a-f]+)$/.exec(packageMetadata.packageManager ?? "");
  if (!packageManager || packageManager[1] !== "9.15.0") {
    throw new Error("The repository packageManager must integrity-pin pnpm 9.15.0.");
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
    },
    node: { version: nodeVersion, assets: nodeAssets },
    pnpm: {
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

function verifyNodeSignature(options) {
  const home = mkdtempSync(path.join(tmpdir(), "flinttrade-node-signature-"));
  try {
    const imported = spawnSync(
      "gpg",
      ["--homedir", home, "--batch", "--status-fd", "1", "--import", options.nodeReleaseKey],
      { encoding: "utf8" },
    );
    if (imported.status !== 0) throw new Error(imported.stderr || "Could not import the pinned Node release key.");
    const verified = spawnSync(
      "gpg",
      [
        "--homedir",
        home,
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
