import { execFileSync, spawnSync } from "node:child_process";
import { chmodSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { describe, expect, it } from "vitest";

const resourceRoot = path.resolve(import.meta.dirname, "..", "resources", "bootstrap");
const posixScript = path.join(resourceRoot, "flinttrade-bootstrap.sh");
const powershellScript = path.join(resourceRoot, "flinttrade-bootstrap.ps1");
const probeRunner = path.resolve(import.meta.dirname, "..", "scripts", "run-bootstrap-probe.mjs");
const windowsSupervisorBuilder = path.resolve(
  import.meta.dirname,
  "..",
  "scripts",
  "build-windows-job-supervisor.mjs",
);
const atomicPromoterBuilder = path.resolve(
  import.meta.dirname,
  "..",
  "scripts",
  "build-atomic-promoter.mjs",
);
const windowsSourceFilesystem = path.resolve(
  import.meta.dirname,
  "..",
  "native",
  "windows-source-filesystem",
  "Program.cs",
);
const windowsSupervisor = path.resolve(
  import.meta.dirname,
  "..",
  "native",
  "windows-job-supervisor",
  "Program.cs",
);
const electronBundler = path.resolve(import.meta.dirname, "..", "scripts", "bundle-electron.mjs");
const desktopPackage = path.resolve(import.meta.dirname, "..", "package.json");

describe("packaged bootstrap entrypoints", () => {
  it("ships an inert exact Git common-directory scaffold", () => {
    const common = path.join(resourceRoot, "git-common");
    expect(readdirSync(common).sort()).toEqual(["objects", "refs"]);
    for (const [directory, content] of [
      ["objects", "FlintTrade hardened Git object-directory sentinel.\n"],
      ["refs", "FlintTrade hardened Git ref-directory sentinel.\n"],
    ] as const) {
      const target = path.join(common, directory);
      expect(lstatSync(target).isDirectory()).toBe(true);
      expect(readdirSync(target)).toEqual([".flinttrade-empty"]);
      expect(readFileSync(path.join(target, ".flinttrade-empty"), "utf8")).toBe(content);
    }
  });

  it.runIf(process.platform !== "win32")("passes the system POSIX shell syntax check", () => {
    expect(() => execFileSync("sh", ["-n", posixScript])).not.toThrow();
  });

  it.runIf(process.platform !== "win32")(
    "runs from a clean PATH with Corepack using the verified Node executable",
    () => {
      const root = mkdtempSync(path.join(tmpdir(), "flinttrade-bootstrap-entrypoint-"));
      try {
        const candidate = path.join(root, "workspace", "source", "FlintTrade.candidate-1");
        const tools = path.join(root, "workspace", "tools");
        const node = path.join(tools, "node", "bin", "node");
        const corepack = path.join(tools, "node", "lib", "node_modules", "corepack", "dist", "corepack.js");
        const uv = path.join(tools, "uv", "uv");
        for (const required of [
          "package.json",
          "pyproject.toml",
          "uv.lock",
          "pnpm-lock.yaml",
          "packages/apps/terminal/package.json",
        ]) {
          const target = path.join(candidate, required);
          mkdirSync(path.dirname(target), { recursive: true });
          writeFileSync(target, "{}\n");
        }
        mkdirSync(path.dirname(node), { recursive: true });
        mkdirSync(path.dirname(corepack), { recursive: true });
        mkdirSync(path.dirname(uv), { recursive: true });
        writeFileSync(
          node,
          `#!/bin/sh
if [ "\${1-}" = "--version" ]; then printf '%s\\n' v22.23.1; exit 0; fi
case "\${1-}" in */corepack.js) shift;; *) exit 71;; esac
[ "\${COREPACK_DEFAULT_TO_LATEST-}" = 0 ] || exit 72
[ -n "\${COREPACK_HOME-}" ] || exit 73
if [ "\${1-}" = "--version" ]; then printf '%s\\n' 0.29.4; exit 0; fi
if [ "\${1-}" = pnpm ] && [ "\${2-}" = "--version" ]; then printf '%s\\n' 9.15.0; fi
exit 0
`,
        );
        writeFileSync(corepack, "#!/usr/bin/env node\n");
        writeFileSync(
          uv,
          `#!/bin/sh
[ "\${UV_NO_EDITABLE-}" = 1 ] || exit 74
[ -n "\${UV_CACHE_DIR-}" ] || exit 75
[ -n "\${UV_PYTHON_INSTALL_DIR-}" ] || exit 76
exit 0
`,
        );
        for (const executable of [node, corepack, uv]) chmodSync(executable, 0o755);

        expect(() =>
          execFileSync("/bin/sh", [posixScript, candidate, uv, node, corepack, tools, "9.15.0"], {
            env: { PATH: "/usr/bin:/bin" },
          }),
        ).not.toThrow();
      } finally {
        rmSync(root, { force: true, recursive: true });
      }
    },
  );

  it("uses frozen locks, exact pnpm and no privileged or remote-script execution", () => {
    const posix = readFileSync(posixScript, "utf8");
    const powershell = readFileSync(powershellScript, "utf8");
    const combined = `${posix}\n${powershell}`;

    expect(combined).toContain("sync --frozen --all-packages --no-install-package flinttrade-ticks");
    expect(combined).toContain('"--frozen", "--all-packages", "--no-install-package", "flinttrade-ticks"');
    expect(combined).toContain("pnpm 9.15.0");
    expect(combined).toContain("--frozen-lockfile");
    expect(combined).toContain("COREPACK_HOME");
    expect(combined).toContain("UV_CACHE_DIR");
    expect(combined).toContain("UV_NO_EDITABLE");
    expect(combined).toContain("UV_PYTHON_INSTALL_DIR");
    expect(posix).toContain('"$uv" venv --relocatable --python 3.12 .venv');
    expect(powershell).toContain(
      'Invoke-Checked $Uv @("venv", "--relocatable", "--python", "3.12", ".venv")',
    );
    expect(posix.indexOf('"$uv" venv --relocatable')).toBeLessThan(
      posix.indexOf('"$uv" sync --frozen'),
    );
    expect(powershell.indexOf('Invoke-Checked $Uv @("venv", "--relocatable"')).toBeLessThan(
      powershell.indexOf('Invoke-Checked $Uv @("sync", "--frozen"'),
    );
    expect(posix.indexOf("export PATH")).toBeLessThan(posix.indexOf('"$node" "$corepack_js" --version'));
    expect(powershell.indexOf("$env:PATH")).toBeLessThan(
      powershell.indexOf('Invoke-Checked $Node @($CorepackJs, "--version")'),
    );
    expect(powershell).not.toContain("corepack.cmd");
    expect(combined).not.toMatch(/\b(?:sudo|doas|apt(?:-get)?|dnf|yum|brew|choco|winget)\b/i);
    expect(combined).not.toMatch(/(?:curl|wget|Invoke-WebRequest|irm)\b[^\n|]*\|/i);
    expect(combined).not.toMatch(/\bInvoke-Expression\b|\biex\b/i);
  });

  it("bundles the real probe with the same CommonJS boundary as Electron main", () => {
    const source = readFileSync(probeRunner, "utf8");

    expect(source).toContain("createRequire(import.meta.url)");
  });

  it("runs the no-shell Windows supervisor compiler on every standard bundle path", () => {
    const builder = readFileSync(windowsSupervisorBuilder, "utf8");
    const metadata = JSON.parse(readFileSync(desktopPackage, "utf8")) as { scripts: Record<string, string> };

    expect(metadata.scripts.bundle).toContain("build-windows-job-supervisor.mjs");
    expect(metadata.scripts["bundle:dev"]).toContain("build-windows-job-supervisor.mjs");
    expect(metadata.scripts["pack:dir:win"]).toContain("build-windows-job-supervisor.mjs");
    expect(metadata.scripts["pack:dir:win"]).toContain("bundle-electron.mjs");
    expect(metadata.scripts["pack:dir:win"]).toContain("run-electron-builder.mjs");
    expect(metadata.scripts["pack:dir:win"]).not.toContain("pnpm run");
    expect(builder).toContain('"Microsoft.NET", "Framework64", "v4.0.30319", "csc.exe"');
    expect(builder).toContain("execFileSync(");
    expect(builder).toContain("windows-source-filesystem");
    expect(builder).toContain("flinttrade-source-fs.exe");
    expect(builder).toContain("flinttrade-source-fs.sha256.json");
    expect(builder).toContain('createHash("sha256")');
    expect(builder).not.toContain("shell:");
  });

  it("builds, packages, and verifies the digest-bound POSIX atomic promoter", () => {
    const builder = readFileSync(atomicPromoterBuilder, "utf8");
    const metadata = JSON.parse(readFileSync(desktopPackage, "utf8")) as {
      build: {
        files: string[];
        linux: { extraResources: Array<{ from: string; to: string }> };
        mac: { extraResources: Array<{ from: string; to: string }>; signIgnore: string };
      };
      scripts: Record<string, string>;
    };

    for (const script of ["dev", "start", "test", "test:electron", "bundle", "bundle:dev", "build", "pack:mac", "pack:linux:x64", "pack:linux:arm64", "probe:bootstrap"]) {
      if (script === "probe:bootstrap") {
        expect(readFileSync(probeRunner, "utf8")).toContain("build-atomic-promoter.mjs");
      } else {
        expect(metadata.scripts[script]).toContain("build-atomic-promoter.mjs");
      }
    }
    expect(metadata.scripts["test:atomic-promoter"]).toContain("run-required-atomic-promoter-test.mjs");
    expect(builder).toContain('"flinttrade-fs-promoter.node"');
    expect(builder).toContain('"flinttrade-fs-promoter.sha256.json"');
    expect(builder).toContain('"darwin-universal"');
    expect(builder).toContain('`linux-${process.arch}`');
    expect(builder).toContain("rmSync(outputDirectory, { force: true, recursive: true })");
    expect(builder).toContain('const codesign = "/usr/bin/codesign"');
    expect(builder).toContain("FLINTTRADE_NATIVE_MAC_IDENTITY");
    expect(metadata.build.mac.signIgnore).toBe("flinttrade-fs-promoter\\.node$");
    expect(metadata.build.files).not.toContain("dist/**");
    expect(metadata.build.files).toEqual(expect.arrayContaining([
      "dist/electron-main.mjs",
      "dist/electron-preload.js",
    ]));
    for (const resources of [metadata.build.mac.extraResources, metadata.build.linux.extraResources]) {
      expect(resources.some(({ to }) => to === "bootstrap/flinttrade-fs-promoter.node")).toBe(true);
      expect(resources.some(({ to }) => to === "bootstrap/flinttrade-fs-promoter.sha256.json")).toBe(true);
    }
  });

  it("binds the Windows source helper build digest through the exact Job-supervised launch", () => {
    const supervisor = readFileSync(windowsSupervisor, "utf8");
    const bundler = readFileSync(electronBundler, "utf8");

    expect(supervisor).toContain('args[index] == "--target-sha256"');
    expect(supervisor).toContain("OpenAndVerifyTarget(options)");
    expect(supervisor).toContain("HashHandle(handle)");
    expect(supervisor).toContain("FILE_SHARE_READ,");
    expect(supervisor).toContain("CreateProcessW(");
    expect(bundler).toContain("__FLINTTRADE_WINDOWS_SOURCE_FS_SHA256__");
    expect(bundler).toContain("flinttrade-source-fs.sha256.json");
  });

  it("packages the native Windows file-ID and handle-bound source mutation boundary", () => {
    const helper = readFileSync(windowsSourceFilesystem, "utf8");
    const metadata = JSON.parse(readFileSync(desktopPackage, "utf8")) as {
      build: { win: { extraResources: Array<{ from: string; to: string }> } };
    };

    expect(helper).toContain("GetFileInformationByHandleEx");
    expect(helper).toContain("FILE_ID_INFO_CLASS");
    expect(helper).toContain("FILE_FLAG_OPEN_REPARSE_POINT");
    expect(helper).toContain("SetFileInformationByHandle");
    expect(helper).toContain("FILE_RENAME_INFO_CLASS");
    expect(helper).toContain("FILE_DISPOSITION_INFO_CLASS");
    expect(helper).toContain("exclusiveMutation ? 0 : FILE_SHARE_DELETE");
    expect(helper).toContain("(shareWrite ? FILE_SHARE_WRITE : 0)");
    expect(helper).toContain("OpenJournalMutationPinned(temporary, false, true)");
    expect(helper).toContain("OpenJournalMutationPinned(path, true, false)");
    expect(helper).toContain("FlushPinnedDirectory(parentEntry)");
    expect(helper).toContain("DURABILITY_UNAVAILABLE");
    expect(helper).toContain("AMBIGUOUS_EVIDENCE");
    expect(helper).toContain('options.Command == "quarantine-directory"');
    expect(helper).toContain('options.Command == "recover-journal"');
    expect(helper).toContain('options.Command == "remove-quarantined-directory"');
    expect(helper).toContain("RequireExpected(child, evidence.Identity)");
    expect(helper).toContain("evidence.IsDirectory && !evidence.IsReparsePoint");
    expect(helper).toContain("MAX_RECLAMATION_ENTRIES - reclaimedEntries");
    expect(helper).toContain("observedEntries >= remainingEntryBudget");
    expect(helper).toContain("FILE_FLAG_OPEN_REPARSE_POINT");
    expect(helper).toContain("RequireWithinCanonicalRoot(canonicalRoot, child.CanonicalPath)");
    expect(helper).toContain("OpenExpectedJournalEntry(target, expectedTarget)");
    expect(helper).toContain("RequireExpectedJournalState(");
    expect(helper).toContain("CreateJournalTransactionReceipt(");
    expect(helper).toContain("ReconcileJournalTransaction(");
    expect(helper).toContain("JournalTransaction.ReceiptPath(");
    expect(helper).toContain("DeletePinnedEntry(receiptEntry, parentEntry, receipt)");
    expect(helper.match(/if \(!expectedPrevious\.IsMissing\)/g)).toHaveLength(2);
    expect(helper).not.toContain("MarkDelete(previousEntry)");
    expect(helper).toContain("Marshal.AllocHGlobal(1)");
    expect(helper).toContain("Marshal.WriteByte(information, 0, 1)");
    expect(helper).toContain("FindFirstFileW");
    expect(helper).toContain("FindNextFileW");
    expect(helper).not.toContain("DeleteFileW");
    expect(helper).not.toContain("RemoveDirectoryW");
    expect(metadata.build.win.extraResources).toContainEqual({
      from: "dist/native/win32-x64/flinttrade-source-fs.exe",
      to: "bootstrap/flinttrade-source-fs.exe",
    });
    expect(metadata.build.win.extraResources).toContainEqual({
      from: "dist/native/win32-x64/flinttrade-source-fs.sha256.json",
      to: "bootstrap/flinttrade-source-fs.sha256.json",
    });
  });

  it.runIf(process.platform === "win32" || Boolean(process.env.CI))(
    "parses the PowerShell entrypoint when PowerShell is available",
    () => {
      const executable = process.platform === "win32" ? "powershell.exe" : "pwsh";
      const probe = spawnSync(executable, ["-NoProfile", "-NonInteractive", "-Command", "exit 0"]);
      if (probe.error) return;
      // The script path travels in the environment, not as a trailing argv
      // entry: in -Command mode PowerShell does NOT populate $args from
      // trailing arguments, so `$args[0]` was null and Get-Content failed with
      // exit 1. This test only runs on CI (or Windows), so that never surfaced
      // locally. An environment variable also sidesteps quoting for paths
      // containing spaces.
      const parsed = spawnSync(
        executable,
        [
          "-NoProfile",
          "-NonInteractive",
          "-Command",
          "[void][scriptblock]::Create((Get-Content -Raw -LiteralPath $env:FLINTTRADE_PS_SCRIPT))",
        ],
        { env: { ...process.env, FLINTTRADE_PS_SCRIPT: powershellScript } },
      );
      expect(parsed.status, parsed.stderr?.toString() ?? "").toBe(0);
    },
    // PowerShell cold start on the Linux runner is genuinely slow -- measured
    // at 8036 ms against vitest's 5000 ms default, and this spawns it TWICE
    // (probe, then parse). The failure was a startup-time timeout, not a parse
    // error, so the budget needs to reflect what pwsh actually costs rather
    // than what a fast local shell costs.
    30_000,
  );
});
