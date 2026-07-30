import { execFileSync, spawn } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { mkdirSync, renameSync, symlinkSync, truncateSync, writeFileSync } from "node:fs";
import { access, appendFile, lstat, mkdir, mkdtemp, readFile, readdir, realpath, rename, rm, stat, symlink, writeFile } from "node:fs/promises";
import https from "node:https";
import { EventEmitter, once } from "node:events";
import type { IncomingMessage } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { Readable } from "node:stream";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  applyWindowsSupervisorLocalState,
  buildWindowsSupervisorInvocation,
  createNodeBootstrapDependencies,
  currentBootIdentity,
  minimalChildEnvironment,
  parseWindowsSupervisorProof,
  resolveWindowsExecutable,
  systemGitCandidates,
  syncDirectoryForDurability,
  validateArchiveEntries,
  validateTarLinkEntries,
  windowsSupervisorControlLine,
} from "./bootstrap-io";

const roots: string[] = [];

async function sha256File(target: string): Promise<string> {
  return createHash("sha256").update(await readFile(target)).digest("hex");
}

/**
 * How long the orphan-containment fixture's descendant waits before writing its
 * marker.
 *
 * Sized against the containment path it is testing: that sends SIGTERM to the
 * process group and then allows up to 2s for the group to settle before
 * escalating to SIGKILL. A descendant that writes inside that window can win the
 * race on a busy runner without the product being wrong, because the guarantee
 * is that no orphan SURVIVES, not that no orphan executes an instruction. 4s
 * leaves the settle window comfortable headroom while keeping the test well
 * inside its 15s budget.
 */
const DESCENDANT_WRITE_MS = 4_000;

const TEST_WINDOWS_NATIVE_IDENTITY = "0000000000000001:00000000000000000000000000000001";
const TEST_WINDOWS_NATIVE_IDENTITY_DRIFT = "0000000000000002:00000000000000000000000000000002";

async function testAtomicPromote(
  source: string,
  destination: string,
  expected: { dev: number; ino: number },
): Promise<void> {
  const sourceMetadata = await lstat(source);
  if (sourceMetadata.dev !== expected.dev || sourceMetadata.ino !== expected.ino) {
    throw new Error("test atomic promotion source identity mismatch");
  }
  try {
    await lstat(destination);
    const occupied = new Error("Promotion destination already exists; refusing to replace it.") as NodeJS.ErrnoException;
    occupied.code = "EEXIST";
    throw occupied;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  await rename(source, destination);
}

function atomicPromotionTestHooks() {
  return {
    testAtomicPromote,
    async testNativeDirectoryIdentity() {
      return TEST_WINDOWS_NATIVE_IDENTITY;
    },
  };
}

function fakeHttpsRequest(
  response?: { body?: Buffer; headers?: Record<string, string>; location?: string; statusCode: number },
) {
  const request = new EventEmitter() as EventEmitter & {
    destroy(error?: Error): void;
    setTimeout(milliseconds: number, callback: () => void): void;
    unref?(): void;
  };
  request.setTimeout = vi.fn();
  request.destroy = (error?: Error) => {
    if (error) queueMicrotask(() => request.emit("error", error));
    queueMicrotask(() => request.emit("close"));
  };
  const implementation = ((
    _url: string | URL | https.RequestOptions,
    optionsOrCallback?: https.RequestOptions | ((response: IncomingMessage) => void),
    callback?: (response: IncomingMessage) => void,
  ) => {
    const receive = typeof optionsOrCallback === "function" ? optionsOrCallback : callback;
    if (response) {
      const stream = Readable.from(response.body ? [response.body] : []) as Readable & {
        headers: Record<string, string>;
        statusCode: number;
      };
      stream.headers = {
        ...(response.headers ?? {}),
        ...(response.location ? { location: response.location } : {}),
      };
      stream.statusCode = response.statusCode;
      stream.once("end", () => request.emit("close"));
      queueMicrotask(() => receive?.(stream as never));
    }
    return request as never;
  }) as unknown as typeof https.get;
  const get = vi.spyOn(https, "get").mockImplementation(implementation);
  return { get, request };
}

function fakeUnsettledHttpsResponse(statusCode: number, headers: Record<string, string> = {}) {
  const response = new EventEmitter() as EventEmitter & {
    closed: boolean;
    destroy(): void;
    destroyed: boolean;
    headers: Record<string, string>;
    statusCode: number;
  };
  response.closed = false;
  response.destroyed = false;
  response.headers = headers;
  response.statusCode = statusCode;
  response.destroy = () => {
    response.destroyed = true;
  };
  const request = new EventEmitter() as EventEmitter & {
    destroy(error?: Error): void;
    setTimeout(milliseconds: number, callback: () => void): void;
    unref?(): void;
  };
  request.setTimeout = vi.fn();
  request.destroy = (error?: Error) => {
    if (error) queueMicrotask(() => request.emit("error", error));
  };
  const get = vi.spyOn(https, "get").mockImplementation(((
    _url: string | URL,
    _options: https.RequestOptions,
    callback?: (incoming: IncomingMessage) => void,
  ) => {
    queueMicrotask(() => callback?.(response as never));
    return request as never;
  }) as unknown as typeof https.get);
  return {
    close() {
      response.closed = true;
      response.emit("close");
    },
    get,
    response,
  };
}

afterEach(async () => {
  // A test that times out under fake timers is abandoned mid-await, so its own
  // restore never runs; restoring here keeps one failure from freezing every
  // later timer-dependent test in the file.
  vi.useRealTimers();
  await Promise.all(
    roots.splice(0).map((root) => rm(root, { force: true, maxRetries: 8, recursive: true, retryDelay: 25 })),
  );
});

describe("boot-session identity", () => {
  it.runIf(["darwin", "linux", "win32"].includes(process.platform))(
    "reads one stable identity from the current operating-system boot",
    () => {
      const first = currentBootIdentity();
      expect(currentBootIdentity()).toBe(first);
      expect(first).toMatch(new RegExp(`^${process.platform}:`));
    },
  );

  it("uses the Linux kernel boot UUID", () => {
    const readTextFile = vi.fn(() => "550e8400-e29b-41d4-a716-446655440000\n");
    const runFile = vi.fn(() => {
      throw new Error("Linux boot identity must not execute a helper.");
    });

    expect(currentBootIdentity("linux", {
      environment: {},
      readTextFile,
      runFile,
    })).toBe("linux:550e8400-e29b-41d4-a716-446655440000");
    expect(readTextFile).toHaveBeenCalledWith("/proc/sys/kernel/random/boot_id");
    expect(runFile).not.toHaveBeenCalled();
  });

  it("uses the macOS kernel boot-session UUID", () => {
    const readTextFile = vi.fn(() => {
      throw new Error("macOS boot identity must not read a Linux proc file.");
    });
    const runFile = vi.fn(() => "1FF26852-A2F9-4E02-9430-FE79DE2AEAD0\n");

    expect(currentBootIdentity("darwin", {
      environment: {},
      readTextFile,
      runFile,
    })).toBe("darwin:1ff26852-a2f9-4e02-9430-fe79de2aead0");
    expect(runFile).toHaveBeenCalledWith("/usr/sbin/sysctl", ["-n", "kern.bootsessionuuid"]);
    expect(readTextFile).not.toHaveBeenCalled();
  });

  it("uses the Windows operating-system boot timestamp", () => {
    const readTextFile = vi.fn(() => {
      throw new Error("Windows boot identity must not read a Linux proc file.");
    });
    const runFile = vi.fn(() => "134132876543210000\r\n");

    expect(currentBootIdentity("win32", {
      environment: { SystemRoot: "C:\\Windows" },
      readTextFile,
      runFile,
    })).toBe("win32:134132876543210000");
    expect(runFile).toHaveBeenCalledWith(
      "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
      expect.arrayContaining(["-NoProfile", "-NonInteractive", "-Command"]),
    );
    expect(readTextFile).not.toHaveBeenCalled();
  });

  it.each([
    ["linux", "not-a-kernel-uuid"],
    ["darwin", "not-a-kernel-uuid"],
    ["win32", "not-a-file-time"],
  ] as const)("fails closed for an invalid %s boot identity", (platform, output) => {
    expect(() => currentBootIdentity(platform, {
      environment: { SystemRoot: "C:\\Windows" },
      readTextFile: () => output,
      runFile: () => output,
    })).toThrow(`Authoritative ${platform} boot-session identity is unavailable.`);
  });
});

describe("bootstrap system boundaries", () => {
  it("constructs a minimal child environment and strips secret-bearing canaries", () => {
    const environment = minimalChildEnvironment(
      {
        BROKER_API_KEY: "override-canary",
        COREPACK_HOME: "/managed/corepack",
        PATH: "/managed/bin",
      },
      {
        ACCESS_TOKEN: "inherited-canary",
        FLINTTRADE_SAFETY_GATE_SECRET: "safety-canary",
        HOME: "/managed/home",
        PATH: "/usr/bin:/bin",
      },
    );

    expect(environment).toEqual({
      COREPACK_HOME: "/managed/corepack",
      HOME: "/managed/home",
      PATH: "/managed/bin",
    });
    expect(JSON.stringify(environment)).not.toContain("canary");
  });

  it("admits candidate-health isolation only from explicit managed overrides", () => {
    const environment = minimalChildEnvironment(
      {
        FLINTTRADE_DESKTOP: "1",
        FLINTTRADE_FRONTEND_DIST: "/candidate/terminal/dist",
        FLINTTRADE_HOME: "/isolated/flinttrade-home",
        FLINTTRADE_WORKSPACE_DIR: "/isolated/workspace",
        HOME: "/isolated/home",
        PYTHONNOUSERSITE: "1",
      },
      {
        FLINTTRADE_HOME: "/inherited-canary",
        FLINTTRADE_WORKSPACE_DIR: "/inherited-workspace-canary",
        OPENAI_API_KEY: "secret-canary",
      },
    );

    expect(environment).toEqual({
      FLINTTRADE_DESKTOP: "1",
      FLINTTRADE_FRONTEND_DIST: "/candidate/terminal/dist",
      FLINTTRADE_HOME: "/isolated/flinttrade-home",
      FLINTTRADE_WORKSPACE_DIR: "/isolated/workspace",
      HOME: "/isolated/home",
      PYTHONNOUSERSITE: "1",
    });
    expect(JSON.stringify(environment)).not.toContain("canary");
  });

  it.runIf(process.platform !== "win32")(
    "runs an exact managed child environment without inherited profile or proxy credentials",
    async () => {
      const dependencies = createNodeBootstrapDependencies(process.platform, {
        environment: {
          HTTPS_PROXY: "https://user:proxy-canary@example.invalid",
          PATH: process.env.PATH,
          USERPROFILE: "/real/profile-canary",
        },
      });
      const result = await dependencies.command.run({
        args: [
          "-e",
          "process.stdout.write(JSON.stringify({home:process.env.HOME,proxy:process.env.HTTPS_PROXY,profile:process.env.USERPROFILE}))",
        ],
        command: process.execPath,
        env: { HOME: "/isolated/home", PYTHONNOUSERSITE: "1" },
        inheritEnvironment: false,
        timeoutMs: 5_000,
      });

      expect(result).toMatchObject({ contained: true, exitCode: 0 });
      expect(JSON.parse(result.stdout)).toEqual({ home: "/isolated/home" });
      expect(result.stdout).not.toContain("canary");
    },
  );

  it.runIf(process.platform !== "win32")(
    "distinguishes a dangling no-follow path from an access-visible path",
    async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-no-follow-exists-"));
    roots.push(root);
    const dangling = path.join(root, ".env");
    await symlink(path.join(root, "missing-secret-file"), dangling);
    const fileSystem = createNodeBootstrapDependencies(process.platform).fileSystem;

    await expect(fileSystem.exists(dangling)).resolves.toBe(false);
    await expect(fileSystem.existsNoFollow(dangling)).resolves.toBe(true);
    },
  );

  it("normalises Windows environment keys case-insensitively into one deterministic spelling", () => {
    const environment = (minimalChildEnvironment as unknown as (
      overrides: NodeJS.ProcessEnv,
      inherited: NodeJS.ProcessEnv,
      platform: NodeJS.Platform,
    ) => NodeJS.ProcessEnv)(
      { Path: "C:\\managed\\bin" },
      {
        COMSPEC: "C:\\Windows\\System32\\cmd.exe",
        ComSpec: "C:\\canary\\cmd.exe",
        COREPACK_HOME: "C:\\inherited-bootstrap-canary",
        FLINTTRADE_BOOTSTRAP_NODE: "C:\\inherited-node-canary.exe",
        PATH: "C:\\inherited-upper",
        Path: "C:\\inherited-title",
        SystemRoot: "C:\\Windows",
      },
      "win32",
    );

    expect(environment).toEqual({
      COMSPEC: "C:\\Windows\\System32\\cmd.exe",
      PATH: "C:\\managed\\bin",
      SystemRoot: "C:\\Windows",
    });
    expect(Object.keys(environment).filter((key) => key.toLowerCase() === "path")).toHaveLength(1);
    expect(Object.keys(environment).filter((key) => key.toLowerCase() === "comspec")).toHaveLength(1);
    expect(JSON.stringify(environment)).not.toContain("canary");
  });

  it("accepts Windows bootstrap configuration only from explicit managed overrides", () => {
    const environment = (minimalChildEnvironment as unknown as (
      overrides: NodeJS.ProcessEnv,
      inherited: NodeJS.ProcessEnv,
      platform: NodeJS.Platform,
    ) => NodeJS.ProcessEnv)(
      { corepack_home: "C:\\managed\\corepack", flinttrade_bootstrap_node: "C:\\managed\\node.exe" },
      { COREPACK_HOME: "C:\\inherited-canary", FLINTTRADE_BOOTSTRAP_NODE: "C:\\inherited-canary.exe" },
      "win32",
    );

    expect(environment).toEqual({
      COREPACK_HOME: "C:\\managed\\corepack",
      FLINTTRADE_BOOTSTRAP_NODE: "C:\\managed\\node.exe",
    });
    expect(JSON.stringify(environment)).not.toContain("canary");
  });

  it("normalises explicit Windows candidate-health isolation overrides", () => {
    const environment = (minimalChildEnvironment as unknown as (
      overrides: NodeJS.ProcessEnv,
      inherited: NodeJS.ProcessEnv,
      platform: NodeJS.Platform,
    ) => NodeJS.ProcessEnv)(
      {
        flinttrade_desktop: "1",
        flinttrade_frontend_dist: "C:\\Candidate\\terminal\\dist",
        flinttrade_home: "C:\\Isolated\\home",
        flinttrade_workspace_dir: "C:\\Isolated\\workspace",
        pythonnousersite: "1",
      },
      {
        FLINTTRADE_HOME: "C:\\inherited-canary",
        PYTHONNOUSERSITE: "inherited-canary",
      },
      "win32",
    );

    expect(environment).toEqual({
      FLINTTRADE_DESKTOP: "1",
      FLINTTRADE_FRONTEND_DIST: "C:\\Candidate\\terminal\\dist",
      FLINTTRADE_HOME: "C:\\Isolated\\home",
      FLINTTRADE_WORKSPACE_DIR: "C:\\Isolated\\workspace",
      PYTHONNOUSERSITE: "1",
    });
    expect(JSON.stringify(environment)).not.toContain("canary");
  });

  it("constructs the token-bound Windows Job supervisor protocol without shell quoting", () => {
    const token = "ab".repeat(16);
    const expectedTargetSha256 = "cd".repeat(32);
    const invocation = buildWindowsSupervisorInvocation({
      args: ["plain", "space value", 'quote"value', "trailing\\"],
      cwd: "C:\\Flint Trade\\source",
      expectedTargetSha256,
      helper: "C:\\Flint\\flinttrade-job-supervisor.exe",
      parentPid: 42,
      target: "C:\\Tools\\node.exe",
      token,
    });

    expect(invocation).toEqual({
      command: "C:\\Flint\\flinttrade-job-supervisor.exe",
      args: [
        "--protocol",
        "1",
        "--token",
        token,
        "--parent-pid",
        "42",
        "--cwd",
        "C:\\Flint Trade\\source",
        "--target-sha256",
        expectedTargetSha256,
        "--",
        "C:\\Tools\\node.exe",
        "plain",
        "space value",
        'quote"value',
        "trailing\\",
      ],
    });
    expect(windowsSupervisorControlLine(token, "timeout")).toBe(
      `FLINTTRADE_JOB_TERMINATE\t1\t${token}\ttimeout\n`,
    );
    expect(() => buildWindowsSupervisorInvocation({
      args: [],
      expectedTargetSha256: "CD".repeat(32),
      helper: "C:\\Flint\\flinttrade-job-supervisor.exe",
      parentPid: 42,
      target: "C:\\Tools\\node.exe",
      token,
    })).toThrow(/lowercase digest/i);
  });

  it.each([
    ["natural", 0, 0],
    ["natural", 7, 7],
    ["orphan-drained", 0, 1],
    ["cancel", 1, 130],
    ["shutdown", 1, 130],
    ["parent-lost", 1, 130],
    ["timeout", 1, 124],
    ["listener", 1, 1],
    ["control-error", 1, 1],
    ["setup-failed", 127, 127],
  ])("accepts an exact final Windows settlement proof for %s", (reason, leaderExit, helperExit) => {
    const token = "cd".repeat(16);
    const parsed = parseWindowsSupervisorProof(
      `target error\n\nFLINTTRADE_JOB_SUPERVISOR\t1\t${token}\tsettled\t${reason}\t${leaderExit}\t0\n`,
      token,
      helperExit,
      false,
    );

    expect(parsed).toEqual({ contained: true, exitCode: helperExit, stderr: "target error\n" });
  });

  it("rejects an otherwise exact Windows settlement proof when stderr was truncated", () => {
    const token = "ab".repeat(16);
    const stderr = `FLINTTRADE_JOB_SUPERVISOR\t1\t${token}\tsettled\tnatural\t0\t0\n`;

    expect(parseWindowsSupervisorProof(stderr, token, 0, true).contained).toBe(false);
  });

  it("rejects missing, duplicate, malformed, token-mismatched and exit-inconsistent Windows proofs", () => {
    const token = "ef".repeat(16);
    const proof = `FLINTTRADE_JOB_SUPERVISOR\t1\t${token}\tsettled\tnatural\t0\t0`;
    for (const [stderr, exitCode] of [
      ["target stderr", 0],
      [`${proof}\n${proof}\n`, 0],
      [`${proof}\ntrailing\n`, 0],
      [`${proof.replace(token, "00".repeat(16))}\n`, 0],
      [`${proof.replace("\t0\t0", "\t0\t1")}\n`, 0],
      [`${proof}\n`, 1],
    ] as const) {
      expect(parseWindowsSupervisorProof(stderr, token, exitCode, false).contained).toBe(false);
    }
  });

  it.each([
    [{ cancelled: false, listenerFailure: true, timedOut: false }, 1],
    [{ cancelled: false, listenerFailure: false, timedOut: true }, 124],
    [{ cancelled: true, listenerFailure: false, timedOut: false }, 130],
  ])("keeps valid Windows containment proof while local terminal state maps to %s", (local, exitCode) => {
    expect(
      applyWindowsSupervisorLocalState({ contained: true, exitCode: 0, stderr: "" }, local),
    ).toEqual({ contained: true, exitCode, stderr: "" });
  });

  it("resolves only no-follow absolute Windows executables from trusted PATH entries", () => {
    const existing = new Set(["C:\\Trusted\\git.exe", "C:\\Tools\\node.exe"]);
    const fileExists = (target: string) => existing.has(target);
    const environment = { PATH: "relative;C:\\Trusted;C:\\Canary" };

    const canonicalise = (target: string) => target;
    expect(resolveWindowsExecutable("git", environment, fileExists, canonicalise)).toBe("C:\\Trusted\\git.exe");
    expect(resolveWindowsExecutable("C:\\Tools\\node.exe", environment, fileExists, canonicalise)).toBe("C:\\Tools\\node.exe");
    expect(resolveWindowsExecutable("script.cmd", environment, fileExists, canonicalise)).toBeNull();
    expect(resolveWindowsExecutable("..\\git.exe", environment, fileExists, canonicalise)).toBeNull();

    const canonicalEnvironment = (minimalChildEnvironment as unknown as (
      overrides: NodeJS.ProcessEnv,
      inherited: NodeJS.ProcessEnv,
      platform: NodeJS.Platform,
    ) => NodeJS.ProcessEnv)({}, { Path: "C:\\Canary", PATH: "C:\\Trusted" }, "win32");
    expect(resolveWindowsExecutable("git", canonicalEnvironment, fileExists, canonicalise)).toBe("C:\\Trusted\\git.exe");
    expect(
      resolveWindowsExecutable(
        "C:\\Trusted\\..\\Trusted\\git.exe",
        environment,
        (target) => target === "C:\\Trusted\\..\\Trusted\\git.exe" || target === "C:\\Volume\\git.exe",
        () => "C:\\Volume\\git.exe",
      ),
    ).toBe("C:\\Volume\\git.exe");
  });

  it("derives Windows Git only from the system drive and never from inherited PATH", () => {
    expect(systemGitCandidates("win32", {
      PATH: "D:\\attacker-bin",
      SystemRoot: "C:\\Windows",
    })).toEqual([
      "C:\\Program Files\\Git\\cmd\\git.exe",
      "C:\\Program Files\\Git\\bin\\git.exe",
    ]);
    expect(systemGitCandidates("win32", { PATH: "D:\\attacker-bin", SystemRoot: "relative" })).toEqual([]);
  });

  it.runIf(process.platform !== "win32")(
    "ignores an inherited PATH Git and executes the identity-bound system Git",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-untrusted-git-"));
      roots.push(root);
      const marker = path.join(root, "path-git-executed");
      await writeFile(
        path.join(root, "git"),
        `#!/bin/sh\nprintf compromised > '${marker}'\n`,
        { mode: 0o755 },
      );
      const dependencies = createNodeBootstrapDependencies(process.platform, {
        environment: { ...process.env, PATH: root },
      });

      await expect(
        dependencies.command.run({ args: ["--version"], command: "git", timeoutMs: 30_000 }),
      ).resolves.toMatchObject({ contained: true, exitCode: 0, stdout: expect.stringMatching(/^git version /) });
      await expect(access(marker)).rejects.toThrow();
    },
  );

  it.runIf(process.platform !== "win32")(
    "fails Git closed when its captured executable identity changes before spawn",
    async () => {
      const candidate = "/trusted/system/git";
      const captured = {
        canonicalPath: candidate,
        ctimeMs: 1,
        dev: 2,
        ino: 3,
        mode: 0o100755,
        mtimeMs: 4,
        size: 5,
      };
      let inspections = 0;
      const dependencies = createNodeBootstrapDependencies(process.platform, {
        testHooks: {
          inspectTrustedGit: () => ({ ...captured, size: inspections++ === 0 ? 5 : 6 }),
        },
        trustedGitCandidates: [candidate],
      });

      await expect(dependencies.command.run({ args: ["--version"], command: "git" })).resolves.toEqual({
        contained: true,
        exitCode: 127,
        stderr: "Verified system Git is unavailable.",
        stderrTruncated: false,
        stdout: "",
        stdoutTruncated: false,
      });
    },
  );

  it("fails Windows commands closed when the compiled Job supervisor is absent", async () => {
    const dependencies = createNodeBootstrapDependencies("win32", {
      environment: { PATH: "C:\\Trusted", SystemRoot: "C:\\Windows" },
      fileExists: () => false,
      windowsJobSupervisor: "C:\\Flint\\flinttrade-job-supervisor.exe",
    });

    await expect(dependencies.command.run({ args: [], command: "git" })).resolves.toEqual({
      contained: true,
      exitCode: 127,
      stderr: "Verified Windows Job supervisor is unavailable.",
      stderrTruncated: false,
      stdout: "",
      stdoutTruncated: false,
    });
  });

  it("treats a missing Windows command as a contained nonzero result before spawn", async () => {
    const helper = "C:\\Flint\\flinttrade-job-supervisor.exe";
    const powerShell = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe";
    const existing = new Set([helper, powerShell]);
    const dependencies = createNodeBootstrapDependencies("win32", {
      canonicalisePath: (target) => target,
      environment: { PATH: "", SystemRoot: "C:\\Windows" },
      fileExists: (target) => existing.has(target),
      windowsJobSupervisor: helper,
    });

    await expect(dependencies.command.run({ args: ["--version"], command: "git" })).resolves.toEqual({
      contained: true,
      exitCode: 127,
      stderr: "Verified system Git is unavailable.",
      stderrTruncated: false,
      stdout: "",
      stdoutTruncated: false,
    });
  });

  it("supervises an output-callback exception and settles the command as failed", async () => {
    const dependencies = createNodeBootstrapDependencies(process.platform);
    const result = await dependencies.command.run({
      args: ["-e", "console.log('first line'); setInterval(() => {}, 1000)"],
      command: process.execPath,
      onOutput: () => {
        throw new Error("output callback exploded");
      },
      timeoutMs: 30_000,
    });

    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain("Output listener failed: output callback exploded");
  });

  it("rejects download credentials, fragments and unapproved redirect hosts", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-download-policy-"));
    roots.push(root);
    const dependencies = createNodeBootstrapDependencies(process.platform);
    const policy = {
      allowedHosts: ["nodejs.org"],
      idleTimeoutMs: 1_000,
      label: "test asset",
      maxBytes: 1024,
      totalTimeoutMs: 1_000,
    };
    await expect(
      dependencies.download.file(
        "https://user:password@nodejs.org/tool#fragment",
        path.join(root, "credentialed"),
        new AbortController().signal,
        policy,
      ),
    ).rejects.toThrow(/credentials or a fragment/i);

    const fake = fakeHttpsRequest({ location: "https://evil.example/tool", statusCode: 302 });
    try {
      await expect(
        dependencies.download.file(
          "https://nodejs.org/tool",
          path.join(root, "redirected"),
          new AbortController().signal,
          policy,
        ),
      ).rejects.toThrow(/host is not approved/i);
      expect(fake.get).toHaveBeenCalledOnce();
    } finally {
      fake.get.mockRestore();
    }
  });

  it("enforces declared and streamed download byte limits and records final origin", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-download-bounds-"));
    roots.push(root);
    const dependencies = createNodeBootstrapDependencies(process.platform);
    const policy = {
      allowedHosts: ["nodejs.org"],
      idleTimeoutMs: 1_000,
      label: "test asset",
      maxBytes: 3,
      totalTimeoutMs: 1_000,
    };
    let fake = fakeHttpsRequest({ body: Buffer.from("four"), headers: { "content-length": "4" }, statusCode: 200 });
    try {
      await expect(
        dependencies.download.file(
          "https://nodejs.org/tool",
          path.join(root, "declared"),
          new AbortController().signal,
          policy,
        ),
      ).rejects.toThrow(/content length/i);
    } finally {
      fake.get.mockRestore();
    }

    fake = fakeHttpsRequest({ body: Buffer.from("four"), statusCode: 200 });
    try {
      await expect(
        dependencies.download.file(
          "https://nodejs.org/tool",
          path.join(root, "streamed"),
          new AbortController().signal,
          policy,
        ),
      ).rejects.toThrow(/size limit/i);
    } finally {
      fake.get.mockRestore();
    }

    fake = fakeHttpsRequest({ body: Buffer.from("ok"), statusCode: 200 });
    try {
      await expect(
        dependencies.download.file(
          "https://nodejs.org/tool",
          path.join(root, "valid"),
          new AbortController().signal,
          policy,
        ),
      ).resolves.toMatchObject({ bytes: 2, finalUrl: "https://nodejs.org/tool", origin: "https://nodejs.org" });
    } finally {
      fake.get.mockRestore();
    }
  });

  it("refuses to overwrite an existing download destination", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-download-no-clobber-"));
    roots.push(root);
    const destination = path.join(root, "foreign-asset");
    await writeFile(destination, "foreign");
    const dependencies = createNodeBootstrapDependencies(process.platform);
    const fake = fakeHttpsRequest({ body: Buffer.from("managed"), statusCode: 200 });
    try {
      await expect(
        dependencies.download.file(
          "https://nodejs.org/tool",
          destination,
          new AbortController().signal,
          {
            allowedHosts: ["nodejs.org"],
            idleTimeoutMs: 1_000,
            label: "test asset",
            maxBytes: 1024,
            totalTimeoutMs: 1_000,
          },
        ),
      ).rejects.toMatchObject({ code: "EEXIST" });
      expect(await readFile(destination, "utf8")).toBe("foreign");
    } finally {
      fake.get.mockRestore();
    }
  });

  it("enforces one total download deadline even when no response arrives", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-download-deadline-"));
    roots.push(root);
    const dependencies = createNodeBootstrapDependencies(process.platform);
    const fake = fakeHttpsRequest();
    try {
      await expect(
        dependencies.download.file(
          "https://nodejs.org/tool",
          path.join(root, "deadline"),
          new AbortController().signal,
          {
            allowedHosts: ["nodejs.org"],
            idleTimeoutMs: 10_000,
            label: "test asset",
            maxBytes: 1024,
            totalTimeoutMs: 25,
          },
        ),
      ).rejects.toThrow(/total deadline/i);
    } finally {
      fake.get.mockRestore();
    }
  });

  it("awaits response-consumer handle close and preserves the exclusive partial download on abort", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-download-abort-settlement-"));
    roots.push(root);
    const lifecycle: string[] = [];
    let handleOpened!: () => void;
    const opened = new Promise<void>((resolve) => {
      handleOpened = resolve;
    });
    const dependencies = createNodeBootstrapDependencies(process.platform, {
      testHooks: {
        onDownloadTemporaryLifecycle(event) {
          lifecycle.push(event);
          if (event === "handle-opened") handleOpened();
        },
      },
    });
    let sent = false;
    const response = new Readable({
      read() {
        if (!sent) {
          sent = true;
          this.push(Buffer.from("partial"));
        }
      },
    }) as Readable & { headers: Record<string, string>; statusCode: number };
    response.headers = {};
    response.statusCode = 200;
    const request = new EventEmitter() as EventEmitter & {
      destroy(error?: Error): void;
      setTimeout(milliseconds: number, callback: () => void): void;
      unref?(): void;
    };
    request.setTimeout = vi.fn();
    request.destroy = (error?: Error) => {
      queueMicrotask(() => {
        if (error) request.emit("error", error);
        request.emit("close");
      });
    };
    const get = vi.spyOn(https, "get").mockImplementation(((
      _url: string | URL,
      _options: https.RequestOptions,
      callback?: (response: IncomingMessage) => void,
    ) => {
      queueMicrotask(() => callback?.(response as never));
      return request as never;
    }) as unknown as typeof https.get);
    const abort = new AbortController();
    try {
      const running = dependencies.download.file(
        "https://nodejs.org/tool",
        path.join(root, "asset"),
        abort.signal,
        {
          allowedHosts: ["nodejs.org"],
          idleTimeoutMs: 10_000,
          label: "test asset",
          maxBytes: 1024,
          totalTimeoutMs: 10_000,
        },
      );
      await opened;
      abort.abort();

      await expect(running).rejects.toMatchObject({ name: "AbortError" });
      expect(lifecycle).toEqual(["handle-opened", "handle-closed"]);
      await expect(access(path.join(root, "asset"))).resolves.toBeUndefined();
      expect((await dependencies.fileSystem.listNames(root)).filter((name) => name.includes(".download-"))).toEqual([]);
    } finally {
      get.mockRestore();
    }
  });

  it("awaits close after destroying a slow HTTP error response", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-download-error-close-"));
    roots.push(root);
    const dependencies = createNodeBootstrapDependencies(process.platform);
    const response = new EventEmitter() as EventEmitter & {
      closed: boolean;
      destroy(): void;
      destroyed: boolean;
      headers: Record<string, string>;
      statusCode: number;
    };
    response.closed = false;
    response.destroyed = false;
    response.headers = {};
    response.statusCode = 503;
    response.destroy = () => {
      response.destroyed = true;
    };
    const request = new EventEmitter() as EventEmitter & {
      destroy(error?: Error): void;
      setTimeout(milliseconds: number, callback: () => void): void;
      unref?(): void;
    };
    request.setTimeout = vi.fn();
    request.destroy = (error?: Error) => {
      if (error) queueMicrotask(() => request.emit("error", error));
    };
    const get = vi.spyOn(https, "get").mockImplementation(((
      _url: string | URL,
      _options: https.RequestOptions,
      callback?: (incoming: IncomingMessage) => void,
    ) => {
      queueMicrotask(() => callback?.(response as never));
      return request as never;
    }) as unknown as typeof https.get);
    let settled = false;
    try {
      const running = dependencies.download.file(
        "https://nodejs.org/tool",
        path.join(root, "asset"),
        new AbortController().signal,
        {
          allowedHosts: ["nodejs.org"],
          idleTimeoutMs: 10_000,
          label: "test asset",
          maxBytes: 1024,
          totalTimeoutMs: 10_000,
        },
      );
      void running.then(
        () => {
          settled = true;
        },
        () => {
          settled = true;
        },
      );
      await vi.waitFor(() => expect(response.destroyed).toBe(true), { timeout: 15_000 });
      expect(settled).toBe(false);
      response.closed = true;
      response.emit("close");

      await expect(running).rejects.toThrow(/status 503/i);
      expect(settled).toBe(true);
    } finally {
      get.mockRestore();
    }
  });

  it.each([
    ["invalid Content-Length", { headers: { "content-length": "4096" }, openFailure: false }],
    ["temporary-open failure", { headers: {}, openFailure: true }],
  ] as const)("awaits close after a slow 200 response hits %s", async (_label, scenario) => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-download-200-close-"));
    roots.push(root);
    const dependencies = createNodeBootstrapDependencies(process.platform, {
      testHooks: {
        beforeDownloadTemporaryOpen() {
          if (scenario.openFailure) throw new Error("temporary open failed");
        },
      },
    });
    const fake = fakeUnsettledHttpsResponse(200, scenario.headers);
    let settled = false;
    try {
      const running = dependencies.download.file(
        "https://nodejs.org/tool",
        path.join(root, "asset"),
        new AbortController().signal,
        {
          allowedHosts: ["nodejs.org"],
          idleTimeoutMs: 10_000,
          label: "test asset",
          maxBytes: 1024,
          totalTimeoutMs: 10_000,
        },
      );
      void running.then(
        () => {
          settled = true;
        },
        () => {
          settled = true;
        },
      );
      await vi.waitFor(() => expect(fake.response.destroyed).toBe(true), { timeout: 15_000 });
      expect(settled).toBe(false);
      fake.close();

      await expect(running).rejects.toThrow(scenario.openFailure ? /temporary open failed/i : /content length/i);
      expect(settled).toBe(true);
    } finally {
      fake.get.mockRestore();
    }
  });

  it("completes a download across simulated short writes", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-download-short-write-"));
    roots.push(root);
    const destination = path.join(root, "asset");
    const dependencies = createNodeBootstrapDependencies(process.platform, {
      testHooks: { downloadWriteChunkBytes: 1 },
    });
    const fake = fakeHttpsRequest({ body: Buffer.from("complete"), statusCode: 200 });
    try {
      await expect(
        dependencies.download.file(
          "https://nodejs.org/tool",
          destination,
          new AbortController().signal,
          {
            allowedHosts: ["nodejs.org"],
            idleTimeoutMs: 1_000,
            label: "test asset",
            maxBytes: 1024,
            totalTimeoutMs: 1_000,
          },
        ),
      ).resolves.toMatchObject({ bytes: 8 });
      expect(await readFile(destination, "utf8")).toBe("complete");
    } finally {
      fake.get.mockRestore();
    }
  });
  it("runs a probed command and captures bounded output", async () => {
    const dependencies = createNodeBootstrapDependencies(process.platform);
    const result = await dependencies.command.run({
      args: ["-e", "process.stdout.write('probe-ok')"],
      command: process.execPath,
      timeoutMs: 5_000,
    });

    expect(result).toEqual({
      contained: true,
      exitCode: 0,
      stderr: "",
      stderrTruncated: false,
      stdout: "probe-ok",
      stdoutTruncated: false,
    });
  });

  it.runIf(process.platform !== "win32")(
    "durably registers the POSIX anchor before launch and unregisters before release",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-command-lease-"));
      roots.push(root);
      const target = path.join(root, ".flinttrade-bootstrap-operation.lock");
      const dependencies = createNodeBootstrapDependencies(process.platform, { operationLeaseTarget: target });
      const releaseLease = await dependencies.fileSystem.acquireOperationLock({
        bootIdentity: "current-boot",
        ownerPid: process.pid,
        singletonAuthorised: true,
        target,
      });

      await expect(
        dependencies.command.run({ args: ["-e", "process.stdout.write('registered')"], command: process.execPath }),
      ).resolves.toMatchObject({ contained: true, exitCode: 0, stdout: "registered" });
      expect(await dependencies.fileSystem.listNames(target)).toEqual(["owner.json"]);
      await releaseLease();
    },
  );

  it("refuses containment reconciliation without an active same-process lease", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-command-reproof-owner-"));
    roots.push(root);
    const target = path.join(root, ".flinttrade-bootstrap-operation.lock");
    const dependencies = createNodeBootstrapDependencies(process.platform, { operationLeaseTarget: target });

    await expect(dependencies.command.reconcileOperationContainment()).rejects.toThrow(/active same-process/i);
  });

  it.runIf(process.platform !== "win32")(
    "retries a transient directory-sync failure after removing the process-anchor record",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-command-release-sync-"));
      roots.push(root);
      const target = path.join(root, ".flinttrade-bootstrap-operation.lock");
      let releaseSyncAttempts = 0;
      const dependencies = createNodeBootstrapDependencies(process.platform, {
        operationLeaseTarget: target,
        testHooks: {
          beforeProcessAnchorReleaseStage(stage) {
            if (stage === "directory-sync" && ++releaseSyncAttempts === 1) {
              throw new Error("injected process-anchor directory sync failure");
            }
          },
        },
      });
      const releaseLease = await dependencies.fileSystem.acquireOperationLock({
        bootIdentity: "current-boot",
        ownerPid: process.pid,
        singletonAuthorised: true,
        target,
      });

      await expect(
        dependencies.command.run({ args: ["-e", "process.stdout.write('registered')"], command: process.execPath }),
      ).resolves.toMatchObject({ contained: true, exitCode: 0, stdout: "registered" });
      expect(releaseSyncAttempts).toBe(2);
      expect(await dependencies.fileSystem.listNames(target)).toEqual(["owner.json"]);
      await releaseLease();
    },
  );

  it("bounds unterminated output tails and reports both streams as truncated", async () => {
    const output: Array<{ line: string; stream: "stderr" | "stdout" }> = [];
    const result = await createNodeBootstrapDependencies(process.platform).command.run({
      args: [
        "-e",
        "process.stdout.write('x'.repeat(512*1024));process.stderr.write('y'.repeat(512*1024))",
      ],
      command: process.execPath,
      onOutput: (line, stream) => output.push({ line, stream }),
      timeoutMs: 5_000,
    });

    expect(result).toMatchObject({
      contained: true,
      exitCode: 0,
      stderrTruncated: true,
      stdoutTruncated: true,
    });
    expect(result.stdout).toHaveLength(256 * 1024);
    expect(result.stderr).toHaveLength(256 * 1024);
    expect(output).toEqual(expect.arrayContaining([
      { line: "x".repeat(256 * 1024), stream: "stdout" },
      { line: "y".repeat(256 * 1024), stream: "stderr" },
    ]));
  });

  it("bounds cancellation of a child command", async () => {
    const dependencies = createNodeBootstrapDependencies(process.platform);
    const abort = new AbortController();
    const running = dependencies.command.run({
      args: ["-e", "setInterval(() => {}, 1000)"],
      command: process.execPath,
      signal: abort.signal,
      timeoutMs: 30_000,
    });
    abort.abort();

    await expect(running).resolves.toMatchObject({ exitCode: 130 });
  });

  it.runIf(process.platform !== "win32")("cancels descendant processes in the command process group", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-tree-"));
    roots.push(root);
    const marker = path.join(root, "descendant-survived");
    const dependencies = createNodeBootstrapDependencies(process.platform);
    const abort = new AbortController();
    const parent = [
      "const {spawn}=require('node:child_process');",
      "spawn(process.execPath,['-e',\"setTimeout(()=>require('node:fs').writeFileSync(process.argv[1],'alive'),600)\",process.argv[1]],{stdio:'ignore'});",
      "setInterval(()=>{},1000);",
    ].join("");
    const running = dependencies.command.run({
      args: ["-e", parent, marker],
      command: process.execPath,
      signal: abort.signal,
      timeoutMs: 30_000,
    });
    await new Promise((resolve) => setTimeout(resolve, 150));
    abort.abort();
    await expect(running).resolves.toMatchObject({ exitCode: 130 });
    await new Promise((resolve) => setTimeout(resolve, 700));

    await expect(access(marker)).rejects.toThrow();
  });

  it.runIf(process.platform !== "win32")(
    "does not settle cancellation until a SIGTERM-ignoring descendant is force-killed",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-stubborn-tree-"));
      roots.push(root);
      const marker = path.join(root, "descendant-survived");
      const leaseTarget = path.join(root, ".flinttrade-bootstrap-operation.lock");
      const dependencies = createNodeBootstrapDependencies(process.platform, {
        operationLeaseTarget: leaseTarget,
      });
      const releaseLease = await dependencies.fileSystem.acquireOperationLock({
        bootIdentity: "stubborn-descendant-test",
        ownerPid: process.pid,
        singletonAuthorised: true,
        target: leaseTarget,
      });
      const abort = new AbortController();
      const parent = [
        "const {spawn}=require('node:child_process');",
        "spawn(process.execPath,['-e',\"process.on('SIGTERM',()=>{});setTimeout(()=>require('node:fs').writeFileSync(process.argv[1],'alive'),6500);setInterval(()=>{},1000)\",process.argv[1]],{stdio:'ignore'});",
        "setInterval(()=>{},1000);",
      ].join("");
      const running = dependencies.command.run({
        args: ["-e", parent, marker],
        command: process.execPath,
        signal: abort.signal,
        timeoutMs: 30_000,
      });
      await new Promise((resolve) => setTimeout(resolve, 200));
      abort.abort();
      await expect(running).resolves.toMatchObject({ contained: true, exitCode: 130 });
      expect(await dependencies.fileSystem.listNames(leaseTarget)).toEqual(["owner.json"]);
      await releaseLease();
      await new Promise((resolve) => setTimeout(resolve, 1_700));

      await expect(access(marker)).rejects.toThrow();
    },
    12_000,
  );

  it.runIf(process.platform !== "win32")(
    "uses the durable token to drain an escaped child after forced anchor settlement",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-forced-token-drain-"));
      roots.push(root);
      const marker = path.join(root, "detached-descendant-survived");
      const leaseTarget = path.join(root, ".flinttrade-bootstrap-operation.lock");
      const delayedEnumerator = path.join(root, "delayed-ps");
      await writeFile(
        delayedEnumerator,
        [
          "#!/bin/sh",
          'state="$0.seen"',
          'if [ ! -e "$state" ]; then',
          '  : > "$state"',
          "  /bin/sleep 3",
          "fi",
          'if [ -x /bin/ps ]; then exec /bin/ps "$@"; fi',
          'exec /usr/bin/ps "$@"',
          "",
        ].join("\n"),
        { mode: 0o700 },
      );
      const dependencies = createNodeBootstrapDependencies(process.platform, {
        operationLeaseTarget: leaseTarget,
        posixProcessEnumerators: [delayedEnumerator],
      });
      const releaseLease = await dependencies.fileSystem.acquireOperationLock({
        bootIdentity: "forced-token-drain-test",
        ownerPid: process.pid,
        singletonAuthorised: true,
        target: leaseTarget,
      });
      const abort = new AbortController();
      let escapedPid = 0;
      const parent = [
        "const {spawn}=require('node:child_process');",
        "const child=spawn(process.execPath,['-e',\"process.on('SIGTERM',()=>{});process.stdout.write('ready\\\\n');setTimeout(()=>require('node:fs').writeFileSync(process.argv[1],'alive'),4500);setInterval(()=>{},1000)\",process.argv[1]],{detached:true,stdio:['ignore','pipe','ignore']});",
        "child.stdout.once('data',()=>process.stdout.write(`ready:${child.pid}\\n`));",
        "child.unref();",
        "setInterval(()=>{},1000);",
      ].join("");
      const running = dependencies.command.run({
        args: ["-e", parent, marker],
        command: process.execPath,
        onOutput(line) {
          const match = /^ready:([1-9][0-9]*)$/.exec(line);
          if (match) escapedPid = Number(match[1]);
        },
        signal: abort.signal,
        timeoutMs: 30_000,
      });
      await vi.waitFor(() => expect(escapedPid).toBeGreaterThan(0), { timeout: 15_000 });
      abort.abort();

      await expect(running).resolves.toMatchObject({ contained: true, exitCode: 130 });
      expect(await dependencies.fileSystem.listNames(leaseTarget)).toEqual(["owner.json"]);
      await releaseLease();
      await new Promise((resolve) => setTimeout(resolve, 2_500));
      await expect(access(marker)).rejects.toThrow();
    },
    15_000,
  );

  it.runIf(process.platform !== "win32")(
    "retains the durable record until a later same-process containment re-proof succeeds",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-forced-token-failure-"));
      roots.push(root);
      const marker = path.join(root, "detached-descendant-survived");
      const leaseTarget = path.join(root, ".flinttrade-bootstrap-operation.lock");
      const enumerator = path.join(root, "recoverable-ps");
      await writeFile(enumerator, "#!/bin/sh\nexit 1\n", { mode: 0o700 });
      const dependencies = createNodeBootstrapDependencies(process.platform, {
        operationLeaseTarget: leaseTarget,
        posixProcessEnumerators: [enumerator],
      });
      const releaseLease = await dependencies.fileSystem.acquireOperationLock({
        bootIdentity: "forced-token-failure-test",
        ownerPid: process.pid,
        singletonAuthorised: true,
        target: leaseTarget,
      });
      const abort = new AbortController();
      let escapedPid = 0;
      const parent = [
        "const {spawn}=require('node:child_process');",
        "const child=spawn(process.execPath,['-e',\"process.on('SIGTERM',()=>{});process.stdout.write('ready\\\\n');setTimeout(()=>require('node:fs').writeFileSync(process.argv[1],'alive'),4500);setInterval(()=>{},1000)\",process.argv[1]],{detached:true,stdio:['ignore','pipe','ignore']});",
        "child.stdout.once('data',()=>process.stdout.write(`ready:${child.pid}\\n`));",
        "child.unref();",
        "setInterval(()=>{},1000);",
      ].join("");
      try {
        const running = dependencies.command.run({
          args: ["-e", parent, marker],
          command: process.execPath,
          onOutput(line) {
            const match = /^ready:([1-9][0-9]*)$/.exec(line);
            if (match) escapedPid = Number(match[1]);
          },
          signal: abort.signal,
          timeoutMs: 30_000,
        });
        await vi.waitFor(() => expect(escapedPid).toBeGreaterThan(0), { timeout: 15_000 });
        abort.abort();

        await expect(running).resolves.toMatchObject({ contained: false });
        expect(() => process.kill(escapedPid, 0)).not.toThrow();
        expect(await dependencies.fileSystem.listNames(leaseTarget)).toEqual([
          "owner.json",
          expect.stringMatching(/^process-group-[1-9][0-9]*\.json$/),
        ]);
        await expect(dependencies.command.reconcileOperationContainment()).rejects.toThrow(/enumeration.*unavailable/i);
        await expect(releaseLease()).rejects.toThrow(/lease identity changed/i);
        await writeFile(
          enumerator,
          "#!/bin/sh\nif [ -x /bin/ps ]; then exec /bin/ps \"$@\"; fi\nexec /usr/bin/ps \"$@\"\n",
          { mode: 0o700 },
        );
        await expect(dependencies.command.reconcileOperationContainment()).resolves.toBeUndefined();
        expect(await dependencies.fileSystem.listNames(leaseTarget)).toEqual(["owner.json"]);
        await expect(releaseLease()).resolves.toBeUndefined();
      } finally {
        if (escapedPid > 0) {
          try {
            process.kill(-escapedPid, "SIGKILL");
          } catch (error) {
            if ((error as NodeJS.ErrnoException).code !== "ESRCH") throw error;
          }
        }
      }
      await new Promise((resolve) => setTimeout(resolve, 100));
      await expect(access(marker)).rejects.toThrow();
    },
    15_000,
  );

  it.runIf(process.platform !== "win32")(
    "clears the force-kill timer after a cancelled process exits",
    async () => {
      // Real timers throughout: faking the clock also froze every delay()/retry
      // inside the cancel path, so any transient write retry left this test — and,
      // via the leaked fake clock, every later timer-dependent test — hung on the
      // Linux runner. Waiting out the real 5s deadline verifies the same
      // behaviour: a cleared force-kill timer stays silent.
      const originalKill = process.kill.bind(process);
      const kill = vi.spyOn(process, "kill").mockImplementation((pid, signal) => originalKill(pid, signal));
      try {
        const dependencies = createNodeBootstrapDependencies(process.platform);
        const abort = new AbortController();
        const running = dependencies.command.run({
          args: ["-e", "setInterval(() => {}, 1000)"],
          command: process.execPath,
          signal: abort.signal,
          timeoutMs: 30_000,
        });
        abort.abort();
        await expect(running).resolves.toMatchObject({ exitCode: 130 });
        const terminationSignals = kill.mock.calls.filter((call) => call[1] === "SIGTERM" || call[1] === "SIGKILL");
        expect(terminationSignals).toHaveLength(1);

        await new Promise((resolve) => setTimeout(resolve, 5_100));
        expect(kill.mock.calls.filter((call) => call[1] === "SIGTERM" || call[1] === "SIGKILL")).toHaveLength(1);
      } finally {
        kill.mockRestore();
      }
    },
    15_000,
  );

  it.runIf(process.platform !== "win32")("times out descendant processes in the command process group", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-timeout-tree-"));
    roots.push(root);
    const marker = path.join(root, "descendant-survived");
    const dependencies = createNodeBootstrapDependencies(process.platform);
    const parent = [
      "const {spawn}=require('node:child_process');",
      "spawn(process.execPath,['-e',\"setTimeout(()=>require('node:fs').writeFileSync(process.argv[1],'alive'),600)\",process.argv[1]],{stdio:'ignore'});",
      "setInterval(()=>{},1000);",
    ].join("");
    const result = await dependencies.command.run({
      args: ["-e", parent, marker],
      command: process.execPath,
      timeoutMs: 150,
    });
    expect(result.exitCode).toBe(124);
    await new Promise((resolve) => setTimeout(resolve, 700));

    await expect(access(marker)).rejects.toThrow();
  });

  it.runIf(process.platform !== "win32").each([
    ["cancel", 5, 25, 130],
    ["timeout", 25, 5, 124],
  ] as const)("keeps the first %s terminal reason immutable when cancel and timeout race", async (_first, abortMs, timeoutMs, exitCode) => {
    const dependencies = createNodeBootstrapDependencies(process.platform);
    const abort = new AbortController();
    const running = dependencies.command.run({
      args: ["-e", "process.on('SIGTERM',()=>{});setInterval(()=>{},1000)"],
      command: process.execPath,
      signal: abort.signal,
      timeoutMs,
    });
    const timer = setTimeout(() => abort.abort(), abortMs);

    await expect(running).resolves.toMatchObject({ contained: true, exitCode });
    clearTimeout(timer);
  });

  it.runIf(process.platform !== "win32")(
    "fails and contains a zero-exit leader whose ignored-stdio descendant outlives it",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-success-tree-"));
      roots.push(root);
      const marker = path.join(root, "descendant-survived");
      // The descendant waits DESCENDANT_WRITE_MS before writing, and the
      // assertion below is that it never gets there. That delay is fixture
      // headroom for containment latency, not a tolerance on the assertion:
      // the property under test is "the orphan does not survive", and it only
      // tests that if the delay comfortably exceeds how long containment takes.
      //
      // It was 700ms, and containment SIGTERMs the process group and then waits
      // up to 2s for it to settle before escalating. On a loaded Linux runner
      // the descendant therefore won the race and wrote, failing this test on CI
      // while never running locally at all (it is POSIX-only, so a Windows
      // machine skips it). The assertion is unchanged and just as strict - the
      // marker must still never appear - it simply is not decided by scheduler
      // luck any more.
      const parent = [
        "const {spawn}=require('node:child_process');",
        `spawn(process.execPath,['-e',"setTimeout(()=>require('node:fs').writeFileSync(process.argv[1],'alive'),${DESCENDANT_WRITE_MS})",process.argv[1]],{stdio:'ignore'}).unref();`,
      ].join("");

      const result = await createNodeBootstrapDependencies(process.platform).command.run({
        args: ["-e", parent, marker],
        command: process.execPath,
        timeoutMs: 30_000,
      });

      expect(result).toMatchObject({ contained: true, exitCode: 1 });
      expect(result.stderr).toMatch(/descendant|containment/i);
      // Wait past the descendant's write deadline, then require the marker to
      // be absent: had it survived containment, it would have written by now.
      await new Promise((resolve) => setTimeout(resolve, DESCENDANT_WRITE_MS + 500));
      await expect(access(marker)).rejects.toThrow();
    },
    15_000,
  );

  it.runIf(process.platform !== "win32")(
    "fails and contains a zero-exit leader whose delayed descendant escapes into a new session",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-detached-tree-"));
      roots.push(root);
      const marker = path.join(root, "detached-descendant-survived");
      const parent = [
        "const {spawn}=require('node:child_process');",
        "spawn(process.execPath,['-e',\"process.on('SIGTERM',()=>{});setTimeout(()=>require('node:fs').writeFileSync(process.argv[1],'alive'),1500);setInterval(()=>{},1000)\",process.argv[1]],{detached:true,stdio:'ignore'}).unref();",
      ].join("");

      const result = await createNodeBootstrapDependencies(process.platform).command.run({
        args: ["-e", parent, marker],
        command: process.execPath,
        timeoutMs: 30_000,
      });

      expect(result).toMatchObject({ contained: true, exitCode: 1 });
      expect(result.stderr).toMatch(/descendant|containment/i);
      await new Promise((resolve) => setTimeout(resolve, 1_650));
      await expect(access(marker)).rejects.toThrow();
    },
    15_000,
  );

  it.runIf(process.platform !== "win32")(
    "fails closed and cleans the group when trusted POSIX process enumeration is unavailable",
    async () => {
      const result = await createNodeBootstrapDependencies(process.platform, {
        posixProcessEnumerators: ["/definitely-missing/flinttrade-ps"],
      }).command.run({
        args: ["-e", "process.exit(0)"],
        command: process.execPath,
        timeoutMs: 5_000,
      });

      expect(result).toMatchObject({ contained: false, exitCode: 1 });
      expect(result.stderr).toMatch(/enumeration|process-anchor.*did not settle/i);
    },
  );

  it.runIf(process.platform !== "win32")(
    "refuses stale-lease recovery while an escaped token-bound process is still alive",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-tagged-stale-"));
      roots.push(root);
      const target = path.join(root, ".flinttrade-bootstrap-operation.lock");
      const processGroupId = 2_147_483_646;
      const containmentToken = randomBytes(16).toString("hex");
      await mkdir(target);
      await writeFile(
        path.join(target, "owner.json"),
        `${JSON.stringify({ acquiredAt: new Date(0).toISOString(), bootIdentity: "previous-boot", ownerPid: 999_999, operationId: "stale" })}\n`,
      );
      await writeFile(
        path.join(target, `process-group-${processGroupId}.json`),
        `${JSON.stringify({ containmentToken, kind: "posix-group", operationId: "stale", ownerPid: 999_999, processId: processGroupId, protocol: 1 })}\n`,
      );
      const escaped = spawn(process.execPath, ["-e", "process.on('SIGTERM',()=>{});process.stdout.write('ready\\n');setInterval(()=>{},1000)"], {
        detached: true,
        env: { ...process.env, FLINTTRADE_PROCESS_ANCHOR: containmentToken },
        stdio: ["ignore", "pipe", "ignore"],
      });
      await once(escaped.stdout!, "data");
      try {
        const fileSystem = createNodeBootstrapDependencies(process.platform, {
          testHooks: { recordedProcessWaitMs: 75 },
        }).fileSystem;
        await expect(
          fileSystem.acquireOperationLock({
            bootIdentity: "current-boot",
            ownerPid: process.pid,
            singletonAuthorised: true,
            target,
          }),
        ).rejects.toThrow(/tagged POSIX process.*still alive/i);
        expect(await fileSystem.listNames(target)).toEqual([
          "owner.json",
          `process-group-${processGroupId}.json`,
        ]);
      } finally {
        escaped.kill("SIGKILL");
        await once(escaped, "close");
      }
    },
    15_000,
  );

  it.runIf(process.platform !== "win32")(
    "drains a stale token-bound process after its recorded anchor is already absent",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-tagged-recovery-"));
      roots.push(root);
      const target = path.join(root, ".flinttrade-bootstrap-operation.lock");
      const processGroupId = 2_147_483_645;
      const containmentToken = randomBytes(16).toString("hex");
      await mkdir(target);
      await writeFile(
        path.join(target, "owner.json"),
        `${JSON.stringify({ acquiredAt: new Date(0).toISOString(), bootIdentity: "previous-boot", ownerPid: 999_999, operationId: "stale" })}\n`,
      );
      await writeFile(
        path.join(target, `process-group-${processGroupId}.json`),
        `${JSON.stringify({ containmentToken, kind: "posix-group", operationId: "stale", ownerPid: 999_999, processId: processGroupId, protocol: 1 })}\n`,
      );
      const escaped = spawn(
        process.execPath,
        ["-e", "process.on('SIGTERM',()=>{});process.stdout.write('ready\\n');setInterval(()=>{},1000)"],
        {
          detached: true,
          env: { ...process.env, FLINTTRADE_PROCESS_ANCHOR: containmentToken },
          stdio: ["ignore", "pipe", "ignore"],
        },
      );
      const escapedClosed = once(escaped, "close");
      await once(escaped.stdout!, "data");
      try {
        const fileSystem = createNodeBootstrapDependencies(process.platform, {
          testHooks: { ...atomicPromotionTestHooks(), recordedProcessWaitMs: 2_500 },
        }).fileSystem;
        const release = await fileSystem.acquireOperationLock({
          bootIdentity: "current-boot",
          ownerPid: process.pid,
          singletonAuthorised: true,
          target,
        });
        await escapedClosed;
        expect(await fileSystem.listNames(target)).toEqual(["owner.json"]);
        await release();
      } finally {
        if (escaped.exitCode === null && escaped.signalCode === null) escaped.kill("SIGKILL");
        await escapedClosed;
      }
    },
    15_000,
  );

  it.runIf(process.platform !== "win32")(
    "does not signal a live process whose containment token is only a prefix match",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-token-prefix-"));
      roots.push(root);
      const target = path.join(root, ".flinttrade-bootstrap-operation.lock");
      const processGroupId = 2_147_483_642;
      const containmentToken = randomBytes(16).toString("hex");
      await mkdir(target);
      await writeFile(
        path.join(target, "owner.json"),
        `${JSON.stringify({ acquiredAt: new Date(0).toISOString(), bootIdentity: "previous-boot", ownerPid: 999_999, operationId: "stale" })}\n`,
      );
      await writeFile(
        path.join(target, `process-group-${processGroupId}.json`),
        `${JSON.stringify({ containmentToken, kind: "posix-group", operationId: "stale", ownerPid: 999_999, processId: processGroupId, protocol: 1 })}\n`,
      );
      const unrelated = spawn(process.execPath, ["-e", "process.stdout.write('ready\\n');setInterval(()=>{},1000)"], {
        detached: true,
        env: { ...process.env, FLINTTRADE_PROCESS_ANCHOR: `${containmentToken}0` },
        stdio: ["ignore", "pipe", "ignore"],
      });
      const unrelatedClosed = once(unrelated, "close");
      await once(unrelated.stdout!, "data");
      try {
        const fileSystem = createNodeBootstrapDependencies(process.platform, {
          testHooks: atomicPromotionTestHooks(),
        }).fileSystem;
        const release = await fileSystem.acquireOperationLock({
          bootIdentity: "current-boot",
          ownerPid: process.pid,
          singletonAuthorised: true,
          target,
        });
        expect(unrelated.exitCode).toBeNull();
        process.kill(unrelated.pid!, 0);
        await release();
      } finally {
        if (unrelated.exitCode === null && unrelated.signalCode === null) unrelated.kill("SIGKILL");
        await unrelatedClosed;
      }
    },
    15_000,
  );

  it("fails closed on a stale Windows supervisor PID that has been reused by a live process", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-supervisor-reuse-"));
    roots.push(root);
    const target = path.join(root, ".flinttrade-bootstrap-operation.lock");
    await mkdir(target);
    await writeFile(
      path.join(target, "owner.json"),
      `${JSON.stringify({ acquiredAt: new Date(0).toISOString(), bootIdentity: "previous-boot", ownerPid: 999_999, operationId: "stale" })}\n`,
    );
    await writeFile(
      path.join(target, `windows-supervisor-${process.pid}.json`),
      `${JSON.stringify({ kind: "windows-supervisor", operationId: "stale", ownerPid: 999_999, processId: process.pid, protocol: 1 })}\n`,
    );
    const fileSystem = createNodeBootstrapDependencies(process.platform, {
      testHooks: { recordedProcessWaitMs: 75 },
    }).fileSystem;

    await expect(
      fileSystem.acquireOperationLock({
        bootIdentity: "current-boot",
        ownerPid: process.pid,
        singletonAuthorised: true,
        target,
      }),
    ).rejects.toThrow(/Windows supervisor.*still alive/i);
    expect(await fileSystem.listNames(target)).toEqual([
      "owner.json",
      `windows-supervisor-${process.pid}.json`,
    ]);
  });

  it("rejects a corrupt final process record but recovers a strict pre-START publication record", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-process-publication-"));
    roots.push(root);
    const corrupt = path.join(root, ".corrupt-operation.lock");
    const partial = path.join(root, ".partial-operation.lock");
    const owner = `${JSON.stringify({ acquiredAt: new Date(0).toISOString(), bootIdentity: "previous-boot", ownerPid: 999_999, operationId: "stale" })}\n`;
    await mkdir(corrupt);
    await writeFile(path.join(corrupt, "owner.json"), owner);
    await writeFile(path.join(corrupt, "process-group-2147483644.json"), "{}\n");
    const fileSystem = createNodeBootstrapDependencies(process.platform, {
      testHooks: atomicPromotionTestHooks(),
    }).fileSystem;
    await expect(
      fileSystem.acquireOperationLock({
        bootIdentity: "current-boot",
        ownerPid: process.pid,
        singletonAuthorised: true,
        target: corrupt,
      }),
    ).rejects.toThrow(/process-group record is invalid/i);

    const mismatched = path.join(root, ".mismatched-operation.lock");
    await mkdir(mismatched);
    await writeFile(path.join(mismatched, "owner.json"), owner);
    await writeFile(
      path.join(mismatched, "process-group-2147483642.json"),
      `${JSON.stringify({ containmentToken: "a".repeat(32), kind: "posix-group", operationId: "different", ownerPid: 999_999, processId: 2_147_483_642, protocol: 1 })}\n`,
    );
    await expect(
      fileSystem.acquireOperationLock({
        bootIdentity: "current-boot",
        ownerPid: process.pid,
        singletonAuthorised: true,
        target: mismatched,
      }),
    ).rejects.toThrow(/final process record.*bound.*owner/i);
    expect(await fileSystem.listNames(mismatched)).toEqual(["owner.json", "process-group-2147483642.json"]);

    await mkdir(partial);
    await writeFile(path.join(partial, "owner.json"), owner);
    await writeFile(
      path.join(
        partial,
        ".process-group-2147483643.publishing-123e4567-e89b-42d3-a456-426614174000.json",
      ),
      "{\n",
    );
    const release = await fileSystem.acquireOperationLock({
      bootIdentity: "current-boot",
      ownerPid: process.pid,
      singletonAuthorised: true,
      target: partial,
    });
    expect(await fileSystem.listNames(partial)).toEqual(["owner.json"]);
    await release();
  });

  it("recovers only a singleton-authorised stale operation lease and rejects no-follow aliases", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-lease-"));
    roots.push(root);
    const target = path.join(root, ".flinttrade-bootstrap-operation.lock");
    await mkdir(target);
    await writeFile(
      path.join(target, "owner.json"),
      `${JSON.stringify({ acquiredAt: new Date(0).toISOString(), bootIdentity: "previous-boot", ownerPid: 999_999, operationId: "stale" })}\n`,
    );
    const fileSystem = createNodeBootstrapDependencies(process.platform, {
      testHooks: atomicPromotionTestHooks(),
    }).fileSystem;
    const acquire = fileSystem.acquireOperationLock as unknown as (input: {
      bootIdentity: string;
      ownerPid: number;
      singletonAuthorised: boolean;
      target: string;
    }) => Promise<() => Promise<void>>;

    await expect(
      acquire({ bootIdentity: "current-boot", ownerPid: process.pid, singletonAuthorised: false, target }),
    ).rejects.toThrow(/singleton|exclusive|another/i);
    const release = await acquire({
      bootIdentity: "current-boot",
      ownerPid: process.pid,
      singletonAuthorised: true,
      target,
    });
    expect(JSON.parse(await readFile(path.join(target, "owner.json"), "utf8"))).toMatchObject({
      bootIdentity: "current-boot",
      ownerPid: process.pid,
    });
    await expect(
      acquire({ bootIdentity: "current-boot", ownerPid: process.pid, singletonAuthorised: true, target }),
    ).rejects.toThrow(/re-entr|already|same process/i);
    await release();

    const aliased = path.join(root, "aliased-operation.lock");
    await symlink(root, aliased);
    await expect(
      acquire({ bootIdentity: "current-boot", ownerPid: process.pid, singletonAuthorised: true, target: aliased }),
    ).rejects.toThrow(/symbolic|no-follow|directory/i);
  });

  it.each([
    ["POSIX", "linux"],
    ["simulated Windows", "win32"],
  ] as const)(
    "preserves a stale lease and foreign late quarantine at the %s native no-replace boundary",
    async (_label, platform) => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-lease-final-race-"));
      roots.push(root);
      const target = path.join(root, ".flinttrade-bootstrap-operation.lock");
      const owner = `${JSON.stringify({
        acquiredAt: new Date(0).toISOString(),
        bootIdentity: "previous-boot",
        operationId: "stale",
        ownerPid: 999_999,
      })}\n`;
      await mkdir(target);
      await writeFile(path.join(target, "owner.json"), owner);
      const canonicalTarget = await realpath(target);
      let quarantine = "";
      let foreignIdentity: { dev: number; ino: number } | null = null;
      const inspectNative = vi.fn(async () => TEST_WINDOWS_NATIVE_IDENTITY);
      const preLeaseScope = vi.fn();
      const promoteNative = vi.fn(async (
        source: string,
        destination: string,
        expected: { dev: number; ino: number; nativeIdentity?: string },
      ) => {
        if (platform === "win32") expect(expected.nativeIdentity).toBe(TEST_WINDOWS_NATIVE_IDENTITY);
        await testAtomicPromote(source, destination, expected);
      });
      const dependencies = createNodeBootstrapDependencies(platform, {
        operationLeaseTarget: target,
        testHooks: {
          async beforeAtomicPromotion(source, destination) {
            expect(source).toBe(canonicalTarget);
            if (platform === "win32") expect(inspectNative).toHaveBeenCalledTimes(2);
            quarantine = destination;
            await mkdir(destination);
            const metadata = await lstat(destination);
            foreignIdentity = { dev: metadata.dev, ino: metadata.ino };
          },
          onPreLeaseCommandScope: preLeaseScope,
          testAtomicPromote: promoteNative,
          testNativeDirectoryIdentity: inspectNative,
        },
      });
      const acquire = dependencies.fileSystem.acquireOperationLock;
      expect(dependencies.command.operationLeaseTarget).toBe(target);
      expect(preLeaseScope).toHaveBeenCalledTimes(platform === "win32" ? 1 : 0);
      if (platform === "win32") expect(preLeaseScope).toHaveBeenCalledWith(undefined);

      await expect(acquire({
        bootIdentity: "current-boot",
        ownerPid: process.pid,
        singletonAuthorised: true,
        target,
      })).rejects.toMatchObject({ code: "EEXIST" });
      expect(quarantine).toMatch(/\.stale-[0-9a-f-]{36}$/);
      expect(await readFile(path.join(target, "owner.json"), "utf8")).toBe(owner);
      await expect(lstat(quarantine)).resolves.toMatchObject(foreignIdentity!);
      expect(promoteNative).toHaveBeenCalledTimes(1);
      expect(inspectNative).toHaveBeenCalledTimes(platform === "win32" ? 2 : 0);
    },
  );

  it("captures the Windows native lease identity before rejecting stale lease content", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-lease-native-order-"));
    roots.push(root);
    const target = path.join(root, ".flinttrade-bootstrap-operation.lock");
    await mkdir(target);
    const owner = `${JSON.stringify({
      acquiredAt: new Date(0).toISOString(),
      bootIdentity: "previous-boot",
      operationId: "stale",
      ownerPid: 999_999,
    })}\n`;
    await writeFile(path.join(target, "owner.json"), owner);
    const inspectNative = vi.fn(async (nativeTarget: string) => {
      await writeFile(path.join(nativeTarget, "unexpected"), "foreign evidence");
      return TEST_WINDOWS_NATIVE_IDENTITY;
    });
    const promoteNative = vi.fn(testAtomicPromote);
    const acquire = createNodeBootstrapDependencies("win32", {
      operationLeaseTarget: target,
      testHooks: {
        testAtomicPromote: promoteNative,
        testNativeDirectoryIdentity: inspectNative,
      },
    }).fileSystem.acquireOperationLock;

    await expect(acquire({
      bootIdentity: "current-boot",
      ownerPid: process.pid,
      singletonAuthorised: true,
      target,
    })).rejects.toThrow(/unexpected entries/i);
    expect(inspectNative).toHaveBeenCalledTimes(1);
    expect(promoteNative).not.toHaveBeenCalled();
    await expect(readFile(path.join(target, "owner.json"), "utf8")).resolves.toBe(owner);
    await expect(readFile(path.join(target, "unexpected"), "utf8")).resolves.toBe("foreign evidence");
  });

  it("refuses Windows stale-lease recovery when the native identity changes after validation", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-lease-native-drift-"));
    roots.push(root);
    const target = path.join(root, ".flinttrade-bootstrap-operation.lock");
    const owner = `${JSON.stringify({
      acquiredAt: new Date(0).toISOString(),
      bootIdentity: "previous-boot",
      operationId: "stale",
      ownerPid: 999_999,
    })}\n`;
    await mkdir(target);
    await writeFile(path.join(target, "owner.json"), owner);
    const inspectNative = vi.fn()
      .mockResolvedValueOnce(TEST_WINDOWS_NATIVE_IDENTITY)
      .mockResolvedValueOnce(TEST_WINDOWS_NATIVE_IDENTITY_DRIFT);
    const promoteNative = vi.fn(testAtomicPromote);
    const acquire = createNodeBootstrapDependencies("win32", {
      operationLeaseTarget: target,
      testHooks: {
        testAtomicPromote: promoteNative,
        testNativeDirectoryIdentity: inspectNative,
      },
    }).fileSystem.acquireOperationLock;

    await expect(acquire({
      bootIdentity: "current-boot",
      ownerPid: process.pid,
      singletonAuthorised: true,
      target,
    })).rejects.toThrow(/changed during containment reconciliation/i);
    expect(inspectNative).toHaveBeenCalledTimes(2);
    expect(promoteNative).not.toHaveBeenCalled();
    await expect(readFile(path.join(target, "owner.json"), "utf8")).resolves.toBe(owner);
  });

  it("preserves a process record inserted during the Windows stale-lease move and refuses a new lease", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-lease-post-move-scope-"));
    roots.push(root);
    const target = path.join(root, ".flinttrade-bootstrap-operation.lock");
    const owner = `${JSON.stringify({
      acquiredAt: new Date(0).toISOString(),
      bootIdentity: "previous-boot",
      operationId: "stale",
      ownerPid: 999_999,
    })}\n`;
    await mkdir(target);
    await writeFile(path.join(target, "owner.json"), owner);
    const processId = 2_147_483_644;
    const recordName = `process-group-${processId}.json`;
    const record = `${JSON.stringify({
      containmentToken: "a".repeat(32),
      kind: "posix-group",
      operationId: "stale",
      ownerPid: 999_999,
      processId,
      protocol: 1,
    })}\n`;
    let quarantine = "";
    const acquire = createNodeBootstrapDependencies("win32", {
      operationLeaseTarget: target,
      testHooks: {
        async beforeAtomicPromotion(source, destination) {
          quarantine = destination;
          await writeFile(path.join(source, recordName), record);
        },
        ...atomicPromotionTestHooks(),
      },
    }).fileSystem.acquireOperationLock;

    await expect(acquire({
      bootIdentity: "current-boot",
      ownerPid: process.pid,
      singletonAuthorised: true,
      target,
    })).rejects.toThrow(/identity changed during quarantine/i);
    expect(quarantine).toMatch(/\.stale-[0-9a-f-]{36}$/);
    await expect(lstat(target)).rejects.toMatchObject({ code: "ENOENT" });
    await expect(readFile(path.join(quarantine, "owner.json"), "utf8")).resolves.toBe(owner);
    await expect(readFile(path.join(quarantine, recordName), "utf8")).resolves.toBe(record);
  });

  it("preserves and revalidates a Windows stale-lease quarantine across later acquisitions", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-lease-windows-preserve-"));
    roots.push(root);
    const target = path.join(root, ".flinttrade-bootstrap-operation.lock");
    const owner = `${JSON.stringify({
      acquiredAt: new Date(0).toISOString(),
      bootIdentity: "previous-boot",
      operationId: "stale",
      ownerPid: 999_999,
    })}\n`;
    await mkdir(target);
    await writeFile(path.join(target, "owner.json"), owner);
    let quarantine = "";
    const dependencies = createNodeBootstrapDependencies("win32", {
      operationLeaseTarget: target,
      testHooks: {
        beforeAtomicPromotion(_source, destination) {
          quarantine = destination;
        },
        ...atomicPromotionTestHooks(),
      },
    });
    const request = {
      bootIdentity: "current-boot",
      ownerPid: process.pid,
      singletonAuthorised: true,
      target,
    };

    const firstRelease = await dependencies.fileSystem.acquireOperationLock(request);
    expect(quarantine).toMatch(/\.stale-[0-9a-f-]{36}$/);
    await expect(readFile(path.join(quarantine, "owner.json"), "utf8")).resolves.toBe(owner);
    await firstRelease();
    const secondRelease = await dependencies.fileSystem.acquireOperationLock(request);
    await expect(readFile(path.join(quarantine, "owner.json"), "utf8")).resolves.toBe(owner);
    await secondRelease();
    await expect(readFile(path.join(quarantine, "owner.json"), "utf8")).resolves.toBe(owner);
  });

  it("fails closed when 64 preserved Windows lease quarantines require manual archival", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-lease-windows-cap-"));
    roots.push(root);
    const target = path.join(root, ".flinttrade-bootstrap-operation.lock");
    const owner = `${JSON.stringify({
      acquiredAt: new Date(0).toISOString(),
      bootIdentity: "previous-boot",
      operationId: "stale",
      ownerPid: 999_999,
    })}\n`;
    const quarantines: string[] = [];
    for (let index = 0; index < 64; index += 1) {
      const quarantine = `${target}.stale-00000000-0000-4000-8000-${String(index).padStart(12, "0")}`;
      quarantines.push(quarantine);
      await mkdir(quarantine);
      await writeFile(path.join(quarantine, "owner.json"), owner);
    }
    const acquire = createNodeBootstrapDependencies("win32", {
      operationLeaseTarget: target,
      testHooks: {
        testAtomicPromote,
        async testNativeDirectoryIdentity(nativeTarget) {
          const digest = createHash("sha256").update(nativeTarget).digest("hex");
          return `${digest.slice(0, 16)}:${digest.slice(16, 48)}`;
        },
      },
    }).fileSystem.acquireOperationLock;

    await expect(acquire({
      bootIdentity: "current-boot",
      ownerPid: process.pid,
      singletonAuthorised: true,
      target,
    })).rejects.toThrow(/reached 64.*archive.*manually remove/i);
    await expect(lstat(target)).rejects.toMatchObject({ code: "ENOENT" });
    for (const quarantine of quarantines) {
      await expect(readFile(path.join(quarantine, "owner.json"), "utf8")).resolves.toBe(owner);
    }
  });

  it("reconciles a validated crash-left lease quarantine before creating the next lease", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-lease-quarantine-"));
    roots.push(root);
    const target = path.join(root, ".flinttrade-bootstrap-operation.lock");
    const quarantine = `${target}.stale-123e4567-e89b-42d3-a456-426614174000`;
    await mkdir(quarantine);
    await writeFile(
      path.join(quarantine, "owner.json"),
      `${JSON.stringify({ acquiredAt: new Date(0).toISOString(), bootIdentity: "previous-boot", ownerPid: 999_999, operationId: "stale" })}\n`,
    );
    const acquire = createNodeBootstrapDependencies(process.platform, {
      testHooks: atomicPromotionTestHooks(),
    }).fileSystem.acquireOperationLock;

    const release = await acquire({
      bootIdentity: "current-boot",
      ownerPid: process.pid,
      singletonAuthorised: true,
      target,
    });
    if (process.platform === "win32") await expect(access(quarantine)).resolves.toBeUndefined();
    else await expect(access(quarantine)).rejects.toThrow();
    await expect(access(path.join(target, "owner.json"))).resolves.toBeUndefined();
    await release();
  });

  it.each([
    ["empty lease directory", null],
    ["empty owner record", ""],
    ["truncated owner record", '{"operationId":'],
    ["invalid owner shape", '{"operationId":"partial"}'],
  ])("recovers a singleton-authorised %s from partial publication", async (_label, content) => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-partial-lease-"));
    roots.push(root);
    const target = path.join(root, ".flinttrade-bootstrap-operation.lock");
    await mkdir(target);
    if (content !== null) await writeFile(path.join(target, "owner.json"), content);
    const acquire = createNodeBootstrapDependencies(process.platform, {
      testHooks: atomicPromotionTestHooks(),
    }).fileSystem.acquireOperationLock;

    const release = await acquire({
      bootIdentity: "current-boot",
      ownerPid: process.pid,
      singletonAuthorised: true,
      target,
    });

    expect(JSON.parse(await readFile(path.join(target, "owner.json"), "utf8"))).toMatchObject({
      bootIdentity: "current-boot",
      ownerPid: process.pid,
    });
    await release();
  });

  it("publishes a complete durable lease owner across simulated short writes", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-lease-short-write-"));
    roots.push(root);
    const target = path.join(root, ".flinttrade-bootstrap-operation.lock");
    const progress: number[] = [];
    const acquire = createNodeBootstrapDependencies(process.platform, {
      testHooks: {
        leaseOwnerWriteChunkBytes: 1,
        onLeaseOwnerPublication(stage, bytesWritten) {
          if (stage === "after-write") progress.push(bytesWritten);
        },
      },
    }).fileSystem.acquireOperationLock;

    const release = await acquire({
      bootIdentity: "current-boot",
      ownerPid: process.pid,
      singletonAuthorised: true,
      target,
    });

    expect(progress.length).toBeGreaterThan(1);
    expect(JSON.parse(await readFile(path.join(target, "owner.json"), "utf8"))).toMatchObject({
      bootIdentity: "current-boot",
    });
    await release();
  });

  it("reserves an in-process lease before asynchronous owner publication", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-concurrent-lease-"));
    roots.push(root);
    const target = path.join(root, ".flinttrade-bootstrap-operation.lock");
    let enteredPublication!: () => void;
    const publicationEntered = new Promise<void>((resolve) => {
      enteredPublication = resolve;
    });
    let continuePublication!: () => void;
    const publicationAllowed = new Promise<void>((resolve) => {
      continuePublication = resolve;
    });
    let paused = false;
    const acquire = createNodeBootstrapDependencies(process.platform, {
      testHooks: {
        async onLeaseOwnerPublication(stage) {
          if (stage === "before-open" && !paused) {
            paused = true;
            enteredPublication();
            await publicationAllowed;
          }
        },
      },
    }).fileSystem.acquireOperationLock;
    const request = {
      bootIdentity: "current-boot",
      ownerPid: process.pid,
      singletonAuthorised: true,
      target,
    };

    const first = acquire(request);
    await publicationEntered;
    await expect(acquire(request)).rejects.toThrow(/re-entr|already|same process/i);
    continuePublication();
    const release = await first;
    await release();
  });

  it("refuses a replacement lease directory after owner unlink on release retry", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-lease-release-swap-"));
    roots.push(root);
    const target = path.join(root, ".flinttrade-bootstrap-operation.lock");
    const moved = path.join(root, "moved-owned-lease");
    let swapped = false;
    const acquire = createNodeBootstrapDependencies(process.platform, {
      testHooks: {
        beforeLeaseReleaseStage(stage) {
          if (stage === "directory-sync" && !swapped) {
            swapped = true;
            renameSync(target, moved);
            mkdirSync(target, { mode: 0o700 });
          }
        },
      },
    }).fileSystem.acquireOperationLock;
    const release = await acquire({
      bootIdentity: "current-boot",
      ownerPid: process.pid,
      singletonAuthorised: true,
      target,
    });

    await expect(release()).rejects.toThrow(/identity changed/i);
    await expect(release()).rejects.toThrow(/identity changed/i);
    await expect(access(target)).resolves.toBeUndefined();
    await expect(access(moved)).resolves.toBeUndefined();
  });

  it.each(["unexpected", "symlink", "directory"] as const)(
    "refuses an ambiguous %s lease shape during singleton recovery",
    async (kind) => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-ambiguous-lease-"));
      roots.push(root);
      const target = path.join(root, ".flinttrade-bootstrap-operation.lock");
      await mkdir(target);
      if (kind === "unexpected") await writeFile(path.join(target, "extra"), "ambiguous");
      if (kind === "symlink") await symlink(root, path.join(target, "owner.json"));
      if (kind === "directory") await mkdir(path.join(target, "owner.json"));
      const acquire = createNodeBootstrapDependencies(process.platform).fileSystem.acquireOperationLock;

      await expect(
        acquire({
          bootIdentity: "current-boot",
          ownerPid: process.pid,
          singletonAuthorised: true,
          target,
        }),
      ).rejects.toThrow(/unexpected entries|no-follow regular file/i);
    },
  );

  it("retries the same lease release after a transient validation failure", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-lease-release-"));
    roots.push(root);
    const target = path.join(root, ".flinttrade-bootstrap-operation.lock");
    const acquire = createNodeBootstrapDependencies(process.platform).fileSystem.acquireOperationLock;
    const release = await acquire({
      bootIdentity: "current-boot",
      ownerPid: process.pid,
      singletonAuthorised: true,
      target,
    });
    const interruption = path.join(target, "interruption");
    await writeFile(interruption, "failpoint");

    await expect(release()).rejects.toThrow(/unexpected entries/i);
    await rm(interruption);
    await expect(release()).resolves.toBeUndefined();
    await expect(access(target)).rejects.toThrow();
  });

  it("writes and replaces files atomically with owner-only parents", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-io-"));
    roots.push(root);
    const dependencies = createNodeBootstrapDependencies(process.platform);
    const target = path.join(root, "nested", "marker.json");

    await dependencies.fileSystem.writeTextAtomic(target, "first");
    await dependencies.fileSystem.writeTextAtomic(target, "second");

    expect(await readFile(target, "utf8")).toBe("second");
    await expect(access(`${target}.tmp`)).rejects.toThrow();
    await expect(syncDirectoryForDurability(path.dirname(target))).resolves.toBeUndefined();
  });

  it("writes an exclusive marker once and preserves an existing file", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-exclusive-marker-"));
    roots.push(root);
    const target = path.join(root, "marker.json");
    const dependencies = createNodeBootstrapDependencies(process.platform);

    await dependencies.fileSystem.writeTextAbsent(target, "first");
    await expect(dependencies.fileSystem.writeTextAbsent(target, "second")).rejects.toMatchObject({ code: "EEXIST" });
    expect(await readFile(target, "utf8")).toBe("first");
  });

  it("does not follow predictable temporary, destination or durable-log symlinks", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-write-alias-"));
    roots.push(root);
    const dependencies = createNodeBootstrapDependencies(process.platform);
    const directory = path.join(root, "nested");
    const outside = path.join(root, "outside");
    const target = path.join(directory, "marker.json");
    const log = path.join(directory, "bootstrap.jsonl");
    await mkdir(directory);
    await writeFile(outside, "outside");
    await symlink(outside, `${target}.tmp`);
    await symlink(outside, target);

    await dependencies.fileSystem.writeTextAtomic(target, "managed");
    expect(await readFile(target, "utf8")).toBe("managed");
    expect(await readFile(outside, "utf8")).toBe("outside");
    expect(await readFile(`${target}.tmp`, "utf8")).toBe("outside");

    await symlink(outside, log);
    await expect(dependencies.fileSystem.appendText(log, "event\n")).rejects.toThrow(/no-follow|regular file/i);
    expect(await readFile(outside, "utf8")).toBe("outside");
  });

  it("rejects a durable-log identity swap between no-follow validation and handle open", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-log-race-"));
    roots.push(root);
    const log = path.join(root, "bootstrap.jsonl");
    const original = path.join(root, "bootstrap.original");
    const outside = path.join(root, "outside");
    await writeFile(log, "old\n");
    await writeFile(outside, "outside");
    const dependencies = createNodeBootstrapDependencies(process.platform, {
      testHooks: {
        beforeAppendOpen(target) {
          renameSync(target, original);
          symlinkSync(outside, target);
        },
      },
    });

    await expect(dependencies.fileSystem.appendText(log, "new\n")).rejects.toThrow();
    expect(await readFile(outside, "utf8")).toBe("outside");
    expect(await readFile(original, "utf8")).toBe("old\n");
  });

  it("rejects a durable-log parent swap before opening without touching the outside directory", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-log-parent-race-"));
    roots.push(root);
    const parent = path.join(root, "logs");
    const originalParent = path.join(root, "logs.original");
    const outside = path.join(root, "outside");
    const log = path.join(parent, "bootstrap.jsonl");
    await mkdir(parent);
    await mkdir(outside);
    const dependencies = createNodeBootstrapDependencies(process.platform, {
      testHooks: {
        beforeAppendOpen() {
          renameSync(parent, originalParent);
          symlinkSync(outside, parent, "dir");
        },
      },
    });

    await expect(dependencies.fileSystem.appendText(log, "event\n")).rejects.toThrow(/parent identity/i);
    await expect(access(path.join(outside, "bootstrap.jsonl"))).rejects.toThrow();
  });

  it("completes a durable-log append across simulated short writes", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-log-short-write-"));
    roots.push(root);
    const log = path.join(root, "bootstrap.jsonl");
    const dependencies = createNodeBootstrapDependencies(process.platform, {
      testHooks: { appendWriteChunkBytes: 2 },
    });
    const event = '{"message":"ready £"}\n';

    await dependencies.fileSystem.appendText(log, event);
    await dependencies.fileSystem.appendText(log, event);

    expect(await readFile(log, "utf8")).toBe(`${event}${event}`);
  });

  it("propagates a first-create durable-log parent-sync failure", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-log-parent-sync-"));
    roots.push(root);
    const log = path.join(root, "bootstrap.jsonl");
    const beforeParentSync = vi.fn(() => {
      throw new Error("parent directory sync failed");
    });
    const dependencies = createNodeBootstrapDependencies(process.platform, {
      testHooks: { beforeAppendParentSync: beforeParentSync },
    });

    await expect(dependencies.fileSystem.appendText(log, "event\n")).rejects.toThrow("parent directory sync failed");
    expect(await readFile(log, "utf8")).toBe("event\n");
    expect(beforeParentSync).toHaveBeenCalledOnce();
  });

  it("rejects a durable append when the canonical log name is replaced after file sync", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-log-post-sync-race-"));
    roots.push(root);
    const log = path.join(root, "bootstrap.jsonl");
    const displaced = path.join(root, "bootstrap.displaced.jsonl");
    await writeFile(log, "old\n");
    const dependencies = createNodeBootstrapDependencies(process.platform, {
      testHooks: {
        beforeAppendParentSync(target) {
          renameSync(target, displaced);
          writeFileSync(target, "replacement\n", { flag: "wx", mode: 0o600 });
        },
      },
    });

    await expect(dependencies.fileSystem.appendText(log, "terminal\n")).rejects.toThrow(/pathname changed/i);
    expect(await readFile(log, "utf8")).toBe("replacement\n");
    expect(await readFile(displaced, "utf8")).toBe("old\nterminal\n");
  });

  it("creates and syncs an absent durable-log directory chain in dependency order", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-log-directory-chain-"));
    roots.push(root);
    const workspace = path.join(root, "workspace");
    const logs = path.join(workspace, "logs");
    const syncs: Array<[string, "directory" | "parent"]> = [];
    const dependencies = createNodeBootstrapDependencies(process.platform, {
      testHooks: {
        beforeDurableDirectorySync(target, kind) {
          syncs.push([target, kind]);
        },
      },
    });

    await dependencies.fileSystem.ensureDurableDirectory(logs, root);

    expect(syncs).toEqual([
      [workspace, "directory"],
      [root, "parent"],
      [logs, "directory"],
      [workspace, "parent"],
      [root, "directory"],
      [path.dirname(root), "parent"],
      [workspace, "directory"],
      [root, "parent"],
      [logs, "directory"],
      [workspace, "parent"],
    ]);
  });

  it("syncs a pre-existing workspace/logs chain from a fresh dependency instance", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-log-fresh-chain-"));
    roots.push(root);
    const workspace = path.join(root, "workspace");
    const logs = path.join(workspace, "logs");
    await mkdir(logs, { recursive: true });
    const syncs: Array<[string, "directory" | "parent"]> = [];
    const dependencies = createNodeBootstrapDependencies(process.platform, {
      testHooks: {
        beforeDurableDirectorySync(target, kind) {
          syncs.push([target, kind]);
        },
      },
    });

    await dependencies.fileSystem.ensureDurableDirectory(logs, root);

    expect(syncs).toEqual([
      [root, "directory"],
      [path.dirname(root), "parent"],
      [workspace, "directory"],
      [root, "parent"],
      [logs, "directory"],
      [workspace, "parent"],
    ]);
  });

  it("propagates a durable-log directory-chain sync failure", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-log-directory-failure-"));
    roots.push(root);
    const logs = path.join(root, "workspace", "logs");
    let failed = false;
    const dependencies = createNodeBootstrapDependencies(process.platform, {
      testHooks: {
        beforeDurableDirectorySync(target, kind) {
          if (!failed && kind === "parent" && target === root) {
            failed = true;
            throw new Error("workspace parent sync failed");
          }
        },
      },
    });

    await expect(dependencies.fileSystem.ensureDurableDirectory(logs, root)).rejects.toThrow(
      "workspace parent sync failed",
    );
    await expect(dependencies.fileSystem.ensureDurableDirectory(logs, root)).resolves.toBeUndefined();
  });

  it("allows only real confined directories as generated source-tree roots", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-generated-root-"));
    roots.push(root);
    const dependencies = createNodeBootstrapDependencies(process.platform);
    await writeFile(path.join(root, "source.txt"), "source");
    const identity = await dependencies.fileSystem.snapshotSourceTree(root);
    const generated = path.join(root, "node_modules");
    await mkdir(generated);
    await writeFile(path.join(generated, "generated.txt"), "generated");
    await expect(dependencies.fileSystem.verifySourceTree(root, identity, ["node_modules"])).resolves.toBe(true);

    await rm(generated, { recursive: true });
    const outside = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-generated-outside-"));
    roots.push(outside);
    await symlink(outside, generated);
    await expect(dependencies.fileSystem.verifySourceTree(root, identity, ["node_modules"])).resolves.toBe(false);
  });

  it("rejects traversal and mixed-root archives before extraction", () => {
    expect(() => validateArchiveEntries(["safe/file", "../escape"], "archive")).toThrow("unsafe path");
    expect(() => validateArchiveEntries(["root/file", "other/file"], "archive", "root")).toThrow("unexpected root");
    expect(validateArchiveEntries(["root/file", "root/sub/next"], "archive", "root")).toEqual([
      "root/file",
      "root/sub/next",
    ]);
    expect(validateArchiveEntries(["root/", "root/file"], "archive", "root")).toEqual(["root", "root/file"]);
  });

  it.runIf(process.platform !== "win32")(
    "completes a stable ZIP snapshot across simulated short writes",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-snapshot-short-write-"));
      roots.push(root);
      const archive = path.join(root, "short-write.zip");
      const destination = path.join(root, "extract");
      execFileSync("python3", [
        "-c",
        "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1],'w'); z.writestr('root/file.txt','complete'); z.close()",
        archive,
      ]);
      const dependencies = createNodeBootstrapDependencies(process.platform, {
        testHooks: { archiveSnapshotWriteChunkBytes: 3 },
      });

      await expect(
        dependencies.extractArchive({
          archive,
          destination,
          expectedSha256: await sha256File(archive),
          expectedRoot: "root",
          kind: "zip",
          signal: new AbortController().signal,
        }),
      ).resolves.toEqual(["root/file.txt"]);
      expect(await readFile(path.join(destination, "root", "file.txt"), "utf8")).toBe("complete");
    },
  );

  it.runIf(process.platform !== "win32")(
    "closes the source descriptor across every pre-snapshot setup failure",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-snapshot-setup-failure-"));
      roots.push(root);
      const archive = path.join(root, "source.zip");
      await writeFile(archive, "source archive bytes");
      const baseline = (await readdir("/dev/fd")).length;
      const stages = ["directory-create", "directory-inspect", "destination-open"] as const;

      for (const stage of stages) {
        for (let attempt = 0; attempt < 8; attempt += 1) {
          const dependencies = createNodeBootstrapDependencies(process.platform, {
            testHooks: {
              beforeArchiveSnapshotSetup(current) {
                if (current === stage) throw new Error(`injected ${stage} failure`);
              },
            },
          });
          await expect(
            dependencies.extractArchive({
              archive,
              destination: path.join(root, `extract-${stage}-${attempt}`),
              expectedSha256: await sha256File(archive),
              kind: "zip",
              signal: new AbortController().signal,
            }),
          ).rejects.toThrow(`injected ${stage} failure`);
        }
      }

      expect((await readdir("/dev/fd")).length).toBe(baseline);
    },
  );

  it.runIf(process.platform !== "win32")(
    "preserves its private stable snapshot after successful extraction settlement",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-snapshot-preserved-"));
      roots.push(root);
      const archive = path.join(root, "source.zip");
      const destination = path.join(root, "extract");
      let retainedSnapshot = "";
      execFileSync("python3", [
        "-c",
        "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1],'w'); z.writestr('root/file.txt','complete'); z.close()",
        archive,
      ]);
      const dependencies = createNodeBootstrapDependencies(process.platform, {
        testHooks: {
          onArchiveSnapshotRemove(target) {
            retainedSnapshot = target;
          },
        },
      });

      await expect(
        dependencies.extractArchive({
          archive,
          destination,
          expectedSha256: await sha256File(archive),
          expectedRoot: "root",
          kind: "zip",
          signal: new AbortController().signal,
        }),
      ).resolves.toEqual(["root/file.txt"]);
      expect(await readFile(retainedSnapshot)).toEqual(await readFile(archive));
    },
  );

  it.runIf(process.platform !== "win32")(
    "extracts a validated ZIP root directly into an exclusively reserved candidate",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-strip-root-"));
      roots.push(root);
      const archive = path.join(root, "source.zip");
      execFileSync("python3", [
        "-c",
        "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1],'w'); z.writestr('root/',''); z.writestr('root/file.txt','complete'); z.close()",
        archive,
      ]);
      const dependencies = createNodeBootstrapDependencies(process.platform);
      const destination = await dependencies.fileSystem.reserveTemporaryDirectory(root, "FlintTrade.candidate-1");

      await expect(
        dependencies.extractArchive({
          archive,
          destination: destination.path,
          destinationIdentity: destination.identity,
          expectedSha256: await sha256File(archive),
          expectedRoot: "root",
          kind: "zip",
          signal: new AbortController().signal,
          stripExpectedRoot: true,
        }),
      ).resolves.toEqual(["root", "root/file.txt"]);
      expect(await readFile(path.join(destination.path, "file.txt"), "utf8")).toBe("complete");
      await expect(access(path.join(destination.path, "root"))).rejects.toThrow();
      await expect(
        dependencies.fileSystem.assertDirectoryIdentity(destination.path, destination.identity),
      ).resolves.toBeUndefined();
    },
  );

  it.runIf(process.platform !== "win32")(
    "rejects a truncated but parseable stable ZIP snapshot before parsing",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-snapshot-truncated-"));
      roots.push(root);
      const archive = path.join(root, "truncated.zip");
      const destination = path.join(root, "extract");
      execFileSync("python3", [
        "-c",
        "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1],'w'); z.writestr('root/file.txt','complete'); z.close()",
        archive,
      ]);
      const parseableSize = (await stat(archive)).size;
      await appendFile(archive, "trailing bytes omitted from copied snapshot");
      const dependencies = createNodeBootstrapDependencies(process.platform, {
        testHooks: {
          beforeArchiveSnapshotVerify(target) {
            truncateSync(target, parseableSize);
          },
        },
      });

      await expect(
        dependencies.extractArchive({
          archive,
          destination,
          expectedSha256: await sha256File(archive),
          expectedRoot: "root",
          kind: "zip",
          signal: new AbortController().signal,
        }),
      ).rejects.toThrow(/snapshot.*size|snapshot.*checksum/i);
      await expect(access(destination)).rejects.toThrow();
    },
  );

  it.runIf(process.platform !== "win32")(
    "preserves both snapshot identities when its pathname is replaced at verification failure",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-snapshot-verify-swap-"));
      roots.push(root);
      const archive = path.join(root, "source.zip");
      const destination = path.join(root, "extract");
      const foreign = Buffer.from("foreign snapshot replacement");
      let movedSnapshot = "";
      let replacementSnapshot = "";
      execFileSync("python3", [
        "-c",
        "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1],'w'); z.writestr('root/file.txt','complete'); z.close()",
        archive,
      ]);
      const dependencies = createNodeBootstrapDependencies(process.platform, {
        testHooks: {
          beforeArchiveSnapshotVerify(target) {
            const directory = path.dirname(target);
            movedSnapshot = `${directory}.owned`;
            replacementSnapshot = target;
            renameSync(directory, movedSnapshot);
            mkdirSync(directory, { mode: 0o700 });
            writeFileSync(target, foreign, { mode: 0o600 });
          },
        },
      });

      await expect(
        dependencies.extractArchive({
          archive,
          destination,
          expectedSha256: await sha256File(archive),
          expectedRoot: "root",
          kind: "zip",
          signal: new AbortController().signal,
        }),
      ).rejects.toThrow(/snapshot identity changed/i);
      expect(await readFile(path.join(movedSnapshot, "archive"))).toEqual(await readFile(archive));
      expect(await readFile(replacementSnapshot)).toEqual(foreign);
      await expect(access(destination)).rejects.toThrow();
    },
  );

  it.runIf(process.platform !== "win32")(
    "preserves a foreign snapshot replacement when cleanup observes a pathname swap",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-snapshot-cleanup-swap-"));
      roots.push(root);
      const archive = path.join(root, "source.zip");
      const destination = path.join(root, "extract");
      const foreign = Buffer.from("foreign cleanup replacement");
      let originalSnapshot = "";
      let replacementSnapshot = "";
      execFileSync("python3", [
        "-c",
        "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1],'w'); z.writestr('root/file.txt','complete'); z.close()",
        archive,
      ]);
      const dependencies = createNodeBootstrapDependencies(process.platform, {
        testHooks: {
          onArchiveSnapshotRemove(target, directory) {
            originalSnapshot = `${directory}.owned`;
            replacementSnapshot = target;
            renameSync(directory, originalSnapshot);
            mkdirSync(directory, { mode: 0o700 });
            writeFileSync(target, foreign, { mode: 0o600 });
          },
        },
      });

      await expect(
        dependencies.extractArchive({
          archive,
          destination,
          expectedSha256: await sha256File(archive),
          expectedRoot: "root",
          kind: "zip",
          signal: new AbortController().signal,
        }),
      ).rejects.toThrow(/cleanup identity changed/i);
      expect(await readFile(replacementSnapshot)).toEqual(foreign);
      expect(await readFile(path.join(originalSnapshot, "archive"))).toEqual(await readFile(archive));
      expect(await readFile(path.join(destination, "root", "file.txt"), "utf8")).toBe("complete");
    },
  );

  it.runIf(process.platform !== "win32")(
    "closes a rejected ZIP snapshot handle before removing its snapshot",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-invalid-zip-close-"));
      roots.push(root);
      const archive = path.join(root, "invalid.zip");
      const destination = path.join(root, "extract");
      const events: string[] = [];
      await writeFile(archive, "not a zip archive");
      const dependencies = createNodeBootstrapDependencies(process.platform, {
        testHooks: {
          onArchiveSnapshotRemove() {
            events.push("removing");
          },
          onZipSnapshotHandle(event) {
            events.push(event);
          },
        },
      });

      await expect(
        dependencies.extractArchive({
          archive,
          destination,
          expectedSha256: await sha256File(archive),
          kind: "zip",
          signal: new AbortController().signal,
        }),
      ).rejects.toThrow();
      expect(events).toEqual(["opened", "closed", "removing"]);
    },
  );

  it.runIf(process.platform !== "win32")(
    "awaits both successful ZIP handle closures before snapshot removal",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-valid-zip-close-"));
      roots.push(root);
      const archive = path.join(root, "valid.zip");
      const destination = path.join(root, "extract");
      const events: string[] = [];
      execFileSync("python3", [
        "-c",
        "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1],'w'); z.writestr('root/file.txt','ok'); z.close()",
        archive,
      ]);
      const dependencies = createNodeBootstrapDependencies(process.platform, {
        testHooks: {
          onArchiveSnapshotRemove() {
            events.push("removing");
          },
          onZipSnapshotHandle(event) {
            events.push(event);
          },
        },
      });

      await expect(
        dependencies.extractArchive({
          archive,
          destination,
          expectedSha256: await sha256File(archive),
          expectedRoot: "root",
          kind: "zip",
          signal: new AbortController().signal,
        }),
      ).resolves.toEqual(["root/file.txt"]);
      expect(events).toEqual(["opened", "closed", "opened", "closed", "removing"]);
    },
  );

  it.runIf(process.platform !== "win32")(
    "validates a complete ZIP listing larger than the former command-output tail",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-large-zip-"));
      roots.push(root);
      const archive = path.join(root, "large.zip");
      const destination = path.join(root, "extract");
      const generator = [
        "import zipfile,sys",
        "z=zipfile.ZipFile(sys.argv[1],'w',compression=zipfile.ZIP_STORED)",
        "z.writestr('root/','')",
        "[(z.writestr('root/' + ('entry-%05d-' % i) + ('x'*64), 'x')) for i in range(5000)]",
        "z.close()",
      ].join(";");
      const generated = await createNodeBootstrapDependencies(process.platform).command.run({
        args: ["-c", generator, archive],
        command: "python3",
        timeoutMs: 30_000,
      });
      expect(generated.exitCode).toBe(0);

      const entries = await createNodeBootstrapDependencies(process.platform).extractArchive({
        archive,
        destination,
        expectedSha256: await sha256File(archive),
        expectedRoot: "root",
        kind: "zip",
        signal: new AbortController().signal,
      });
      expect(entries).toHaveLength(5001);
      expect(entries[0]).toBe("root");
    },
    30_000,
  );

  it.runIf(process.platform !== "win32")(
    "rejects an unsafe early ZIP entry before extracting a listing larger than the former tail",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-unsafe-prefix-"));
      roots.push(root);
      const archive = path.join(root, "unsafe.zip");
      const destination = path.join(root, "extract");
      const generator = [
        "import zipfile,sys",
        "z=zipfile.ZipFile(sys.argv[1],'w',compression=zipfile.ZIP_STORED)",
        "z.writestr('../escape','unsafe')",
        "[(z.writestr('root/' + ('entry-%05d-' % i) + ('x'*64), 'x')) for i in range(5000)]",
        "z.close()",
      ].join(";");
      const dependencies = createNodeBootstrapDependencies(process.platform);
      expect(
        (await dependencies.command.run({ args: ["-c", generator, archive], command: "python3" })).exitCode,
      ).toBe(0);

      await expect(
        dependencies.extractArchive({
          archive,
          destination,
          expectedSha256: await sha256File(archive),
          expectedRoot: "root",
          kind: "zip",
          signal: new AbortController().signal,
        }),
      ).rejects.toThrow(/unsafe path|invalid relative path/i);
      expect(await readFile(archive)).not.toHaveLength(0);
      await expect(access(path.join(destination, "root"))).rejects.toThrow();
    },
    30_000,
  );

  it.runIf(process.platform !== "win32")(
    "validates a complete TAR listing larger than the former command-output tail",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-large-tar-"));
      roots.push(root);
      const archive = path.join(root, "large.tar.gz");
      const destination = path.join(root, "extract");
      const generator = [
        "import io,sys,tarfile",
        "t=tarfile.open(sys.argv[1],'w:gz')",
        "d=tarfile.TarInfo('root/');d.type=tarfile.DIRTYPE;t.addfile(d)",
        "[(lambda x:(setattr(x,'size',1),t.addfile(x,io.BytesIO(b'x'))))(tarfile.TarInfo('root/' + ('entry-%05d-' % i) + ('x'*64))) for i in range(5000)]",
        "t.close()",
      ].join(";");
      const dependencies = createNodeBootstrapDependencies(process.platform);
      expect((await dependencies.command.run({ args: ["-c", generator, archive], command: "python3" })).exitCode).toBe(0);

      const entries = await dependencies.extractArchive({
        archive,
        destination,
        expectedSha256: await sha256File(archive),
        expectedRoot: "root",
        kind: "tar.gz",
        signal: new AbortController().signal,
      });
      expect(entries).toHaveLength(5001);
      expect(entries[0]).toBe("root");
    },
    30_000,
  );

  it.runIf(process.platform !== "win32")(
    "rejects an escaping early TAR link before extracting a large trailing listing",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-unsafe-tar-prefix-"));
      roots.push(root);
      const archive = path.join(root, "unsafe.tar.gz");
      const destination = path.join(root, "extract");
      const generator = [
        "import io,sys,tarfile",
        "t=tarfile.open(sys.argv[1],'w:gz')",
        "d=tarfile.TarInfo('root/');d.type=tarfile.DIRTYPE;t.addfile(d)",
        "l=tarfile.TarInfo('root/link');l.type=tarfile.SYMTYPE;l.linkname='../../escape';t.addfile(l)",
        "[(lambda x:(setattr(x,'size',1),t.addfile(x,io.BytesIO(b'x'))))(tarfile.TarInfo('root/' + ('entry-%05d-' % i) + ('x'*64))) for i in range(5000)]",
        "t.close()",
      ].join(";");
      const dependencies = createNodeBootstrapDependencies(process.platform);
      expect((await dependencies.command.run({ args: ["-c", generator, archive], command: "python3" })).exitCode).toBe(0);

      await expect(
        dependencies.extractArchive({
          archive,
          destination,
          expectedSha256: await sha256File(archive),
          expectedRoot: "root",
          kind: "tar.gz",
          signal: new AbortController().signal,
        }),
      ).rejects.toThrow(/link escapes/i);
      await expect(access(path.join(destination, "root"))).rejects.toThrow();
    },
    30_000,
  );

  it.runIf(process.platform !== "win32")(
    "extracts from one stable TAR snapshot when the caller path is replaced during a 40,001-entry listing",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-stable-tar-"));
      roots.push(root);
      const archive = path.join(root, "source.tar.gz");
      const replacement = path.join(root, "replacement.tar.gz");
      const destination = path.join(root, "extract");
      const generator = [
        "import io,sys,tarfile",
        "t=tarfile.open(sys.argv[1],'w:gz')",
        "d=tarfile.TarInfo('root/');d.type=tarfile.DIRTYPE;t.addfile(d)",
        "[(lambda x:(setattr(x,'size',0),t.addfile(x,io.BytesIO(b''))))(tarfile.TarInfo('root/entry-%05d' % i)) for i in range(40000)]",
        "t.close()",
        "t=tarfile.open(sys.argv[2],'w:gz')",
        "x=tarfile.TarInfo('other/UNVALIDATED');x.size=3;t.addfile(x,io.BytesIO(b'bad'));t.close()",
      ].join(";");
      execFileSync("python3", ["-c", generator, archive, replacement]);
      const expectedSha256 = await sha256File(archive);
      const dependencies = createNodeBootstrapDependencies(process.platform, {
        testHooks: {
          onArchiveEntry(index, kind) {
            if (kind === "tar.gz" && index === 1) renameSync(replacement, archive);
          },
        },
      });
      const extraction = dependencies.extractArchive({
        archive,
        destination,
        expectedSha256,
        expectedRoot: "root",
        kind: "tar.gz",
        signal: new AbortController().signal,
      });

      await expect(extraction).resolves.toHaveLength(40_001);
      await expect(access(path.join(destination, "root", "entry-39999"))).resolves.toBeUndefined();
      await expect(access(path.join(destination, "other", "UNVALIDATED"))).rejects.toThrow();
    },
    60_000,
  );

  it.runIf(process.platform !== "win32")(
    "aborts in the middle of one large ZIP entry and preserves the partial tree",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-cancel-zip-"));
      roots.push(root);
      const archive = path.join(root, "large.zip");
      const destination = path.join(root, "extract");
      execFileSync("python3", [
        "-c",
        "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1],'w',compression=zipfile.ZIP_STORED); z.writestr('root/large.bin',b'x'*(96*1024*1024)); z.close()",
        archive,
      ]);
      const abort = new AbortController();
      const events: string[] = [];
      const dependencies = createNodeBootstrapDependencies(process.platform, {
        testHooks: {
          onArchiveSnapshotRemove() {
            events.push("removing");
          },
          onZipSnapshotHandle(event) {
            events.push(event);
          },
        },
      });
      const extraction = dependencies.extractArchive({
        archive,
        destination,
        expectedSha256: await sha256File(archive),
        expectedRoot: "root",
        kind: "zip",
        signal: abort.signal,
      });
      await vi.waitFor(() => expect(access(path.join(destination, "root", "large.bin"))).resolves.toBeUndefined(), {
        timeout: 15_000,
      });
      abort.abort();

      await expect(extraction).rejects.toMatchObject({ name: "AbortError" });
      await expect(access(path.join(destination, "root"))).resolves.toBeUndefined();
      expect(events.at(-1)).toBe("removing");
      expect(events.slice(0, -1).at(-1)).toBe("closed");
    },
    30_000,
  );

  it.runIf(process.platform !== "win32")(
    "aborts during a large TAR extraction and preserves the partial tree",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-cancel-tar-"));
      roots.push(root);
      const archive = path.join(root, "large.tar.gz");
      const destination = path.join(root, "extract");
      const generator = [
        "import io,sys,tarfile",
        "t=tarfile.open(sys.argv[1],'w:gz')",
        "[(lambda x:(setattr(x,'size',1024),t.addfile(x,io.BytesIO(b'x'*1024))))(tarfile.TarInfo('root/entry-%05d' % i)) for i in range(20000)]",
        "t.close()",
      ].join(";");
      execFileSync("python3", ["-c", generator, archive]);
      const abort = new AbortController();
      const extraction = createNodeBootstrapDependencies(process.platform).extractArchive({
        archive,
        destination,
        expectedSha256: await sha256File(archive),
        expectedRoot: "root",
        kind: "tar.gz",
        signal: abort.signal,
      });
      await vi.waitFor(() => expect(access(path.join(destination, "root"))).resolves.toBeUndefined(), {
        timeout: 15_000,
      });
      abort.abort();

      await expect(extraction).rejects.toMatchObject({ name: "AbortError" });
      await expect(access(path.join(destination, "root"))).resolves.toBeUndefined();
    },
    30_000,
  );

  it.runIf(process.platform !== "win32")(
    "reserves a fresh UUID directory without touching a colliding foreign path",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-reserve-collision-"));
      roots.push(root);
      const firstId = "11111111-1111-4111-8111-111111111111";
      const secondId = "22222222-2222-4222-8222-222222222222";
      const prefix = "FlintTrade.candidate-1";
      const foreign = path.join(root, `${prefix}-${firstId}`);
      await mkdir(foreign);
      await writeFile(path.join(foreign, "sentinel"), "foreign");
      const ids = [firstId, secondId];
      const dependencies = createNodeBootstrapDependencies(process.platform, {
        testHooks: { temporaryDirectoryId: () => ids.shift()! },
      });

      const reservation = await dependencies.fileSystem.reserveTemporaryDirectory(root, prefix);

      expect(reservation.path).toBe(path.join(root, `${prefix}-${secondId}`));
      expect(await readFile(path.join(foreign, "sentinel"), "utf8")).toBe("foreign");
      await expect(
        dependencies.fileSystem.assertDirectoryIdentity(reservation.path, reservation.identity, true),
      ).resolves.toBeUndefined();
    },
  );

  it.runIf(process.platform !== "win32")(
    "rejects a reserved-directory pathname swap without deleting either directory",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-reserve-swap-"));
      roots.push(root);
      const outside = path.join(root, "outside");
      const moved = path.join(root, "moved-reservation");
      await mkdir(outside);
      await writeFile(path.join(outside, "sentinel"), "outside");
      const dependencies = createNodeBootstrapDependencies(process.platform, {
        testHooks: {
          afterTemporaryDirectoryCreated(target) {
            renameSync(target, moved);
            symlinkSync(outside, target, "dir");
          },
          temporaryDirectoryId: () => "33333333-3333-4333-8333-333333333333",
        },
      });

      await expect(
        dependencies.fileSystem.reserveTemporaryDirectory(root, "FlintTrade.candidate-1"),
      ).rejects.toThrow(/identity changed/i);
      expect(await readFile(path.join(outside, "sentinel"), "utf8")).toBe("outside");
      await expect(access(moved)).resolves.toBeUndefined();
    },
  );

  it.runIf(process.platform !== "win32")(
    "fails closed for destination files, symlinks and directories at no-clobber promotion",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-promote-"));
      roots.push(root);
      const dependencies = createNodeBootstrapDependencies(process.platform, {
        testHooks: { testAtomicPromote },
      });
      for (const kind of ["file", "symlink", "empty-directory", "non-empty-directory"] as const) {
        const source = path.join(root, `source-${kind}`);
        const destination = path.join(root, `destination-${kind}`);
        await mkdir(source);
        await writeFile(path.join(source, "identity"), "candidate");
        if (kind === "file") await writeFile(destination, "existing");
        if (kind === "symlink") await symlink(source, destination);
        if (kind.includes("directory")) await mkdir(destination);
        if (kind === "non-empty-directory") await writeFile(path.join(destination, "identity"), "existing");

        const identity = await dependencies.fileSystem.directoryIdentity(source);
        await expect(dependencies.fileSystem.promoteAbsent(source, destination, identity)).rejects.toThrow(/already exists/i);
        expect(await readFile(path.join(source, "identity"), "utf8")).toBe("candidate");
      }
    },
  );

  it.runIf(process.platform !== "win32")(
    "preserves candidate and foreign identities when the destination appears at the native promotion boundary",
    async () => {
      const root = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-promote-race-")));
      roots.push(root);
      const source = path.join(root, "candidate");
      const destination = path.join(root, "active");
      await mkdir(source);
      await writeFile(path.join(source, "candidate"), "candidate");
      let foreignIdentity: Awaited<ReturnType<typeof lstat>> | null = null;
      const dependencies = createNodeBootstrapDependencies(process.platform, {
        testHooks: {
          async beforeAtomicPromotion() {
            await mkdir(destination);
            await writeFile(path.join(destination, "foreign"), "foreign");
            foreignIdentity = await lstat(destination);
          },
          testAtomicPromote,
        },
      });
      const candidateIdentity = await dependencies.fileSystem.directoryIdentity(source);

      await expect(
        dependencies.fileSystem.promoteAbsent(source, destination, candidateIdentity),
      ).rejects.toThrow(/already exists/i);
      const candidateAfter = await lstat(source);
      const foreignAfter = await lstat(destination);
      expect({ dev: candidateAfter.dev, ino: candidateAfter.ino }).toEqual(candidateIdentity);
      expect({ dev: foreignAfter.dev, ino: foreignAfter.ino }).toEqual({
        dev: foreignIdentity!.dev,
        ino: foreignIdentity!.ino,
      });
      expect(await readFile(path.join(source, "candidate"), "utf8")).toBe("candidate");
      expect(await readFile(path.join(destination, "foreign"), "utf8")).toBe("foreign");
    },
  );

  it("allows confined tar symlinks and rejects symlink or hardlink escape", () => {
    const entries = ["root/bin/corepack", "root/lib/corepack"];
    expect(() =>
      validateTarLinkEntries(entries, "lrwxr-xr-x user/group 0 date root/bin/corepack -> ../lib/corepack", "tar"),
    ).not.toThrow();
    expect(() =>
      validateTarLinkEntries(entries, "lrwxr-xr-x user/group 0 date root/bin/corepack -> ../../../etc/passwd", "tar"),
    ).toThrow("escapes");
    expect(() =>
      validateTarLinkEntries(entries, "hrw-r--r-- user/group 0 date root/bin/corepack link to ../../outside", "tar"),
    ).toThrow("escapes");
  });

  it("rejects missing, cyclic and link-through-link TAR targets", () => {
    expect(() =>
      validateTarLinkEntries(
        ["root/link"],
        "lrwxr-xr-x user/group 0 date root/link -> missing",
        "tar",
      ),
    ).toThrow(/missing|another link/i);
    expect(() =>
      validateTarLinkEntries(
        ["root/a", "root/b"],
        [
          "lrwxr-xr-x user/group 0 date root/a -> b",
          "lrwxr-xr-x user/group 0 date root/b -> a",
        ].join("\n"),
        "tar",
      ),
    ).toThrow(/missing|another link/i);
  });
});
