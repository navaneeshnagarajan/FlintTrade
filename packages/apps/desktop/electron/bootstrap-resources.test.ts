import { execFileSync, spawnSync } from "node:child_process";
import {
  chmodSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
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
    "reuses a validated POSIX virtual environment with the verified tools",
    () => {
      const root = mkdtempSync(path.join(tmpdir(), "flinttrade-bootstrap-entrypoint-"));
      try {
        const candidate = path.join(root, "workspace", "source", "FlintTrade.[candidate]-1");
        const tools = path.join(root, "workspace", "tools");
        const node = path.join(tools, "node", "bin", "node");
        const corepack = path.join(tools, "node", "lib", "node_modules", "corepack", "dist", "corepack.js");
        const uv = path.join(tools, "uv", "uv");
        const pythonVersionRoot = path.join(tools, "python", "cpython-3.12.0");
        const pythonAlias = path.join(tools, "python", "cpython-3.12");
        const pythonHome = path.join(pythonAlias, "bin");
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
        const staleEnvironmentFile = path.join(candidate, ".venv", "stale");
        mkdirSync(path.dirname(staleEnvironmentFile), { recursive: true });
        writeFileSync(staleEnvironmentFile, "stale\n");
        mkdirSync(path.join(pythonVersionRoot, "bin"), { recursive: true });
        writeFileSync(path.join(pythonVersionRoot, "bin", "python3.12"), "managed python fixture\n");
        symlinkSync(pythonVersionRoot, pythonAlias, "junction");
        const environment = path.join(candidate, ".venv");
        mkdirSync(path.join(environment, "lib"));
        mkdirSync(path.join(environment, "bin"));
        symlinkSync("lib", path.join(environment, "lib64"), "dir");
        symlinkSync(`${pythonHome}/python3.12`, path.join(environment, "bin", "python"), "file");
        symlinkSync("python", path.join(environment, "bin", "python3"), "file");
        symlinkSync("python", path.join(environment, "bin", "python3.12"), "file");
        writeFileSync(
          path.join(candidate, ".venv", "pyvenv.cfg"),
          `home = ${pythonHome}\nuv = 0.11.16\nversion_info = 3.12.0\nrelocatable = true\n`,
        );
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
if [ "\${1-}" = pnpm ] && [ "\${2-}" = "--version" ]; then printf '%s\\n' 10.34.5; fi
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
if [ -e .venv ]; then
  case "\${1-}" in python|venv) exit 77;; esac
fi
if [ "\${1-}" = venv ]; then
  for argument in "\$@"; do
    [ "\$argument" != --allow-existing ] || exit 78
  done
  mkdir .venv
  printf '%s\n' 'home = ${pythonHome}' 'uv = 0.11.16' 'version_info = 3.12.0' 'relocatable = true' > .venv/pyvenv.cfg
fi
exit 0
`,
        );
        for (const executable of [node, corepack, uv]) chmodSync(executable, 0o755);

        expect(() =>
          execFileSync("/bin/sh", [posixScript, candidate, uv, node, corepack, tools, "10.34.5"], {
            env: { PATH: "/usr/bin:/bin" },
          }),
        ).not.toThrow();
        expect(readFileSync(staleEnvironmentFile, "utf8")).toBe("stale\n");
        rmSync(path.join(candidate, ".venv"), { force: true, recursive: true });
        expect(() =>
          execFileSync("/bin/sh", [posixScript, candidate, uv, node, corepack, tools, "10.34.5"], {
            env: { PATH: "/usr/bin:/bin" },
          }),
        ).not.toThrow();
        expect(readFileSync(path.join(candidate, ".venv", "pyvenv.cfg"), "utf8")).toContain(
          "version_info = 3.12.0",
        );
      } finally {
        rmSync(root, { force: true, recursive: true });
      }
    },
  );

  it.runIf(process.platform === "win32")(
    "reuses a validated Windows virtual environment with the verified tools",
    () => {
      const root = mkdtempSync(path.join(tmpdir(), "flinttrade-bootstrap-entrypoint-"));
      try {
        const candidate = path.join(root, "workspace", "source", "FlintTrade.[candidate]-1");
        const tools = path.join(root, "workspace", "tools");
        const node = path.join(tools, "node.cmd");
        const uv = path.join(tools, "uv.cmd");
        const corepack = path.join(tools, "corepack.js");
        const pythonVersionRoot = path.join(tools, "python", "cpython-3.12.0");
        const pythonAlias = path.join(tools, "python", "cpython-3.12");
        const pythonHome = path.join(pythonAlias, "bin");
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
        const staleEnvironmentFile = path.join(candidate, ".venv", "stale");
        mkdirSync(path.dirname(staleEnvironmentFile), { recursive: true });
        writeFileSync(staleEnvironmentFile, "stale\n");
        mkdirSync(path.join(pythonVersionRoot, "bin"), { recursive: true });
        symlinkSync(pythonVersionRoot, pythonAlias, "junction");
        writeFileSync(
          path.join(candidate, ".venv", "pyvenv.cfg"),
          `home = ${pythonHome}\nuv = 0.11.16\nversion_info = 3.12.0\nrelocatable = true\n`,
        );
        mkdirSync(tools, { recursive: true });
        writeFileSync(corepack, "// verified Corepack fixture\n");
        writeFileSync(
          node,
          `@echo off
if "%~1"=="--version" (
  echo v22.23.2
  exit /b 0
)
if "%~2"=="--version" (
  echo 0.34.6
  exit /b 0
)
if "%~2"=="pnpm" if "%~3"=="--version" (
  echo 10.34.5
  exit /b 0
)
exit /b 0
`,
        );
        writeFileSync(
          uv,
          `@echo off
setlocal
if "%~1"=="--version" exit /b 0
if not "%UV_NO_EDITABLE%"=="1" exit /b 74
if exist .venv if "%~1"=="python" exit /b 77
if exist .venv if "%~1"=="venv" exit /b 77
if "%~1"=="venv" goto venv
exit /b 0
:venv
:scan
if "%~1"=="" goto scanned
if "%~1"=="--allow-existing" exit /b 78
shift
goto scan
:scanned
mkdir .venv
exit /b 0
`,
        );

        const result = spawnSync(
          "powershell.exe",
          [
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            powershellScript,
            "-Candidate",
            candidate,
            "-Uv",
            uv,
            "-Node",
            node,
            "-CorepackJs",
            corepack,
            "-ToolsRoot",
            tools,
            "-PnpmVersion",
            "10.34.5",
          ],
          { encoding: "utf8" },
        );

        expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
        expect(readFileSync(staleEnvironmentFile, "utf8")).toBe("stale\n");
        rmSync(path.join(candidate, ".venv"), { force: true, recursive: true });
        const freshResult = spawnSync(
          "powershell.exe",
          [
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            powershellScript,
            "-Candidate",
            candidate,
            "-Uv",
            uv,
            "-Node",
            node,
            "-CorepackJs",
            corepack,
            "-ToolsRoot",
            tools,
            "-PnpmVersion",
            "10.34.5",
          ],
          { encoding: "utf8" },
        );
        expect(freshResult.status, `${freshResult.stdout}\n${freshResult.stderr}`).toBe(0);
        expect(lstatSync(path.join(candidate, ".venv")).isDirectory()).toBe(true);
      } finally {
        rmSync(root, { force: true, recursive: true });
      }
    },
    30_000,
  );

  it.each([
    "top-level-link",
    "nested-directory-link",
    "nested-file-link",
    "malformed-directory",
    "missing-uv-metadata",
    "wrong-python-version",
    "not-relocatable",
    "external-python-home",
    "linked-python-root",
    "fresh-linked-python-root",
  ] as const)(
    "refuses an unsafe %s virtual environment before invoking managed tools",
    (scenario) => {
      const root = mkdtempSync(path.join(tmpdir(), "flinttrade-bootstrap-linked-venv-"));
      try {
        const candidate = path.join(root, "candidate.[brackets]");
        const outside = path.join(root, "outside");
        const tools = path.join(root, "tools");
        let pythonHome = path.join(tools, "python", "cpython-3.12", "bin");
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
        mkdirSync(outside, { recursive: true });
        const sentinel = path.join(outside, "sentinel");
        writeFileSync(sentinel, "keep\n");
        if (scenario === "fresh-linked-python-root") {
          const externalPythonRoot = path.join(outside, "fresh-python-root");
          const managedPythonRoot = path.join(tools, "python");
          mkdirSync(path.join(externalPythonRoot, "cpython-3.12", "bin"), { recursive: true });
          mkdirSync(path.dirname(managedPythonRoot), { recursive: true });
          symlinkSync(
            externalPythonRoot,
            managedPythonRoot,
            process.platform === "win32" ? "junction" : "dir",
          );
        }
        const environment = path.join(candidate, ".venv");
        if (scenario !== "top-level-link" && scenario !== "fresh-linked-python-root") {
          mkdirSync(environment);
          if (scenario !== "malformed-directory") {
            if (scenario === "linked-python-root") {
              const externalPythonRoot = path.join(outside, "python-root");
              const managedPythonRoot = path.join(tools, "python");
              mkdirSync(path.join(externalPythonRoot, "cpython-3.12", "bin"), { recursive: true });
              mkdirSync(path.dirname(managedPythonRoot), { recursive: true });
              symlinkSync(
                externalPythonRoot,
                managedPythonRoot,
                process.platform === "win32" ? "junction" : "dir",
              );
            } else if (scenario === "external-python-home") {
              const externalPython = path.join(outside, "python-home");
              const pythonAlias = path.join(tools, "python", "cpython-3.12");
              mkdirSync(path.join(externalPython, "bin"), { recursive: true });
              mkdirSync(path.dirname(pythonAlias), { recursive: true });
              symlinkSync(externalPython, pythonAlias, process.platform === "win32" ? "junction" : "dir");
              pythonHome = path.join(pythonAlias, "bin");
            } else {
              mkdirSync(pythonHome, { recursive: true });
            }
            const configuration = [
              `home = ${pythonHome}`,
              ...(scenario === "missing-uv-metadata" ? [] : ["uv = 0.11.16"]),
              `version_info = ${scenario === "wrong-python-version" ? "3.13.1" : "3.12.0"}`,
              `relocatable = ${scenario === "not-relocatable" ? "false" : "true"}`,
            ];
            writeFileSync(
              path.join(environment, "pyvenv.cfg"),
              `${configuration.join("\n")}\n`,
            );
          } else {
            writeFileSync(path.join(environment, "not-a-virtual-environment"), "keep\n");
          }
        }
        if (scenario === "top-level-link") {
          symlinkSync(outside, environment, process.platform === "win32" ? "junction" : "dir");
        } else if (scenario === "nested-directory-link") {
          const link = path.join(environment, process.platform === "win32" ? "Lib" : "lib");
          symlinkSync(outside, link, process.platform === "win32" ? "junction" : "dir");
        } else if (scenario === "nested-file-link") {
          const bin = path.join(environment, "bin");
          mkdirSync(bin);
          symlinkSync(
            process.platform === "win32" ? outside : sentinel,
            path.join(bin, "activate"),
            process.platform === "win32" ? "junction" : "file",
          );
        }

        const uv = path.join(tools, process.platform === "win32" ? "uv.cmd" : "uv");
        const node = path.join(tools, process.platform === "win32" ? "node.cmd" : "node");
        const corepack = path.join(tools, "corepack.js");
        mkdirSync(tools, { recursive: true });
        for (const tool of [uv, node, corepack]) writeFileSync(tool, "must not run\n");

        const result =
          process.platform === "win32"
            ? spawnSync(
                "powershell.exe",
                [
                  "-NoProfile",
                  "-NonInteractive",
                  "-ExecutionPolicy",
                  "Bypass",
                  "-File",
                  powershellScript,
                  "-Candidate",
                  candidate,
                  "-Uv",
                  uv,
                  "-Node",
                  node,
                  "-CorepackJs",
                  corepack,
                  "-ToolsRoot",
                  tools,
                  "-PnpmVersion",
                  "10.34.5",
                ],
                { encoding: "utf8" },
              )
            : spawnSync("/bin/sh", [posixScript, candidate, uv, node, corepack, tools, "10.34.5"], {
                encoding: "utf8",
                env: { PATH: "/usr/bin:/bin" },
              });

        expect(result.status).not.toBe(0);
        expect(`${result.stdout}\n${result.stderr}`).toContain(
          scenario.endsWith("linked-python-root")
            ? "Refusing managed Python tool root"
            : scenario.endsWith("link")
              ? "Refusing"
              : "Refusing existing .venv",
        );
        expect(readFileSync(sentinel, "utf8")).toBe("keep\n");
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
    expect(combined).toContain("pnpm 10.34.5");
    expect(combined).toContain("--frozen-lockfile");
    expect(combined).toContain("COREPACK_HOME");
    expect(combined).toContain("UV_CACHE_DIR");
    expect(combined).toContain("UV_NO_EDITABLE");
    expect(combined).toContain("UV_PYTHON_INSTALL_DIR");
    expect(posix).toContain('"$uv" venv --relocatable --python 3.12 .venv');
    expect(powershell).toContain(
      'Invoke-Checked $Uv @("venv", "--relocatable", "--python", "3.12", ".venv")',
    );
    expect(combined).not.toContain("--clear");
    expect(combined).not.toContain("--allow-existing");
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
