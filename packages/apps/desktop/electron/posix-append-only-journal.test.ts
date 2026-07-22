import { chmod, lstat, mkdir, mkdtemp, readFile, readdir, realpath, rename, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { createPosixAppendOnlyJournal } from "./posix-append-only-journal";
import { createNodeSourcePromotionFileSystem } from "./source-promotion";

describe.runIf(process.platform !== "win32")("POSIX append-only source journal", () => {
  const roots: string[] = [];

  afterEach(async () => {
    await Promise.all(roots.splice(0).map((root) => rm(root, { force: true, recursive: true })));
  });

  async function fixture(label: string) {
    const root = await realpath(await mkdtemp(path.join(tmpdir(), `flinttrade-${label}-`)));
    roots.push(root);
    return {
      journal: path.join(root, ".journal"),
      root,
    };
  }

  it("refuses a foreign logical target inserted at directory creation without replacing it", async () => {
    const { journal } = await fixture("journal-target-insertion");
    const fileSystem = createNodeSourcePromotionFileSystem({
      testHooks: {
        journalAdversarial: async (event, paths) => {
          if (event === "before-directory-create") await writeFile(paths.target, "foreign logical target");
        },
      },
    });

    await expect(fileSystem.writeJournalAtomic(journal, "managed\n")).rejects.toThrow(/owner-private|no-follow/i);
    expect(await readFile(journal, "utf8")).toBe("foreign logical target");
  });

  it.each([
    ["value", "before-value-link"],
    ["tombstone", "before-tombstone-link"],
  ] as const)("preserves a foreign final revision collision during %s publication", async (kind, boundary) => {
    const { journal } = await fixture(`journal-${kind}-collision`);
    const initial = createNodeSourcePromotionFileSystem();
    if (kind === "tombstone") await initial.writeJournalAtomic(journal, "current\n");
    let foreignRecord = "";
    const fileSystem = createNodeSourcePromotionFileSystem({
      testHooks: {
        journalAdversarial: async (event, paths) => {
          if (event !== boundary || !paths.record) return;
          foreignRecord = paths.record;
          await writeFile(paths.record, "foreign revision", { mode: 0o400 });
        },
      },
    });

    const operation = kind === "value"
      ? fileSystem.writeJournalAtomic(journal, "next\n")
      : fileSystem.removeJournal(journal);
    await expect(operation).rejects.toMatchObject({ code: "EEXIST" });
    expect(await readFile(foreignRecord, "utf8")).toBe("foreign revision");
    expect((await readdir(journal)).some((name) => name.startsWith(".stage-"))).toBe(true);
  });

  it.each([
    ["value", "before-value-link"],
    ["tombstone", "before-tombstone-link"],
  ] as const)("detects a logical-directory swap before %s publication and preserves both trees", async (kind, boundary) => {
    const { journal, root } = await fixture(`journal-${kind}-swap`);
    const initial = createNodeSourcePromotionFileSystem();
    await initial.writeJournalAtomic(journal, "current\n");
    const moved = path.join(root, ".journal-owned");
    let injected = false;
    const fileSystem = createNodeSourcePromotionFileSystem({
      testHooks: {
        journalAdversarial: async (event, paths) => {
          if (event !== boundary || injected) return;
          injected = true;
          await rename(paths.target, moved);
          await mkdir(paths.target, { mode: 0o700 });
          await writeFile(path.join(paths.target, "foreign"), "foreign replacement");
        },
      },
    });

    const operation = kind === "value"
      ? fileSystem.writeJournalAtomic(journal, "next\n")
      : fileSystem.removeJournal(journal);
    await expect(operation).rejects.toThrow(/identity changed/i);
    expect(await readFile(path.join(journal, "foreign"), "utf8")).toBe("foreign replacement");
    expect((await readdir(moved)).some((name) => name.startsWith(".stage-"))).toBe(true);
  });

  it("fails closed on a synced but unpublished stage and retains the partial publication", async () => {
    const { journal } = await fixture("journal-partial-publication");
    const fileSystem = createNodeSourcePromotionFileSystem({
      testHooks: {
        journalAdversarial(event) {
          if (event === "before-record-link") throw new Error("simulated crash before publication link");
        },
      },
    });

    await expect(fileSystem.writeJournalAtomic(journal, "value\n")).rejects.toThrow(/simulated crash/i);
    const entries = await readdir(journal);
    expect(entries.filter((name) => name.startsWith(".stage-"))).toHaveLength(1);
    expect(entries.filter((name) => name.startsWith("revision-"))).toHaveLength(0);
    await expect(createNodeSourcePromotionFileSystem().readJournal(journal)).rejects.toThrow(/unpublished/i);
  });

  it("rejects tampering with an immutable linked revision", async () => {
    const { journal } = await fixture("journal-tamper");
    const fileSystem = createNodeSourcePromotionFileSystem();
    await fileSystem.writeJournalAtomic(journal, "value\n");
    const revision = (await readdir(journal)).find((name) => name.startsWith("revision-"));
    if (!revision) throw new Error("test revision is missing");
    const revisionPath = path.join(journal, revision);
    await chmod(revisionPath, 0o600);
    await writeFile(revisionPath, "tampered\n");
    await chmod(revisionPath, 0o400);

    await expect(fileSystem.readJournal(journal)).rejects.toThrow(/invalid|digest|canonical/i);
    expect(await readFile(revisionPath, "utf8")).toBe("tampered\n");
  });

  it("restarts from a tombstone and appends a later operation without removing history", async () => {
    const { journal } = await fixture("journal-restart");
    const firstRuntime = createNodeSourcePromotionFileSystem();
    await firstRuntime.writeJournalAtomic(journal, "first\n");
    await firstRuntime.writeJournalAtomic(journal, "second\n");
    await firstRuntime.removeJournal(journal);

    const secondRuntime = createNodeSourcePromotionFileSystem();
    await expect(secondRuntime.readJournal(journal)).resolves.toBeNull();
    await secondRuntime.writeJournalAtomic(journal, "third\n");
    await expect(createNodeSourcePromotionFileSystem().readJournal(journal)).resolves.toBe("third\n");
    const entries = await readdir(journal);
    expect(entries.filter((name) => name.startsWith("revision-"))).toHaveLength(4);
    expect(entries.filter((name) => name.startsWith(".stage-"))).toHaveLength(4);
  });

  it("does not create storage when removing a wholly absent logical journal", async () => {
    const { journal } = await fixture("journal-absent-remove");
    await createNodeSourcePromotionFileSystem().removeJournal(journal);
    await expect(lstat(journal)).rejects.toMatchObject({ code: "ENOENT" });
  });

  it("fails closed on a foreign entry without deleting it", async () => {
    const { journal } = await fixture("journal-foreign-entry");
    const fileSystem = createNodeSourcePromotionFileSystem();
    await fileSystem.writeJournalAtomic(journal, "value\n");
    const foreign = path.join(journal, "foreign-evidence");
    await writeFile(foreign, "retain me");

    await expect(fileSystem.readJournal(journal)).rejects.toThrow(/foreign entries/i);
    expect(await readFile(foreign, "utf8")).toBe("retain me");
  });

  it("fails closed at the revision bound and retains the last valid value", async () => {
    const { journal } = await fixture("journal-revision-bound");
    const bounded = createPosixAppendOnlyJournal({
      testHooks: {
        limits: { maxRevisions: 2 },
      },
    });
    await bounded.write(journal, "first\n");
    await bounded.write(journal, "second\n");

    await expect(bounded.write(journal, "third\n")).rejects.toThrow(/2-revision bound.*archive/i);
    await expect(bounded.read(journal)).resolves.toBe("second\n");
    const entries = await readdir(journal);
    expect(entries.filter((name) => name.startsWith("revision-"))).toHaveLength(2);
    expect(entries.filter((name) => name.startsWith(".stage-"))).toHaveLength(2);
  });

  it("fails closed at the unique-byte growth bound and retains the last valid value", async () => {
    const { journal } = await fixture("journal-byte-bound");
    const initial = createPosixAppendOnlyJournal();
    await initial.write(journal, "first\n");
    const firstRevision = (await readdir(journal)).find((name) => name.startsWith("revision-"));
    if (!firstRevision) throw new Error("test revision is missing");
    const firstSize = (await lstat(path.join(journal, firstRevision))).size;
    const bounded = createPosixAppendOnlyJournal({
      testHooks: {
        limits: { maxTotalBytes: firstSize },
      },
    });

    await expect(bounded.write(journal, "second\n")).rejects.toThrow(/byte growth bound.*archive/i);
    await expect(bounded.read(journal)).resolves.toBe("first\n");
    const entries = await readdir(journal);
    expect(entries.filter((name) => name.startsWith("revision-"))).toHaveLength(1);
    expect(entries.filter((name) => name.startsWith(".stage-"))).toHaveLength(1);
  });
});
