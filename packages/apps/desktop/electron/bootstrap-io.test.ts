import { access, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createNodeBootstrapDependencies,
  syncDirectoryForDurability,
  validateArchiveEntries,
  validateTarLinkEntries,
} from "./bootstrap-io";

const roots: string[] = [];

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { force: true, recursive: true })));
});

describe("bootstrap system boundaries", () => {
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
      expect(kill).toHaveBeenCalledTimes(1);

      await vi.advanceTimersByTimeAsync(5_001);
      expect(kill).toHaveBeenCalledTimes(1);
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
  });

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
});
