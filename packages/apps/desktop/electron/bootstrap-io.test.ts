import { access, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import https from "node:https";
import { EventEmitter } from "node:events";
import type { IncomingMessage } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { Readable } from "node:stream";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createNodeBootstrapDependencies,
  isSuccessfulTaskkillExit,
  minimalChildEnvironment,
  syncDirectoryForDurability,
  validateArchiveEntries,
  validateTarLinkEntries,
} from "./bootstrap-io";

const roots: string[] = [];

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

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { force: true, recursive: true })));
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

  it("treats every non-zero taskkill exit as failed containment proof", () => {
    expect(isSuccessfulTaskkillExit(0)).toBe(true);
    expect(isSuccessfulTaskkillExit(1)).toBe(false);
    expect(isSuccessfulTaskkillExit(128)).toBe(false);
    expect(isSuccessfulTaskkillExit(null)).toBe(false);
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
  it("runs a probed command and captures bounded output", async () => {
    const dependencies = createNodeBootstrapDependencies(process.platform);
    const result = await dependencies.command.run({
      args: ["-e", "process.stdout.write('probe-ok')"],
      command: process.execPath,
      timeoutMs: 5_000,
    });

    expect(result).toEqual({ exitCode: 0, stderr: "", stdout: "probe-ok" });
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
      const dependencies = createNodeBootstrapDependencies(process.platform);
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
      await expect(running).resolves.toMatchObject({ exitCode: 130 });
      await new Promise((resolve) => setTimeout(resolve, 1_700));

      await expect(access(marker)).rejects.toThrow();
    },
    12_000,
  );

  it.runIf(process.platform !== "win32")("clears the force-kill timer after a cancelled process exits", async () => {
    vi.useFakeTimers();
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

      await vi.advanceTimersByTimeAsync(5_001);
      expect(kill.mock.calls.filter((call) => call[1] === "SIGTERM" || call[1] === "SIGKILL")).toHaveLength(1);
    } finally {
      kill.mockRestore();
      vi.useRealTimers();
    }
  });

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
    "validates a complete ZIP listing larger than the former command-output tail",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-large-zip-"));
      roots.push(root);
      const archive = path.join(root, "large.zip");
      const destination = path.join(root, "extract");
      await mkdir(destination);
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
      await mkdir(destination);
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
      await mkdir(destination);
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
      await mkdir(destination);
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
    "fails closed for destination files, symlinks and directories at no-clobber promotion",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-promote-"));
      roots.push(root);
      const dependencies = createNodeBootstrapDependencies(process.platform);
      for (const kind of ["file", "symlink", "empty-directory", "non-empty-directory"] as const) {
        const source = path.join(root, `source-${kind}`);
        const destination = path.join(root, `destination-${kind}`);
        await mkdir(source);
        await writeFile(path.join(source, "identity"), "candidate");
        if (kind === "file") await writeFile(destination, "existing");
        if (kind === "symlink") await symlink(source, destination);
        if (kind.includes("directory")) await mkdir(destination);
        if (kind === "non-empty-directory") await writeFile(path.join(destination, "identity"), "existing");

        await expect(dependencies.fileSystem.promoteAbsent(source, destination)).rejects.toThrow(/already exists/i);
        expect(await readFile(path.join(source, "identity"), "utf8")).toBe("candidate");
      }
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
