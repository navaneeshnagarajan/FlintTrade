import { execFileSync, spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { once } from "node:events";
import {
  chmodSync,
  copyFileSync,
  existsSync,
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
    "rebuilds a validated POSIX virtual environment without executing its old contents",
    () => {
      const root = mkdtempSync(path.join(tmpdir(), "flinttrade-bootstrap-entrypoint-"));
      try {
        const poisonedUvTarget = path.join(root, "outside-uv-target");
        mkdirSync(poisonedUvTarget);
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
        writeFileSync(
          path.join(pythonVersionRoot, "bin", "python3.12"),
          `#!/bin/sh
[ "\${1-}" = -I ] && [ "\${2-}" = -S ] && [ "\${3-}" = -c ] || exit 91
source_path=\${5-}
destination_path=\${6-}
[ -n "\$source_path" ] && [ -n "\$destination_path" ] || exit 92
[ ! -L "\$source_path" ] && [ -d "\$source_path" ] || exit 93
[ ! -e "\$destination_path" ] && [ ! -L "\$destination_path" ] || exit 94
mv "\$source_path" "\$destination_path"
`,
        );
        chmodSync(path.join(pythonVersionRoot, "bin", "python3.12"), 0o755);
        symlinkSync(pythonVersionRoot, pythonAlias, "junction");
        const environment = path.join(candidate, ".venv");
        mkdirSync(path.join(environment, "lib"));
        mkdirSync(path.join(environment, "bin"));
        symlinkSync("lib", path.join(environment, "lib64"), "dir");
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
if [ "\${FLINTTRADE_TEST_FAIL_PNPM_INSTALL-}" = 1 ] &&
  [ "\${1-}" = pnpm ] && [ "\${2-}" = install ]; then
  exit 96
fi
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
[ "\${UV_WORKING_DIR-}" = '${candidate}' ] || exit 81
[ "\${UV_PROJECT-}" = '${candidate}' ] || exit 82
[ "\${UV_NO_CONFIG-}" = 1 ] || exit 83
[ "\${UV_MANAGED_PYTHON-}" = 1 ] || exit 84
[ -z "\${UV_SYSTEM_PYTHON-}" ] || exit 85
if [ "\${1-}" = venv ]; then
  for argument in "\$@"; do
    [ "\$argument" != --allow-existing ] || exit 78
  done
  target=\${5-}
  [ -n "\$target" ] && [ "\$target" != .venv ] || exit 77
  mkdir -p "\$target/lib" "\$target/bin"
  ln -s lib "\$target/lib64"
  ln -s '${pythonHome}/python3.12' "\$target/bin/python"
  ln -s python "\$target/bin/python3"
  ln -s python "\$target/bin/python3.12"
  if [ "\${FLINTTRADE_TEST_INVALID_STAGED_CONFIG-}" = 1 ]; then
    staged_version=3.13.0
  else
    staged_version=3.12.0
  fi
  printf '%s\n' 'home = ${pythonHome}' 'uv = 0.11.16' "version_info = \$staged_version" 'relocatable = true' > "\$target/pyvenv.cfg"
fi
if [ "\${1-}" = sync ]; then
  [ -n "\${UV_PROJECT_ENVIRONMENT-}" ] || exit 79
  [ "\$UV_PROJECT_ENVIRONMENT" != "\$PWD/.venv" ] || exit 80
  if [ -n "\${FLINTTRADE_TEST_OCCUPY_FINAL-}" ]; then
    ln -s "\$FLINTTRADE_TEST_OCCUPY_FINAL" "\$PWD/.venv"
  fi
fi
exit 0
`,
        );
        for (const executable of [node, corepack, uv]) chmodSync(executable, 0o755);

        expect(() =>
          execFileSync("/bin/sh", [posixScript, candidate, uv, node, corepack, tools, "10.34.5"], {
            env: {
              PATH: "/usr/bin:/bin",
              UV_PROJECT_ENVIRONMENT: poisonedUvTarget,
              UV_WORKING_DIR: poisonedUvTarget,
              UV_PROJECT: poisonedUvTarget,
              UV_SYSTEM_PYTHON: "1",
            },
          }),
        ).not.toThrow();
        expect(existsSync(staleEnvironmentFile)).toBe(false);
        rmSync(path.join(candidate, ".venv"), { force: true, recursive: true });
        expect(() =>
          execFileSync("/bin/sh", [posixScript, candidate, uv, node, corepack, tools, "10.34.5"], {
            env: {
              PATH: "/usr/bin:/bin",
              UV_PROJECT_ENVIRONMENT: poisonedUvTarget,
              UV_WORKING_DIR: poisonedUvTarget,
              UV_PROJECT: poisonedUvTarget,
              UV_SYSTEM_PYTHON: "1",
            },
          }),
        ).not.toThrow();
        expect(readFileSync(path.join(candidate, ".venv", "pyvenv.cfg"), "utf8")).toContain(
          "version_info = 3.12.0",
        );
        const preservedEnvironmentFile = path.join(candidate, ".venv", "preserved");
        writeFileSync(preservedEnvironmentFile, "preserved\n");
        const invalidStagedResult = spawnSync(
          "/bin/sh",
          [posixScript, candidate, uv, node, corepack, tools, "10.34.5"],
          {
            encoding: "utf8",
            env: {
              PATH: "/usr/bin:/bin",
              FLINTTRADE_TEST_INVALID_STAGED_CONFIG: "1",
              UV_PROJECT_ENVIRONMENT: poisonedUvTarget,
              UV_WORKING_DIR: poisonedUvTarget,
              UV_PROJECT: poisonedUvTarget,
              UV_SYSTEM_PYTHON: "1",
            },
          },
        );
        expect(invalidStagedResult.status).not.toBe(0);
        expect(existsSync(preservedEnvironmentFile)).toBe(true);
        expect(readdirSync(candidate).filter((entry) => entry.startsWith(".venv.flinttrade-"))).toEqual(
          [],
        );
        const failedJavascriptResult = spawnSync(
          "/bin/sh",
          [posixScript, candidate, uv, node, corepack, tools, "10.34.5"],
          {
            encoding: "utf8",
            env: {
              PATH: "/usr/bin:/bin",
              FLINTTRADE_TEST_FAIL_PNPM_INSTALL: "1",
              UV_PROJECT_ENVIRONMENT: poisonedUvTarget,
              UV_WORKING_DIR: poisonedUvTarget,
              UV_PROJECT: poisonedUvTarget,
              UV_SYSTEM_PYTHON: "1",
            },
          },
        );
        expect(failedJavascriptResult.status).not.toBe(0);
        expect(existsSync(preservedEnvironmentFile)).toBe(true);
        expect(readdirSync(candidate).filter((entry) => entry.startsWith(".venv.flinttrade-"))).toEqual(
          [],
        );
        rmSync(path.join(candidate, ".venv"), { force: true, recursive: true });
        const outsideSentinel = path.join(poisonedUvTarget, "sentinel");
        writeFileSync(outsideSentinel, "outside\n");
        const occupiedFinalResult = spawnSync(
          "/bin/sh",
          [posixScript, candidate, uv, node, corepack, tools, "10.34.5"],
          {
            encoding: "utf8",
            env: {
              PATH: "/usr/bin:/bin",
              FLINTTRADE_TEST_OCCUPY_FINAL: poisonedUvTarget,
            },
          },
        );
        expect(occupiedFinalResult.status).not.toBe(0);
        expect(lstatSync(path.join(candidate, ".venv")).isSymbolicLink()).toBe(true);
        expect(readFileSync(outsideSentinel, "utf8")).toBe("outside\n");
        expect(existsSync(path.join(poisonedUvTarget, "staging"))).toBe(false);
        expect(readdirSync(candidate).filter((entry) => entry.startsWith(".venv.flinttrade-"))).toEqual(
          [],
        );
      } finally {
        rmSync(root, { force: true, recursive: true });
      }
    },
  );

  it.runIf(process.platform === "win32")(
    "rebuilds a validated Windows virtual environment without executing its old contents",
    async () => {
      const root = mkdtempSync(path.join(tmpdir(), "flinttrade-bootstrap-entrypoint-"));
      let lockedNestedExecutableProcess: ReturnType<typeof spawn> | undefined;
      try {
        const poisonedUvTarget = path.join(root, "outside-uv-target");
        mkdirSync(poisonedUvTarget);
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
        const staleEnvironmentBytes = Buffer.from([0x00, 0x66, 0x6c, 0x69, 0x6e, 0x74, 0xff]);
        writeFileSync(staleEnvironmentFile, staleEnvironmentBytes);
        const staleScripts = path.join(candidate, ".venv", "Scripts");
        const stalePython = path.join(staleScripts, "python.exe");
        const stalePythonw = path.join(staleScripts, "pythonw.exe");
        mkdirSync(staleScripts);
        const system32 = path.join(process.env.SystemRoot ?? "C:\\Windows", "System32");
        copyFileSync(path.join(system32, "where.exe"), stalePython);
        copyFileSync(path.join(system32, "where.exe"), stalePythonw);
        const nestedNativeDirectory = path.join(candidate, ".venv", "Lib", "site-packages", "native");
        const nestedSentinel = path.join(nestedNativeDirectory, "sentinel.bin");
        const nestedSentinelBytes = Buffer.from([0xde, 0xad, 0x00, 0xbe, 0xef, 0x0a]);
        const lockedNestedExecutable = path.join(nestedNativeDirectory, "worker-helper.exe");
        mkdirSync(nestedNativeDirectory, { recursive: true });
        writeFileSync(nestedSentinel, nestedSentinelBytes);
        copyFileSync(
          path.join(system32, "ping.exe"),
          lockedNestedExecutable,
        );
        const lockedNestedExecutableSha256 = createHash("sha256")
          .update(readFileSync(lockedNestedExecutable))
          .digest("hex");
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
if "%FLINTTRADE_TEST_FAIL_PNPM_INSTALL%"=="1" if "%~2"=="pnpm" if "%~3"=="install" exit /b 96
exit /b 0
`,
        );
        writeFileSync(
          uv,
          `@echo off
setlocal
if "%~1"=="--version" exit /b 0
if not "%UV_NO_EDITABLE%"=="1" exit /b 74
if not "%UV_WORKING_DIR%"=="${candidate}" exit /b 81
if not "%UV_PROJECT%"=="${candidate}" exit /b 82
if not "%UV_NO_CONFIG%"=="1" exit /b 83
if not "%UV_MANAGED_PYTHON%"=="1" exit /b 84
if defined UV_SYSTEM_PYTHON exit /b 85
if "%~1"=="venv" if not "%~5"==".venv" (
  mkdir "%~5\\Scripts"
  copy /y "%SystemRoot%\\System32\\where.exe" "%~5\\Scripts\\python.exe" >nul
  if not "%FLINTTRADE_TEST_MISSING_STAGED_LAUNCHER%"=="1" copy /y "%SystemRoot%\\System32\\where.exe" "%~5\\Scripts\\pythonw.exe" >nul
  >"%~5\\pyvenv.cfg" echo home = ${pythonHome}
  >>"%~5\\pyvenv.cfg" echo uv = 0.11.16
  if "%FLINTTRADE_TEST_INVALID_STAGED_CONFIG%"=="1" (
    >>"%~5\\pyvenv.cfg" echo version_info = 3.13.0
  ) else (
    >>"%~5\\pyvenv.cfg" echo version_info = 3.12.0
  )
  >>"%~5\\pyvenv.cfg" echo relocatable = true
  exit /b 0
)
if exist .venv if "%~1"=="venv" exit /b 77
if "%~1"=="sync" (
  if "%UV_PROJECT_ENVIRONMENT%"=="" exit /b 79
  if /I "%UV_PROJECT_ENVIRONMENT%"=="%CD%\\.venv" exit /b 80
  exit /b 0
)
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

        const invokeBootstrap = (extraEnvironment: NodeJS.ProcessEnv = {}) =>
          spawnSync(
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
            {
              encoding: "utf8",
              env: {
                ...process.env,
                UV_PROJECT_ENVIRONMENT: poisonedUvTarget,
                UV_WORKING_DIR: poisonedUvTarget,
                UV_PROJECT: poisonedUvTarget,
                UV_SYSTEM_PYTHON: "1",
                ...extraEnvironment,
              },
            },
          );

        rmSync(stalePythonw);
        const missingCurrentLauncherResult = invokeBootstrap();
        expect(missingCurrentLauncherResult.status).not.toBe(0);
        expect(`${missingCurrentLauncherResult.stdout}\n${missingCurrentLauncherResult.stderr}`).toContain(
          "Refusing existing .venv because its Python launchers are missing, linked, or not regular files.",
        );
        expect(readFileSync(staleEnvironmentFile)).toEqual(staleEnvironmentBytes);
        expect(readdirSync(candidate).filter((entry) => entry.startsWith(".venv.flinttrade-"))).toEqual(
          [],
        );
        copyFileSync(path.join(system32, "where.exe"), stalePythonw);

        const missingStagedLauncherResult = invokeBootstrap({
          FLINTTRADE_TEST_MISSING_STAGED_LAUNCHER: "1",
        });
        expect(missingStagedLauncherResult.status).not.toBe(0);
        expect(`${missingStagedLauncherResult.stdout}\n${missingStagedLauncherResult.stderr}`).toContain(
          "Refusing staged .venv because its Python launchers are missing, linked, or not regular files.",
        );
        expect(readFileSync(staleEnvironmentFile)).toEqual(staleEnvironmentBytes);
        expect(readdirSync(candidate).filter((entry) => entry.startsWith(".venv.flinttrade-"))).toEqual(
          [],
        );

        lockedNestedExecutableProcess = spawn(lockedNestedExecutable, ["-t", "127.0.0.1"], {
          stdio: "ignore",
          windowsHide: true,
        });
        await once(lockedNestedExecutableProcess, "spawn");

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
          {
            encoding: "utf8",
            env: {
              ...process.env,
              UV_PROJECT_ENVIRONMENT: poisonedUvTarget,
              UV_WORKING_DIR: poisonedUvTarget,
              UV_PROJECT: poisonedUvTarget,
              UV_SYSTEM_PYTHON: "1",
            },
          },
        );

        expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
        expect(`${result.stdout}\n${result.stderr}`).toContain(
          "Deferred cleanup of the retired virtual environment because one of its files is still in use.",
        );
        expect(existsSync(staleEnvironmentFile)).toBe(false);
        const retainedBackups = readdirSync(candidate).filter((entry) =>
          /^\.venv\.flinttrade-backup-[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}$/.test(entry),
        );
        expect(retainedBackups).toHaveLength(1);
        const retainedBackup = path.join(candidate, retainedBackups[0]!);
        expect(`${result.stdout}\n${result.stderr}`).toContain(
          `Blocked file: '${path.join(retainedBackup, "Lib", "site-packages", "native", "worker-helper.exe")}'.`,
        );
        expect(`${result.stdout}\n${result.stderr}`).toContain(
          `Retained path: '${retainedBackup}'.`,
        );
        expect(readdirSync(path.join(candidate, retainedBackups[0]!)).sort()).toEqual([
          "Lib",
          "Scripts",
          "pyvenv.cfg",
          "stale",
        ]);
        expect(readFileSync(path.join(retainedBackup, "stale"))).toEqual(staleEnvironmentBytes);
        expect(readFileSync(path.join(retainedBackup, "Lib", "site-packages", "native", "sentinel.bin"))).toEqual(
          nestedSentinelBytes,
        );
        expect(
          createHash("sha256")
            .update(
              readFileSync(
                path.join(retainedBackup, "Lib", "site-packages", "native", "worker-helper.exe"),
              ),
            )
            .digest("hex"),
        ).toBe(lockedNestedExecutableSha256);
        expect(readdirSync(path.join(retainedBackup, "Lib", "site-packages", "native")).sort()).toEqual([
          "sentinel.bin",
          "worker-helper.exe",
        ]);
        if (lockedNestedExecutableProcess.exitCode === null) {
          const lockedNestedExecutableExit = once(lockedNestedExecutableProcess, "exit");
          lockedNestedExecutableProcess.kill();
          await lockedNestedExecutableExit;
        }
        lockedNestedExecutableProcess = undefined;
        const unownedLookalike = path.join(candidate, ".venv.flinttrade-backup-not-owned");
        mkdirSync(unownedLookalike);
        writeFileSync(path.join(unownedLookalike, "sentinel"), "preserve\n");
        const incompleteOrphanName = ".venv.flinttrade-backup-00000000000040008000000000000000";
        const incompleteOrphan = path.join(candidate, incompleteOrphanName);
        mkdirSync(incompleteOrphan);
        writeFileSync(path.join(incompleteOrphan, "sentinel"), "preserve\n");
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
          {
            encoding: "utf8",
            env: {
              ...process.env,
              UV_PROJECT_ENVIRONMENT: poisonedUvTarget,
              UV_WORKING_DIR: poisonedUvTarget,
              UV_PROJECT: poisonedUvTarget,
              UV_SYSTEM_PYTHON: "1",
            },
          },
        );
        expect(freshResult.status, `${freshResult.stdout}\n${freshResult.stderr}`).toBe(0);
        expect(`${freshResult.stdout}\n${freshResult.stderr}`).toContain(
          `Preserved an unvalidated retired virtual environment at '${incompleteOrphan}'.`,
        );
        expect(lstatSync(path.join(candidate, ".venv")).isDirectory()).toBe(true);
        expect(
          readdirSync(candidate).filter((entry) =>
            /^\.venv\.flinttrade-backup-[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}$/.test(entry),
          ),
        ).toEqual([incompleteOrphanName]);
        expect(readFileSync(path.join(unownedLookalike, "sentinel"), "utf8")).toBe("preserve\n");
        expect(readFileSync(path.join(incompleteOrphan, "sentinel"), "utf8")).toBe("preserve\n");
        rmSync(unownedLookalike, { recursive: true });
        rmSync(incompleteOrphan, { recursive: true });
        const preservedEnvironmentFile = path.join(candidate, ".venv", "preserved");
        writeFileSync(preservedEnvironmentFile, "preserved\n");
        const invalidStagedResult = spawnSync(
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
          {
            encoding: "utf8",
            env: {
              ...process.env,
              FLINTTRADE_TEST_INVALID_STAGED_CONFIG: "1",
              UV_PROJECT_ENVIRONMENT: poisonedUvTarget,
              UV_WORKING_DIR: poisonedUvTarget,
              UV_PROJECT: poisonedUvTarget,
              UV_SYSTEM_PYTHON: "1",
            },
          },
        );
        expect(invalidStagedResult.status).not.toBe(0);
        expect(existsSync(preservedEnvironmentFile)).toBe(true);
        expect(readdirSync(candidate).filter((entry) => entry.startsWith(".venv.flinttrade-"))).toEqual(
          [],
        );
        const failedJavascriptResult = spawnSync(
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
          {
            encoding: "utf8",
            env: {
              ...process.env,
              FLINTTRADE_TEST_FAIL_PNPM_INSTALL: "1",
              UV_PROJECT_ENVIRONMENT: poisonedUvTarget,
              UV_WORKING_DIR: poisonedUvTarget,
              UV_PROJECT: poisonedUvTarget,
              UV_SYSTEM_PYTHON: "1",
            },
          },
        );
        expect(failedJavascriptResult.status).not.toBe(0);
        expect(existsSync(preservedEnvironmentFile)).toBe(true);
        expect(readdirSync(candidate).filter((entry) => entry.startsWith(".venv.flinttrade-"))).toEqual(
          [],
        );
      } finally {
        if (lockedNestedExecutableProcess?.exitCode === null) {
          const lockedNestedExecutableExit = once(lockedNestedExecutableProcess, "exit");
          lockedNestedExecutableProcess.kill();
          await lockedNestedExecutableExit;
        }
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
    "fresh-nested-linked-python-entry",
    ...(process.platform === "win32" ? (["fresh-case-distinct-python-alias"] as const) : []),
    "fresh-python-link-via-external-trampoline",
    "fresh-python-link-via-external-parent-trampoline",
    ...(process.platform !== "win32"
      ? (["fresh-python-link-via-inroot-dotdot-trampoline"] as const)
      : []),
    "fresh-linked-tools-root",
    ...(process.platform !== "win32" ? (["fresh-noncanonical-tools-path"] as const) : []),
    ...(process.platform !== "win32" ? (["fresh-untrusted-posix-path"] as const) : []),
    "reused-python-tree-link-escape",
    "duplicate-uv-metadata",
    "alternate-uv-metadata",
    "alternate-home-metadata",
    "contradictory-version-metadata",
    "alternate-version-metadata",
    "version-alias-metadata",
    "contradictory-relocatable-metadata",
    "alternate-relocatable-metadata",
    "unicode-whitespace-relocatable-metadata",
    "bom-prefixed-metadata",
  ] as const)(
    "refuses an unsafe %s virtual environment before invoking managed tools",
    (scenario) => {
      const root = mkdtempSync(path.join(tmpdir(), "flinttrade-bootstrap-linked-venv-"));
      try {
        const candidate = path.join(root, "candidate.[brackets]");
        const outside = path.join(root, "outside");
        const tools = path.join(root, "tools");
        let toolsArgument = tools;
        const pathCanary = path.join(root, "path-canary");
        const pathCanaryMarker = path.join(root, "path-canary-invoked");
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
        if (scenario === "fresh-noncanonical-tools-path") {
          const safeRoot = path.join(root, "safe");
          const outsideIntermediate = path.join(outside, "intermediate");
          const outsideTools = path.join(outside, "tools");
          mkdirSync(outsideIntermediate, { recursive: true });
          mkdirSync(path.join(outsideTools, "python"), { recursive: true });
          mkdirSync(safeRoot, { recursive: true });
          symlinkSync(outsideIntermediate, path.join(safeRoot, "link"), "dir");
          toolsArgument = `${path.join(safeRoot, "link")}/../tools`;
        } else if (scenario === "fresh-linked-tools-root") {
          const externalToolsRoot = path.join(outside, "fresh-tools-root");
          mkdirSync(path.join(externalToolsRoot, "python", "cpython-3.12", "bin"), {
            recursive: true,
          });
          symlinkSync(
            externalToolsRoot,
            tools,
            process.platform === "win32" ? "junction" : "dir",
          );
        } else if (scenario === "fresh-untrusted-posix-path") {
          const externalPython = path.join(outside, "fresh-python-version");
          const pythonAlias = path.join(tools, "python", "cpython-3.12");
          mkdirSync(path.join(externalPython, "bin"), { recursive: true });
          mkdirSync(path.dirname(pythonAlias), { recursive: true });
          symlinkSync(externalPython, pythonAlias, "dir");
          mkdirSync(pathCanary);
          for (const command of ["find", "readlink", "grep", "sed", "dirname", "basename"]) {
            const executable = path.join(pathCanary, command);
            writeFileSync(
              executable,
              `#!/bin/sh\nprintf invoked > '${pathCanaryMarker}'\nexit 0\n`,
            );
            chmodSync(executable, 0o755);
          }
        } else if (scenario === "fresh-linked-python-root") {
          const externalPythonRoot = path.join(outside, "fresh-python-root");
          const managedPythonRoot = path.join(tools, "python");
          mkdirSync(path.join(externalPythonRoot, "cpython-3.12", "bin"), { recursive: true });
          mkdirSync(path.dirname(managedPythonRoot), { recursive: true });
          symlinkSync(
            externalPythonRoot,
            managedPythonRoot,
            process.platform === "win32" ? "junction" : "dir",
          );
        } else if (scenario === "fresh-nested-linked-python-entry") {
          const externalPython = path.join(outside, "fresh-python-version");
          const pythonAlias = path.join(tools, "python", "cpython-3.12");
          mkdirSync(path.join(externalPython, "bin"), { recursive: true });
          mkdirSync(path.dirname(pythonAlias), { recursive: true });
          symlinkSync(externalPython, pythonAlias, process.platform === "win32" ? "junction" : "dir");
        } else if (scenario === "fresh-case-distinct-python-alias") {
          const managedPythonRoot = path.join(tools, "python");
          const caseDistinctRoot = path.join(tools, "PYTHON");
          const pythonAlias = path.join(managedPythonRoot, "cpython-3.12");
          const caseDistinctVersion = path.join(caseDistinctRoot, "cpython-3.12.0");
          mkdirSync(tools, { recursive: true });
          if (process.platform === "win32") {
            const caseSensitivity = spawnSync(
              "fsutil.exe",
              ["file", "SetCaseSensitiveInfo", tools, "enable"],
              { encoding: "utf8" },
            );
            expect(
              caseSensitivity.status,
              `${caseSensitivity.stdout}\n${caseSensitivity.stderr}`,
            ).toBe(0);
          }
          mkdirSync(managedPythonRoot);
          mkdirSync(path.join(caseDistinctVersion, "bin"), { recursive: true });
          symlinkSync(
            caseDistinctVersion,
            pythonAlias,
            process.platform === "win32" ? "junction" : "dir",
          );
        } else if (scenario === "fresh-python-link-via-external-trampoline") {
          const managedPythonRoot = path.join(tools, "python");
          const managedVersion = path.join(managedPythonRoot, "cpython-3.12.0");
          const externalTrampoline = path.join(outside, "python-trampoline");
          const pythonAlias = path.join(managedPythonRoot, "cpython-3.12");
          mkdirSync(path.join(managedVersion, "bin"), { recursive: true });
          symlinkSync(
            managedVersion,
            externalTrampoline,
            process.platform === "win32" ? "junction" : "dir",
          );
          symlinkSync(
            externalTrampoline,
            pythonAlias,
            process.platform === "win32" ? "junction" : "dir",
          );
        } else if (scenario === "fresh-python-link-via-external-parent-trampoline") {
          const managedPythonRoot = path.join(tools, "python");
          const managedVersion = path.join(managedPythonRoot, "cpython-3.12.0");
          const externalParentTrampoline = path.join(outside, "python-parent-trampoline");
          const pythonAlias = path.join(managedPythonRoot, "cpython-3.12");
          mkdirSync(path.join(managedVersion, "bin"), { recursive: true });
          symlinkSync(
            managedPythonRoot,
            externalParentTrampoline,
            process.platform === "win32" ? "junction" : "dir",
          );
          symlinkSync(
            path.join(externalParentTrampoline, path.basename(managedVersion)),
            pythonAlias,
            process.platform === "win32" ? "junction" : "dir",
          );
        } else if (scenario === "fresh-python-link-via-inroot-dotdot-trampoline") {
          const managedPythonRoot = path.join(tools, "python");
          const deepRoot = path.join(managedPythonRoot, "deep");
          const anchor = path.join(managedPythonRoot, "anchor");
          const trampoline = path.join(deepRoot, "trampoline");
          const escape = path.join(managedPythonRoot, "escape");
          mkdirSync(anchor, { recursive: true });
          mkdirSync(path.join(tools, "outside"), { recursive: true });
          mkdirSync(deepRoot, { recursive: true });
          symlinkSync(anchor, trampoline, "dir");
          symlinkSync("deep/trampoline/../../outside", escape, "dir");
        }
        const environment = path.join(candidate, ".venv");
        if (
          scenario !== "top-level-link" &&
          scenario !== "fresh-linked-python-root" &&
          scenario !== "fresh-linked-tools-root" &&
          scenario !== "fresh-noncanonical-tools-path" &&
          scenario !== "fresh-untrusted-posix-path" &&
          scenario !== "fresh-nested-linked-python-entry" &&
          scenario !== "fresh-case-distinct-python-alias" &&
          scenario !== "fresh-python-link-via-external-trampoline" &&
          scenario !== "fresh-python-link-via-external-parent-trampoline" &&
          scenario !== "fresh-python-link-via-inroot-dotdot-trampoline"
        ) {
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
            if (scenario === "reused-python-tree-link-escape") {
              const escapedEntry = path.join(tools, "python", "escaped-entry");
              symlinkSync(
                outside,
                escapedEntry,
                process.platform === "win32" ? "junction" : "dir",
              );
            }
            const configuration = [
              `home = ${pythonHome}`,
              ...(scenario === "alternate-home-metadata" ? [`home=${outside}`] : []),
              ...(scenario === "missing-uv-metadata"
                ? []
                : [
                    "uv = 0.11.16",
                    ...(scenario === "duplicate-uv-metadata" ? ["uv = 0.11.15"] : []),
                    ...(scenario === "alternate-uv-metadata" ? ["uv=0.11.15"] : []),
                  ]),
              `version_info = ${scenario === "wrong-python-version" ? "3.13.1" : "3.12.0"}`,
              ...(scenario === "contradictory-version-metadata"
                ? ["version_info = 3.13.1"]
                : []),
              ...(scenario === "alternate-version-metadata" ? [" version_info=3.13.1"] : []),
              ...(scenario === "version-alias-metadata" ? ["version = 3.13.1"] : []),
              `relocatable = ${scenario === "not-relocatable" ? "false" : "true"}`,
              ...(scenario === "contradictory-relocatable-metadata"
                ? ["relocatable = false"]
                : []),
              ...(scenario === "alternate-relocatable-metadata" ? ["relocatable=false"] : []),
              ...(scenario === "unicode-whitespace-relocatable-metadata"
                ? ["relocatable\u00a0=false"]
                : []),
            ];
            const configurationContents = `${configuration.join("\n")}\n`;
            writeFileSync(
              path.join(environment, "pyvenv.cfg"),
              scenario === "bom-prefixed-metadata"
                ? Buffer.concat([
                    Buffer.from([0xef, 0xbb, 0xbf]),
                    Buffer.from(configurationContents, "utf8"),
                  ])
                : configurationContents,
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
                  toolsArgument,
                  "-PnpmVersion",
                  "10.34.5",
                ],
                { encoding: "utf8" },
              )
            : spawnSync(
                "/bin/sh",
                [posixScript, candidate, uv, node, corepack, toolsArgument, "10.34.5"],
                {
                  encoding: "utf8",
                  env: {
                    PATH: scenario === "fresh-untrusted-posix-path" ? pathCanary : "/usr/bin:/bin",
                  },
                },
              );

        expect(result.status).not.toBe(0);
        expect(`${result.stdout}\n${result.stderr}`).toContain(
          scenario === "bom-prefixed-metadata"
            ? "pyvenv.cfg is not valid BOM-less UTF-8"
            : scenario === "duplicate-uv-metadata" ||
          scenario === "alternate-uv-metadata" ||
          scenario === "alternate-home-metadata" ||
          scenario === "contradictory-version-metadata" ||
          scenario === "alternate-version-metadata" ||
          scenario === "version-alias-metadata" ||
          scenario === "contradictory-relocatable-metadata" ||
          scenario === "alternate-relocatable-metadata" ||
          scenario === "unicode-whitespace-relocatable-metadata"
            ? "not a uv-managed relocatable Python 3.12 environment"
            : scenario.endsWith("linked-python-root") ||
                scenario === "fresh-linked-tools-root" ||
                scenario === "fresh-noncanonical-tools-path" ||
                scenario === "fresh-untrusted-posix-path" ||
                scenario === "fresh-nested-linked-python-entry" ||
                scenario === "fresh-case-distinct-python-alias" ||
                scenario === "fresh-python-link-via-external-trampoline" ||
                scenario === "fresh-python-link-via-external-parent-trampoline" ||
                scenario === "fresh-python-link-via-inroot-dotdot-trampoline" ||
                scenario === "reused-python-tree-link-escape"
              ? "Refusing managed Python tool root"
              : scenario.endsWith("link")
                ? "Refusing"
                : "Refusing existing .venv",
        );
        expect(readFileSync(sentinel, "utf8")).toBe("keep\n");
        expect(existsSync(pathCanaryMarker)).toBe(false);
      } finally {
        rmSync(root, { force: true, recursive: true });
      }
    },
  );

  it("refuses a managed Python link escape created during a fresh install before creating the venv", () => {
    const root = mkdtempSync(path.join(tmpdir(), "flinttrade-bootstrap-python-postcheck-"));
    try {
      const candidate = path.join(root, "candidate");
      const outside = path.join(root, "outside-python");
      const tools = path.join(root, "tools");
      const venvMarker = path.join(root, "venv-invoked");
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

      const uv = path.join(tools, process.platform === "win32" ? "uv.cmd" : "uv");
      const node = path.join(tools, process.platform === "win32" ? "node.cmd" : "node");
      const corepack = path.join(tools, "corepack.js");
      mkdirSync(tools, { recursive: true });
      writeFileSync(corepack, "// verified Corepack fixture\n");
      if (process.platform === "win32") {
        const pythonAlias = path.join(tools, "python", "cpython-3.12");
        writeFileSync(
          uv,
          `@echo off
if "%~1"=="--version" exit /b 0
if "%~1"=="python" (
  mkdir "${path.dirname(pythonAlias)}"
  mklink /J "${pythonAlias}" "${outside}" >nul
  exit /b 0
)
if "%~1"=="venv" (
  echo invoked>"${venvMarker}"
  mkdir .venv
)
exit /b 0
`,
        );
        writeFileSync(
          node,
          `@echo off
if "%~1"=="--version" echo v22.23.2
if "%~2"=="--version" echo 0.34.6
if "%~2"=="pnpm" if "%~3"=="--version" echo 10.34.5
exit /b 0
`,
        );
      } else {
        const pythonAlias = path.join(tools, "python", "cpython-3.12");
        writeFileSync(
          uv,
          `#!/bin/sh
if [ "\${1-}" = --version ]; then exit 0; fi
if [ "\${1-}" = python ]; then
  mkdir -p '${path.dirname(pythonAlias)}'
  ln -s '${outside}' '${pythonAlias}'
  exit 0
fi
if [ "\${1-}" = venv ]; then
  printf invoked > '${venvMarker}'
  mkdir .venv
fi
exit 0
`,
        );
        writeFileSync(
          node,
          `#!/bin/sh
if [ "\${1-}" = --version ]; then printf '%s\n' v22.23.1; exit 0; fi
case "\${1-}" in */corepack.js) shift;; *) exit 71;; esac
if [ "\${1-}" = --version ]; then printf '%s\n' 0.29.4; exit 0; fi
if [ "\${1-}" = pnpm ] && [ "\${2-}" = --version ]; then printf '%s\n' 10.34.5; fi
exit 0
`,
        );
        chmodSync(uv, 0o755);
        chmodSync(node, 0o755);
      }

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
      expect(`${result.stdout}\n${result.stderr}`).toContain("Refusing managed Python tool root");
      expect(existsSync(venvMarker)).toBe(false);
    } finally {
      rmSync(root, { force: true, recursive: true });
    }
  });

  it("uses frozen locks, exact pnpm and no privileged or remote-script execution", () => {
    const posix = readFileSync(posixScript, "utf8");
    const powershell = readFileSync(powershellScript, "utf8");
    const combined = `${posix}\n${powershell}`;

    expect(combined).toContain("sync --frozen --all-packages --no-install-package flinttrade-ticks");
    for (const argument of ['"sync",', '"--frozen",', '"--all-packages",', '"--no-install-package",']) {
      expect(powershell).toContain(argument);
    }
    expect(powershell).toContain('"flinttrade-ticks",');
    expect(combined).toContain("pnpm 10.34.5");
    expect(combined).toContain("--frozen-lockfile");
    expect(combined).toContain("COREPACK_HOME");
    expect(combined).toContain("UV_CACHE_DIR");
    expect(combined).toContain("UV_MANAGED_PYTHON");
    expect(combined).toContain("UV_NO_EDITABLE");
    expect(combined).toContain("UV_NO_CONFIG");
    expect(combined).toContain("UV_PROJECT");
    expect(combined).toContain("UV_PROJECT_ENVIRONMENT");
    expect(combined).toContain("UV_PYTHON_INSTALL_DIR");
    expect(combined).toContain("UV_WORKING_DIR");
    expect(posix).toContain("python install 3.12 --no-bin");
    expect(powershell).toContain('"--no-bin",');
    expect(powershell).toContain('"--no-registry",');
    expect(posix).toContain(
      '"$uv" venv --relocatable --python 3.12 "$staging_virtual_environment"',
    );
    for (const argument of ['"venv",', '"--relocatable",', '"--python",', '"3.12",']) {
      expect(powershell).toContain(argument);
    }
    expect(powershell).toContain("$stagingVirtualEnvironmentPath,");
    expect(posix).toContain(
      'safe_rename_directory "$backup_virtual_environment" "$candidate/.venv"',
    );
    expect(posix).toContain(
      'safe_rename_directory "$staging_virtual_environment" "$candidate/.venv"',
    );
    expect(powershell).toContain(
      "[IO.Directory]::Move($backupVirtualEnvironmentPath, $virtualEnvironmentPath)",
    );
    expect(combined).not.toContain("--clear");
    expect(combined).not.toContain("--allow-existing");
    expect(posix.indexOf('"$uv" venv --relocatable')).toBeLessThan(
      posix.indexOf('"$uv" sync --frozen'),
    );
    expect(powershell.indexOf('"venv",')).toBeLessThan(powershell.indexOf('"sync",'));
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
