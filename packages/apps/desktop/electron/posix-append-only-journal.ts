import { createHash, randomUUID } from "node:crypto";
import { constants } from "node:fs";
import { link, lstat, mkdir, open, opendir, realpath } from "node:fs/promises";
import path from "node:path";

const OWNER_NAME = "owner.json";
const REVISION_PATTERN = /^revision-([0-9]{8})-([0-9a-f]{64})\.json$/;
const STAGE_PATTERN = /^\.stage-([0-9]{8})-([0-9a-f]{64})-([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\.json$/;
const MAX_CONTENT_BYTES = 128 * 1024;
const MAX_RECORD_BYTES = 512 * 1024;
const MAX_REVISIONS = 4_096;
const MAX_TOTAL_BYTES = 64 * 1024 * 1024;

type JournalKind = "tombstone" | "value";

interface DirectoryPin {
  dev: number;
  handle: Awaited<ReturnType<typeof open>>;
  ino: number;
  target: string;
}

interface JournalOwner {
  journalId: string;
  logicalPathSha256: string;
  schemaVersion: 1;
}

interface JournalRecordBody {
  contents: string | null;
  kind: JournalKind;
  previousSha256: string | null;
  schemaVersion: 1;
  sequence: number;
}

interface JournalRecord extends JournalRecordBody {
  sha256: string;
}

interface ScannedFile {
  contents: string;
  dev: number;
  ino: number;
  mode: number;
  nlink: number;
  size: number;
  uid: number;
}

interface ScannedRevision {
  file: ScannedFile;
  name: string;
  record: JournalRecord;
}

interface JournalState {
  latest: JournalRecord | null;
  revisions: ScannedRevision[];
  totalBytes: number;
}

export type PosixAppendOnlyJournalAdversarialEvent =
  | "before-directory-create"
  | "before-record-link"
  | "before-stage-open"
  | "before-tombstone-link"
  | "before-value-link";

export interface PosixAppendOnlyJournalOptions {
  durability?: (event: "directory-synced" | "journal-file-synced", target: string) => void;
  testHooks?: {
    adversarial?: (
      event: PosixAppendOnlyJournalAdversarialEvent,
      paths: {
        record?: string;
        stage?: string;
        target: string;
      },
    ) => Promise<void> | void;
    limits?: {
      maxRevisions?: number;
      maxTotalBytes?: number;
    };
  };
}

export interface PosixAppendOnlyJournal {
  read(target: string): Promise<string | null>;
  remove(target: string): Promise<void>;
  write(target: string, contents: string): Promise<void>;
}

function sha256(value: string | Buffer): string {
  return createHash("sha256").update(value).digest("hex");
}

function missing(error: unknown): boolean {
  return error instanceof Error && "code" in error && (error as NodeJS.ErrnoException).code === "ENOENT";
}

function exclusiveCollision(error: unknown): boolean {
  return error instanceof Error && "code" in error && (error as NodeJS.ErrnoException).code === "EEXIST";
}

function sequenceName(sequence: number): string {
  return String(sequence).padStart(8, "0");
}

function canonicalOwner(owner: JournalOwner): string {
  return `${JSON.stringify({
    journalId: owner.journalId,
    logicalPathSha256: owner.logicalPathSha256,
    schemaVersion: owner.schemaVersion,
  })}\n`;
}

function canonicalRecordBody(record: JournalRecordBody): string {
  return JSON.stringify({
    contents: record.contents,
    kind: record.kind,
    previousSha256: record.previousSha256,
    schemaVersion: record.schemaVersion,
    sequence: record.sequence,
  });
}

function canonicalRecord(record: JournalRecord): string {
  return `${JSON.stringify({
    contents: record.contents,
    kind: record.kind,
    previousSha256: record.previousSha256,
    schemaVersion: record.schemaVersion,
    sequence: record.sequence,
    sha256: record.sha256,
  })}\n`;
}

function parseOwner(contents: string, target: string): JournalOwner {
  let parsed: unknown;
  try {
    parsed = JSON.parse(contents);
  } catch (error) {
    throw new Error(`POSIX append-only journal owner metadata is invalid at ${target}.`, { cause: error });
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`POSIX append-only journal owner metadata is invalid at ${target}.`);
  }
  const owner = parsed as Record<string, unknown>;
  if (
    owner.schemaVersion !== 1 ||
    typeof owner.journalId !== "string" ||
    !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(owner.journalId) ||
    typeof owner.logicalPathSha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(owner.logicalPathSha256) ||
    Object.keys(owner).sort().join(",") !== "journalId,logicalPathSha256,schemaVersion"
  ) {
    throw new Error(`POSIX append-only journal owner metadata is invalid at ${target}.`);
  }
  const result = owner as unknown as JournalOwner;
  if (
    result.logicalPathSha256 !== sha256(path.resolve(target)) ||
    contents !== canonicalOwner(result)
  ) {
    throw new Error(`POSIX append-only journal owner metadata does not bind its logical path at ${target}.`);
  }
  return result;
}

function parseRecord(contents: string, name: string): JournalRecord {
  if (Buffer.byteLength(contents) > MAX_RECORD_BYTES) {
    throw new Error(`POSIX append-only journal record exceeds ${MAX_RECORD_BYTES} bytes: ${name}.`);
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(contents);
  } catch (error) {
    throw new Error(`POSIX append-only journal record is invalid JSON: ${name}.`, { cause: error });
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`POSIX append-only journal record has an invalid schema: ${name}.`);
  }
  const value = parsed as Record<string, unknown>;
  const contentsValue = value.contents;
  if (
    value.schemaVersion !== 1 ||
    !Number.isSafeInteger(value.sequence) ||
    Number(value.sequence) <= 0 ||
    Number(value.sequence) > MAX_REVISIONS ||
    !["tombstone", "value"].includes(String(value.kind)) ||
    (value.kind === "value" ? typeof contentsValue !== "string" : contentsValue !== null) ||
    (value.previousSha256 !== null && (
      typeof value.previousSha256 !== "string" || !/^[0-9a-f]{64}$/.test(value.previousSha256)
    )) ||
    typeof value.sha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(value.sha256) ||
    Object.keys(value).sort().join(",") !== "contents,kind,previousSha256,schemaVersion,sequence,sha256"
  ) {
    throw new Error(`POSIX append-only journal record has an invalid schema: ${name}.`);
  }
  if (typeof contentsValue === "string" && Buffer.byteLength(contentsValue) > MAX_CONTENT_BYTES) {
    throw new Error(`POSIX append-only journal value exceeds ${MAX_CONTENT_BYTES} bytes: ${name}.`);
  }
  const record = value as unknown as JournalRecord;
  const expectedSha256 = sha256(canonicalRecordBody(record));
  const nameMatch = REVISION_PATTERN.exec(name);
  if (
    !nameMatch ||
    Number(nameMatch[1]) !== record.sequence ||
    nameMatch[2] !== record.sha256 ||
    record.sha256 !== expectedSha256 ||
    contents !== canonicalRecord(record)
  ) {
    throw new Error(`POSIX append-only journal record digest or canonical encoding is invalid: ${name}.`);
  }
  return record;
}

function effectiveUserId(): number | null {
  return typeof process.geteuid === "function" ? process.geteuid() : null;
}

async function assertDirectoryPin(pin: DirectoryPin): Promise<void> {
  const [opened, named] = await Promise.all([
    pin.handle.stat(),
    lstat(pin.target),
  ]);
  if (
    !opened.isDirectory() ||
    !named.isDirectory() ||
    named.isSymbolicLink() ||
    opened.dev !== pin.dev ||
    opened.ino !== pin.ino ||
    named.dev !== pin.dev ||
    named.ino !== pin.ino
  ) {
    throw new Error(`POSIX append-only journal directory identity changed at ${pin.target}; evidence was preserved.`);
  }
}

async function syncPinnedDirectory(
  pin: DirectoryPin,
  durability: NonNullable<PosixAppendOnlyJournalOptions["durability"]>,
): Promise<void> {
  await assertDirectoryPin(pin);
  await pin.handle.sync();
  durability("directory-synced", pin.target);
  await assertDirectoryPin(pin);
}

async function scanFile(pin: DirectoryPin, name: string, expectedMode: number): Promise<ScannedFile> {
  await assertDirectoryPin(pin);
  const target = path.join(pin.target, name);
  const first = await lstat(target);
  if (first.isSymbolicLink() || !first.isFile()) {
    throw new Error(`POSIX append-only journal entry is not a no-follow regular file: ${name}.`);
  }
  const handle = await open(target, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const opened = await handle.stat();
    if (
      !opened.isFile() ||
      opened.dev !== first.dev ||
      opened.ino !== first.ino ||
      opened.size < 0 ||
      opened.size > MAX_RECORD_BYTES ||
      (opened.mode & 0o777) !== expectedMode ||
      (effectiveUserId() !== null && opened.uid !== effectiveUserId())
    ) {
      throw new Error(`POSIX append-only journal entry identity or permissions changed: ${name}.`);
    }
    const contents = await handle.readFile({ encoding: "utf8" });
    const [after, namedAfter] = await Promise.all([handle.stat(), lstat(target)]);
    if (
      after.dev !== opened.dev ||
      after.ino !== opened.ino ||
      after.size !== opened.size ||
      after.mtimeMs !== opened.mtimeMs ||
      after.ctimeMs !== opened.ctimeMs ||
      namedAfter.dev !== opened.dev ||
      namedAfter.ino !== opened.ino
    ) {
      throw new Error(`POSIX append-only journal entry changed during read: ${name}.`);
    }
    await assertDirectoryPin(pin);
    return {
      contents,
      dev: Number(opened.dev),
      ino: Number(opened.ino),
      mode: opened.mode,
      nlink: opened.nlink,
      size: opened.size,
      uid: opened.uid,
    };
  } finally {
    await handle.close();
  }
}

async function openJournalDirectory(target: string, create: boolean): Promise<DirectoryPin | null> {
  if (!path.isAbsolute(target) || path.resolve(target) !== target) {
    throw new Error("POSIX append-only journal path must be absolute and normalised.");
  }
  const canonicalParent = await realpath(path.dirname(target));
  target = path.join(canonicalParent, path.basename(target));
  let created = false;
  if (create) {
    try {
      await mkdir(target, { mode: 0o700 });
      created = true;
    } catch (error) {
      if (!exclusiveCollision(error)) throw error;
    }
  }
  let metadata: Awaited<ReturnType<typeof lstat>>;
  try {
    metadata = await lstat(target);
  } catch (error) {
    if (!create && missing(error)) return null;
    throw error;
  }
  if (
    metadata.isSymbolicLink() ||
    !metadata.isDirectory() ||
    (metadata.mode & 0o777) !== 0o700 ||
    (effectiveUserId() !== null && metadata.uid !== effectiveUserId())
  ) {
    throw new Error(`POSIX append-only journal path is not an owner-private no-follow directory: ${target}.`);
  }
  if ((await realpath(target)) !== target) throw new Error(`POSIX append-only journal path changed identity: ${target}.`);
  const handle = await open(target, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_DIRECTORY);
  const pin: DirectoryPin = {
    dev: Number(metadata.dev),
    handle,
    ino: Number(metadata.ino),
    target,
  };
  try {
    await assertDirectoryPin(pin);
    const ownerPath = path.join(target, OWNER_NAME);
    if (created) {
      const owner: JournalOwner = {
        journalId: randomUUID(),
        logicalPathSha256: sha256(target),
        schemaVersion: 1,
      };
      const ownerHandle = await open(
        ownerPath,
        constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY | constants.O_NOFOLLOW,
        0o600,
      );
      try {
        await ownerHandle.writeFile(canonicalOwner(owner), { encoding: "utf8" });
        await ownerHandle.sync();
        await ownerHandle.chmod(0o400);
        await ownerHandle.sync();
      } finally {
        await ownerHandle.close();
      }
      await pin.handle.sync();
      const parentHandle = await open(path.dirname(target), constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_DIRECTORY);
      try {
        await parentHandle.sync();
      } finally {
        await parentHandle.close();
      }
    }
    const ownerFile = await scanFile(pin, OWNER_NAME, 0o400);
    if (ownerFile.nlink !== 1) {
      throw new Error(`POSIX append-only journal owner metadata has an unexpected link count at ${target}.`);
    }
    parseOwner(ownerFile.contents, target);
    return pin;
  } catch (error) {
    await handle.close().catch(() => undefined);
    throw error;
  }
}

async function scanJournal(
  pin: DirectoryPin,
  limits: { maxRevisions: number; maxTotalBytes: number },
): Promise<JournalState> {
  await assertDirectoryPin(pin);
  const names: string[] = [];
  const directory = await opendir(pin.target);
  for await (const entry of directory) {
    names.push(entry.name);
    if (names.length > 1 + (limits.maxRevisions * 2)) {
      throw new Error(
        `POSIX append-only journal reached its ${limits.maxRevisions}-revision bound at ${pin.target}; ` +
        "stop FlintTrade and archive the exact journal directory before retrying.",
      );
    }
  }
  await assertDirectoryPin(pin);
  const revisionNames = names.filter((name) => REVISION_PATTERN.test(name)).sort();
  const stageNames = names.filter((name) => STAGE_PATTERN.test(name)).sort();
  const foreign = names.filter((name) => name !== OWNER_NAME && !REVISION_PATTERN.test(name) && !STAGE_PATTERN.test(name));
  if (foreign.length > 0) {
    throw new Error(`POSIX append-only journal contains foreign entries at ${pin.target}; evidence was preserved.`);
  }
  if (revisionNames.length > limits.maxRevisions || stageNames.length > limits.maxRevisions) {
    throw new Error(
      `POSIX append-only journal reached its ${limits.maxRevisions}-revision bound at ${pin.target}; ` +
      "stop FlintTrade and archive the exact journal directory before retrying.",
    );
  }

  const revisions: ScannedRevision[] = [];
  const uniqueInodes = new Map<string, number>();
  for (const name of revisionNames) {
    const file = await scanFile(pin, name, 0o400);
    if (file.nlink !== 2) {
      throw new Error(`POSIX append-only journal revision has an unexpected link count: ${name}.`);
    }
    const record = parseRecord(file.contents, name);
    revisions.push({ file, name, record });
    uniqueInodes.set(`${file.dev}:${file.ino}`, file.size);
  }
  const stageInodes = new Map<string, string>();
  for (const name of stageNames) {
    const file = await scanFile(pin, name, 0o400);
    if (file.nlink !== 2) {
      throw new Error(`POSIX append-only journal has an unpublished or multiply-linked stage: ${name}.`);
    }
    const match = STAGE_PATTERN.exec(name)!;
    const recordName = `revision-${match[1]}-${match[2]}.json`;
    const revision = revisions.find((candidate) => candidate.name === recordName);
    if (
      !revision ||
      revision.file.dev !== file.dev ||
      revision.file.ino !== file.ino ||
      revision.file.contents !== file.contents
    ) {
      throw new Error(`POSIX append-only journal has an unauthenticated publication stage: ${name}.`);
    }
    const inode = `${file.dev}:${file.ino}`;
    if (stageInodes.has(inode)) {
      throw new Error(`POSIX append-only journal revision has duplicate publication stages: ${name}.`);
    }
    stageInodes.set(inode, name);
    uniqueInodes.set(inode, file.size);
  }
  if (stageInodes.size !== revisions.length) {
    throw new Error(`POSIX append-only journal has a revision without its authenticated publication stage at ${pin.target}.`);
  }

  let previous: JournalRecord | null = null;
  for (const revision of revisions) {
    if (
      revision.record.sequence !== (previous?.sequence ?? 0) + 1 ||
      revision.record.previousSha256 !== (previous?.sha256 ?? null)
    ) {
      throw new Error(`POSIX append-only journal revision chain is incomplete or reordered at ${pin.target}.`);
    }
    previous = revision.record;
  }
  const totalBytes = [...uniqueInodes.values()].reduce((total, size) => total + size, 0);
  if (totalBytes > limits.maxTotalBytes) {
    throw new Error(
      `POSIX append-only journal exceeds its ${limits.maxTotalBytes}-byte growth bound at ${pin.target}; ` +
      "stop FlintTrade and archive the exact journal directory before retrying.",
    );
  }
  return { latest: previous, revisions, totalBytes };
}

export function createPosixAppendOnlyJournal(
  options: PosixAppendOnlyJournalOptions = {},
): PosixAppendOnlyJournal {
  const durability = options.durability ?? (() => undefined);
  const adversarial = options.testHooks?.adversarial ?? (() => undefined);
  const maxRevisions = options.testHooks?.limits?.maxRevisions ?? MAX_REVISIONS;
  const maxTotalBytes = options.testHooks?.limits?.maxTotalBytes ?? MAX_TOTAL_BYTES;
  if (
    !Number.isSafeInteger(maxRevisions) ||
    maxRevisions <= 0 ||
    maxRevisions > MAX_REVISIONS ||
    !Number.isSafeInteger(maxTotalBytes) ||
    maxTotalBytes <= 0 ||
    maxTotalBytes > MAX_TOTAL_BYTES
  ) {
    throw new Error("POSIX append-only journal test limits are invalid.");
  }
  const limits = { maxRevisions, maxTotalBytes };

  const append = async (target: string, contents: string | null, skipIfMissing = false): Promise<void> => {
    if (contents !== null && Buffer.byteLength(contents) > MAX_CONTENT_BYTES) {
      throw new Error(`Promotion journal exceeds ${MAX_CONTENT_BYTES} bytes.`);
    }
    let pin = await openJournalDirectory(target, false);
    if (!pin) {
      if (skipIfMissing) return;
      await adversarial("before-directory-create", { target });
      pin = await openJournalDirectory(target, true);
    }
    if (!pin) throw new Error(`POSIX append-only journal directory could not be opened: ${target}.`);
    try {
      target = pin.target;
      const state = await scanJournal(pin, limits);
      if (state.revisions.length >= maxRevisions) {
        throw new Error(
          `POSIX append-only journal reached its ${maxRevisions}-revision bound at ${target}; ` +
          "stop FlintTrade and archive the exact journal directory before retrying.",
        );
      }
      const body: JournalRecordBody = {
        contents,
        kind: contents === null ? "tombstone" : "value",
        previousSha256: state.latest?.sha256 ?? null,
        schemaVersion: 1,
        sequence: state.revisions.length + 1,
      };
      const record: JournalRecord = { ...body, sha256: sha256(canonicalRecordBody(body)) };
      const encoded = canonicalRecord(record);
      if (state.totalBytes + Buffer.byteLength(encoded) > maxTotalBytes) {
        throw new Error(
          `POSIX append-only journal would exceed its ${maxTotalBytes}-byte growth bound at ${target}; ` +
          "stop FlintTrade and archive the exact journal directory before retrying.",
        );
      }
      const sequence = sequenceName(record.sequence);
      const stage = path.join(target, `.stage-${sequence}-${record.sha256}-${randomUUID()}.json`);
      const revision = path.join(target, `revision-${sequence}-${record.sha256}.json`);
      await adversarial("before-stage-open", { record: revision, stage, target });
      await assertDirectoryPin(pin);
      const stageHandle = await open(
        stage,
        constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY | constants.O_NOFOLLOW,
        0o600,
      );
      try {
        await stageHandle.writeFile(encoded, { encoding: "utf8" });
        await stageHandle.sync();
        await stageHandle.chmod(0o400);
        await stageHandle.sync();
        durability("journal-file-synced", stage);
      } finally {
        await stageHandle.close();
      }
      const pinnedStage = await open(stage, constants.O_RDONLY | constants.O_NOFOLLOW);
      try {
        const stageBefore = await pinnedStage.stat();
        if (
          !stageBefore.isFile() ||
          (stageBefore.mode & 0o777) !== 0o400 ||
          stageBefore.nlink !== 1 ||
          (await pinnedStage.readFile({ encoding: "utf8" })) !== encoded
        ) {
          throw new Error("POSIX append-only journal publication stage changed before commit.");
        }
        await assertDirectoryPin(pin);
        await adversarial(contents === null ? "before-tombstone-link" : "before-value-link", {
          record: revision,
          stage,
          target,
        });
        await adversarial("before-record-link", { record: revision, stage, target });
        await assertDirectoryPin(pin);
        await link(stage, revision);
        const [stageAfter, revisionAfter, pinnedAfter] = await Promise.all([
          lstat(stage),
          lstat(revision),
          pinnedStage.stat(),
        ]);
        if (
          stageAfter.dev !== stageBefore.dev ||
          stageAfter.ino !== stageBefore.ino ||
          revisionAfter.dev !== stageBefore.dev ||
          revisionAfter.ino !== stageBefore.ino ||
          pinnedAfter.dev !== stageBefore.dev ||
          pinnedAfter.ino !== stageBefore.ino ||
          pinnedAfter.nlink !== 2
        ) {
          throw new Error("POSIX append-only journal publication did not retain the exact staged identity.");
        }
        await syncPinnedDirectory(pin, durability);
      } finally {
        await pinnedStage.close();
      }
      const settled = await scanJournal(pin, limits);
      if (settled.latest?.sha256 !== record.sha256) {
        throw new Error("POSIX append-only journal did not publish the expected latest revision.");
      }
    } finally {
      await pin.handle.close();
    }
  };

  return {
    async read(target) {
      const pin = await openJournalDirectory(target, false);
      if (!pin) return null;
      try {
        const state = await scanJournal(pin, limits);
        if (!state.latest || state.latest.kind === "tombstone") return null;
        return state.latest.contents;
      } finally {
        await pin.handle.close();
      }
    },
    remove: (target) => append(target, null, true),
    write: (target, contents) => append(target, contents),
  };
}
