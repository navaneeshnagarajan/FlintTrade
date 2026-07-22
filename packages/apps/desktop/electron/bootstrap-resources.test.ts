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
    expect(builder).not.toContain("shell:");
  });

  it.runIf(process.platform === "win32" || Boolean(process.env.CI))(
    "parses the PowerShell entrypoint when PowerShell is available",
    () => {
      const executable = process.platform === "win32" ? "powershell.exe" : "pwsh";
      const probe = spawnSync(executable, ["-NoProfile", "-NonInteractive", "-Command", "exit 0"]);
      if (probe.error) return;
      const parsed = spawnSync(executable, [
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        `[void][scriptblock]::Create((Get-Content -Raw -LiteralPath $args[0]))`,
        powershellScript,
      ]);
      expect(parsed.status).toBe(0);
    },
  );
});
