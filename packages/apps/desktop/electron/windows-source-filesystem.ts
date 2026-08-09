import path from "node:path";

import type { BootstrapDependencies, FileSystemFileIdentity } from "./bootstrap";
import {
  SourceOperationLeaseRetentionError,
  isSourceOperationLeaseRetentionError,
  type SourceOperationLeaseProof,
} from "./source-operation";

export const WINDOWS_NATIVE_IDENTITY_PATTERN = /^[0-9a-f]{16}:[0-9a-f]{32}$/;

export interface WindowsSourceFilesystemBoundary {
  commitJournal(input: { sha256: string; target: string; temporary: string }): Promise<void>;
  inspectDirectory(target: string): Promise<{ nativeIdentity: string; status: "present" } | { status: "missing" }>;
  inspectJournal(target: string): Promise<
    {
      location: "target";
      nativeIdentity: string;
      sha256: string;
      status: "journal-present";
    } | { status: "missing" }
  >;
  quarantineDirectory(input: {
    expectedNativeIdentity: string;
    quarantine: string;
    target: string;
  }): Promise<{ status: "quarantined" }>;
  removeQuarantinedDirectory(input: {
    expectedNativeIdentity: string;
    quarantine: string;
  }): Promise<{ status: "removed" }>;
  removeJournal(input: { target: string }): Promise<void>;
  renameDirectory(input: {
    destination: string;
    expectedNativeIdentity: string;
    source: string;
  }): Promise<void>;
}

export interface WindowsSourceFilesystemOptions {
  dependencies: Pick<BootstrapDependencies, "command" | "fileSystem">;
  expectedHelperSha256: string;
  helper: string;
  operationLease: SourceOperationLeaseProof;
  timeoutMs?: number;
}

type NativeResponse =
  | { identity: string; ok: true; status: "present" }
  | { identity: string; ok: true; sha256: string; status: "journal-entry-present" }
  | {
      identity: string;
      location: "target";
      ok: true;
      sha256: string;
      status: "journal-present";
    }
  | {
      ok: true;
      status: "missing" | "renamed" | "journal-committed" | "journal-recovered" | "journal-removed" | "quarantined" | "removed";
    }
  | { code: string; native: number; ok: false };
type NativeSuccessStatus =
  | "present"
  | "journal-entry-present"
  | "journal-present"
  | "missing"
  | "renamed"
  | "journal-committed"
  | "journal-recovered"
  | "journal-removed"
  | "quarantined"
  | "removed";

const WINDOWS_SOURCE_QUARANTINE_NAME_PATTERN = new RegExp(
  String.raw`^\.FlintTrade\.(?:stale-quarantine-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|cleanup-quarantine-(?:candidate|isolation|staging-(?:candidate|unpack)-[1-9][0-9]*)-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$`,
  "i",
);

function sameFileIdentity(left: FileSystemFileIdentity, right: FileSystemFileIdentity): boolean {
  return (
    left.dev === right.dev &&
    left.ino === right.ino &&
    left.ctimeMs === right.ctimeMs &&
    left.mtimeMs === right.mtimeMs &&
    left.size === right.size
  );
}

function sameWindowsPath(left: string, right: string): boolean {
  const normalise = (value: string): string => {
    let resolved = path.win32.normalize(value);
    if (resolved.startsWith("\\\\?\\UNC\\")) resolved = `\\\\${resolved.slice(8)}`;
    else if (resolved.startsWith("\\\\?\\")) resolved = resolved.slice(4);
    return resolved.toLowerCase();
  };
  return normalise(left) === normalise(right);
}

function requireWindowsPath(target: string, label: string): string {
  if (!path.win32.isAbsolute(target)) throw new Error(`${label} must be an absolute Windows path.`);
  return path.win32.normalize(target);
}

function sameParentEntries(first: string, second: string, label: string): {
  firstName: string;
  parent: string;
  secondName: string;
} {
  const firstPath = requireWindowsPath(first, `${label} first path`);
  const secondPath = requireWindowsPath(second, `${label} second path`);
  const parent = path.win32.dirname(firstPath);
  if (!sameWindowsPath(parent, path.win32.dirname(secondPath))) {
    throw new Error(`${label} requires distinct same-parent paths.`);
  }
  const firstName = path.win32.basename(firstPath);
  const secondName = path.win32.basename(secondPath);
  if (!firstName || !secondName || firstName.toLowerCase() === secondName.toLowerCase()) {
    throw new Error(`${label} requires distinct same-parent paths.`);
  }
  return { firstName, parent, secondName };
}

function parseResponse(stdout: string): NativeResponse {
  const normalised = stdout.replaceAll("\r\n", "\n").trimEnd();
  if (!normalised || normalised.includes("\n")) {
    throw new Error("Windows source filesystem helper returned an invalid response envelope.");
  }
  let value: unknown;
  try {
    value = JSON.parse(normalised);
  } catch (error) {
    throw new Error("Windows source filesystem helper returned invalid JSON.", { cause: error });
  }
  if (typeof value !== "object" || value === null || Array.isArray(value) || !("ok" in value)) {
    throw new Error("Windows source filesystem helper returned an invalid response schema.");
  }
  const response = value as Record<string, unknown>;
  if (response.ok === false) {
    if (
      Object.keys(response).length !== 3 ||
      typeof response.code !== "string" ||
      !/^[A-Z_]+$/.test(response.code) ||
      !Number.isSafeInteger(response.native) ||
      Number(response.native) < 0
    ) {
      throw new Error("Windows source filesystem helper returned an invalid error schema.");
    }
    return response as NativeResponse;
  }
  if (response.ok !== true || typeof response.status !== "string") {
    throw new Error("Windows source filesystem helper returned an invalid success schema.");
  }
  if (response.status === "present") {
    if (
      Object.keys(response).length !== 3 ||
      typeof response.identity !== "string" ||
      !WINDOWS_NATIVE_IDENTITY_PATTERN.test(response.identity)
    ) {
      throw new Error("Windows source filesystem helper returned an invalid native identity.");
    }
  } else if (response.status === "journal-present") {
    if (
      Object.keys(response).length !== 5 ||
      typeof response.identity !== "string" ||
      !WINDOWS_NATIVE_IDENTITY_PATTERN.test(response.identity) ||
      typeof response.sha256 !== "string" ||
      !/^[0-9a-f]{64}$/.test(response.sha256) ||
      response.location !== "target"
    ) {
      throw new Error("Windows source filesystem helper returned invalid journal evidence.");
    }
  } else if (response.status === "journal-entry-present") {
    if (
      Object.keys(response).length !== 4 ||
      typeof response.identity !== "string" ||
      !WINDOWS_NATIVE_IDENTITY_PATTERN.test(response.identity) ||
      typeof response.sha256 !== "string" ||
      !/^[0-9a-f]{64}$/.test(response.sha256)
    ) {
      throw new Error("Windows source filesystem helper returned invalid exact journal evidence.");
    }
  } else if (
    Object.keys(response).length !== 2 ||
    ![
      "missing",
      "renamed",
      "journal-committed",
      "journal-recovered",
      "journal-removed",
      "quarantined",
      "removed",
    ].includes(response.status)
  ) {
    throw new Error("Windows source filesystem helper returned an invalid success status.");
  }
  return response as NativeResponse;
}

function requireIdentity(value: string): string {
  if (!WINDOWS_NATIVE_IDENTITY_PATTERN.test(value)) {
    throw new Error("Windows source filesystem mutation requires an exact native directory identity.");
  }
  return value;
}

export function createWindowsSourceFilesystemBoundary(
  options: WindowsSourceFilesystemOptions,
): WindowsSourceFilesystemBoundary {
  const helper = requireWindowsPath(options.helper, "Windows source filesystem helper");
  if (path.win32.extname(helper).toLowerCase() !== ".exe") {
    throw new Error("Windows source filesystem helper must be an executable path.");
  }
  if (!/^[0-9a-f]{64}$/.test(options.expectedHelperSha256)) {
    throw new Error("Windows source filesystem helper requires a build-bound SHA-256 digest.");
  }
  const timeoutMs = options.timeoutMs ?? 10 * 60_000;
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs <= 0) {
    throw new Error("Windows source filesystem helper timeout must be a positive safe integer.");
  }

  const run = async (args: string[], expectedStatus: NativeSuccessStatus | readonly NativeSuccessStatus[]): Promise<NativeResponse> => {
    await options.operationLease.assertHeld();
    if (!(await options.dependencies.fileSystem.existsNoFollow(helper))) {
      throw new Error("Packaged Windows source filesystem helper is missing.");
    }
    const [canonicalHelper, helperBefore] = await Promise.all([
      options.dependencies.fileSystem.realpath(helper),
      options.dependencies.fileSystem.fileIdentity(helper),
    ]);
    if (!sameWindowsPath(canonicalHelper, helper)) {
      throw new Error("Packaged Windows source filesystem helper resolved through an alias.");
    }

    let result: Awaited<ReturnType<BootstrapDependencies["command"]["run"]>>;
    try {
      result = await options.dependencies.command.run({
        args: ["--source-fs", "1", ...args],
        command: helper,
        env: {},
        expectedExecutableSha256: options.expectedHelperSha256,
        inheritEnvironment: false,
        timeoutMs,
      });
    } catch (error) {
      if (isSourceOperationLeaseRetentionError(error)) throw error;
      throw new SourceOperationLeaseRetentionError(
        "Windows source filesystem command rejected without proving process containment.",
        { cause: error },
      );
    }
    if (!result.contained) {
      throw new SourceOperationLeaseRetentionError(
        "Windows source filesystem process containment could not be proven.",
      );
    }
    // Native Windows: the job supervisor uses stderr for its proof protocol (FLINTTRADE_JOB_SUPERVISOR lines).
    // Strip those before the unexpected-output check so only real helper stderr (or truncation) fails.
    // Keeps security: any non-protocol stderr from the helper still triggers.
    const effectiveStderr = result.stderr.replace(/^FLINTTRADE_JOB_SUPERVISOR.*$/gm, "").trim();
    if (result.stdoutTruncated || result.stderrTruncated || effectiveStderr !== "") {
      throw new Error("Windows source filesystem helper returned truncated or unexpected output.");
    }
    const response = parseResponse(result.stdout);
    const helperAfter = await options.dependencies.fileSystem.fileIdentity(helper);
    if (!sameFileIdentity(helperBefore, helperAfter)) {
      throw new Error("Packaged Windows source filesystem helper identity changed during execution.");
    }
    try {
      await options.operationLease.assertHeld();
    } catch (error) {
      throw new SourceOperationLeaseRetentionError(
        "The source-operation lease could not be re-proven after a Windows filesystem mutation.",
        { cause: error },
      );
    }
    if (response.ok === false) {
      const message = response.code === "RESERVED_SIDECAR_OCCUPIED"
        ? "Reserved Windows journal .previous sidecar is occupied; refusing to adopt or delete it."
        : `Windows source filesystem helper refused the operation (${response.code}).`;
      const error = new Error(message) as NodeJS.ErrnoException;
      if (response.code === "LOCKED") error.code = "EBUSY";
      else error.code = response.code;
      throw error;
    }
    const allowedStatuses = typeof expectedStatus === "string" ? [expectedStatus] : expectedStatus;
    if (result.exitCode !== 0 || !allowedStatuses.includes(response.status)) {
      throw new Error(`Windows source filesystem helper returned an unexpected status with exit code ${result.exitCode}.`);
    }
    return response;
  };

  type JournalEntryEvidence =
    | { identity: string; sha256: string; status: "present" }
    | { status: "missing" };
  const inspectJournalEntry = async (target: string): Promise<JournalEntryEvidence> => {
    const response = await run(
      ["inspect-journal-entry", "--path", requireWindowsPath(target, "Windows journal entry path")],
      ["journal-entry-present", "missing"],
    );
    if (response.ok && response.status === "journal-entry-present") {
      return { identity: response.identity, sha256: response.sha256, status: "present" };
    }
    if (response.ok && response.status === "missing") return { status: "missing" };
    throw new Error("Windows source filesystem helper returned invalid exact journal evidence.");
  };
  const expectedJournalArguments = (
    prefix: "previous" | "target",
    evidence: JournalEntryEvidence,
  ): string[] => evidence.status === "missing"
    ? [`--${prefix}-identity`, "missing", `--${prefix}-sha256`, "missing"]
    : [`--${prefix}-identity`, evidence.identity, `--${prefix}-sha256`, evidence.sha256];
  const recoverJournal = async (target: string): Promise<void> => {
    const normalisedTarget = requireWindowsPath(target, "Windows journal recovery target");
    await run([
      "recover-journal", "--parent", path.win32.dirname(normalisedTarget),
      "--target", path.win32.basename(normalisedTarget),
    ], "journal-recovered");
  };

  return {
    async commitJournal({ sha256, target, temporary }) {
      if (!/^[0-9a-f]{64}$/.test(sha256)) throw new Error("Windows journal commit requires a SHA-256 digest.");
      const names = sameParentEntries(temporary, target, "Windows journal commit");
      await recoverJournal(target);
      const [targetBefore, previousBefore] = await Promise.all([
        inspectJournalEntry(target),
        inspectJournalEntry(`${target}.previous`),
      ]);
      if (previousBefore.status !== "missing") {
        throw new Error("Reserved Windows journal .previous sidecar is occupied; refusing to adopt or delete it.");
      }
      await run([
        "commit-journal", "--parent", names.parent, "--temporary", names.firstName,
        "--target", names.secondName, "--sha256", sha256,
        ...expectedJournalArguments("target", targetBefore),
        ...expectedJournalArguments("previous", previousBefore),
      ], "journal-committed");
    },
    async inspectDirectory(target) {
      const response = await run(
        ["inspect", "--path", requireWindowsPath(target, "Windows inspection path")],
        ["present", "missing"],
      );
      if (response.ok && response.status === "present") {
        return { nativeIdentity: response.identity, status: "present" };
      }
      if (response.ok && response.status === "missing") return { status: "missing" };
      throw new Error("Windows source filesystem helper returned an invalid inspection result.");
    },
    async inspectJournal(target) {
      await recoverJournal(target);
      const response = await run(
        ["inspect-journal", "--path", requireWindowsPath(target, "Windows journal inspection path")],
        ["journal-present", "missing"],
      );
      if (response.ok && response.status === "journal-present") {
        return {
          location: response.location,
          nativeIdentity: response.identity,
          sha256: response.sha256,
          status: "journal-present",
        };
      }
      if (response.ok && response.status === "missing") return { status: "missing" };
      throw new Error("Windows source filesystem helper returned an invalid journal inspection result.");
    },
    async quarantineDirectory({ expectedNativeIdentity, quarantine, target }) {
      const names = sameParentEntries(target, quarantine, "Windows directory quarantine");
      if (!WINDOWS_SOURCE_QUARANTINE_NAME_PATTERN.test(names.secondName)) {
        throw new Error("Windows directory quarantine requires an exact managed quarantine name.");
      }
      await run([
        "quarantine-directory", "--parent", names.parent, "--target", names.firstName,
        "--quarantine", names.secondName, "--expected", requireIdentity(expectedNativeIdentity),
      ], "quarantined");
      return { status: "quarantined" };
    },
    async removeQuarantinedDirectory({ expectedNativeIdentity, quarantine }) {
      const normalisedQuarantine = requireWindowsPath(quarantine, "Windows quarantine removal target");
      const quarantineName = path.win32.basename(normalisedQuarantine);
      if (!WINDOWS_SOURCE_QUARANTINE_NAME_PATTERN.test(quarantineName)) {
        throw new Error("Windows quarantine removal requires an exact managed quarantine name.");
      }
      await run([
        "remove-quarantined-directory",
        "--parent", path.win32.dirname(normalisedQuarantine),
        "--quarantine", quarantineName,
        "--expected", requireIdentity(expectedNativeIdentity),
      ], "removed");
      return { status: "removed" };
    },
    async removeJournal({ target }) {
      const normalisedTarget = requireWindowsPath(target, "Windows journal removal target");
      const parent = path.win32.dirname(normalisedTarget);
      await recoverJournal(normalisedTarget);
      const [targetBefore, previousBefore] = await Promise.all([
        inspectJournalEntry(normalisedTarget),
        inspectJournalEntry(`${normalisedTarget}.previous`),
      ]);
      if (previousBefore.status !== "missing") {
        throw new Error("Reserved Windows journal .previous sidecar is occupied; refusing to adopt or delete it.");
      }
      await run([
        "remove-journal", "--parent", parent, "--target", path.win32.basename(normalisedTarget),
        ...expectedJournalArguments("target", targetBefore),
        ...expectedJournalArguments("previous", previousBefore),
      ], "journal-removed");
    },
    async renameDirectory({ destination, expectedNativeIdentity, source }) {
      const names = sameParentEntries(source, destination, "Windows directory rename");
      await run([
        "rename", "--parent", names.parent, "--source", names.firstName,
        "--destination", names.secondName, "--expected", requireIdentity(expectedNativeIdentity),
      ], "renamed");
    },
  };
}
