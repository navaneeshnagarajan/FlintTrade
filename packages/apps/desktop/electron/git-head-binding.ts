import path from "node:path";

import type {
  BootstrapDependencies,
  FileSystemDirectoryMetadata,
  FileSystemFileIdentity,
} from "./bootstrap";

const COMMIT_PATTERN = /^[0-9a-f]{40}$/;
const SAFE_BRANCH_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$/;
const MAX_HEAD_BYTES = 256;
const MAX_LOOSE_REF_BYTES = 64;

export type GitHeadBindingFileSystem = Pick<
  BootstrapDependencies["fileSystem"],
  | "directoryMetadata"
  | "existsNoFollow"
  | "fileIdentity"
  | "readTextNoFollow"
  | "realpath"
>;

export interface GitHeadBindingRequest {
  branch: string;
  fileSystem: GitHeadBindingFileSystem;
  gitPath: string;
  platform: NodeJS.Platform;
  selectedRevision: string;
}

interface BoundDirectory {
  canonicalPath: string;
  metadata: FileSystemDirectoryMetadata;
  requestedPath: string;
}

interface BoundFile {
  canonicalPath: string;
  content: string;
  identity: FileSystemFileIdentity;
  requestedPath: string;
}

export interface GitHeadBinding {
  gitDirectory: BoundDirectory;
  head: BoundFile;
  kind: "attached" | "detached";
  looseReference: BoundFile | null;
  reference: string | null;
  referenceDirectories: readonly BoundDirectory[];
  revision: string;
}

function samePath(left: string, right: string, platform: NodeJS.Platform): boolean {
  return platform === "win32" ? left.toLowerCase() === right.toLowerCase() : left === right;
}

function sameDirectoryMetadata(
  left: FileSystemDirectoryMetadata,
  right: FileSystemDirectoryMetadata,
): boolean {
  return (
    left.dev === right.dev &&
    left.ino === right.ino &&
    left.ctimeMs === right.ctimeMs &&
    left.mtimeMs === right.mtimeMs &&
    left.size === right.size
  );
}

function sameFileIdentity(left: FileSystemFileIdentity, right: FileSystemFileIdentity): boolean {
  return (
    left.dev === right.dev &&
    left.ino === right.ino &&
    left.ctimeMs === right.ctimeMs &&
    left.mtimeMs === right.mtimeMs &&
    left.size === right.size
  );
}

function requireExactRevision(value: string, label: string): string {
  if (!COMMIT_PATTERN.test(value)) {
    throw new Error(`${label} must be one exact lowercase 40-hex Git revision.`);
  }
  return value;
}

function requireSafeBranch(value: string): string[] {
  const components = value.split("/");
  if (
    !SAFE_BRANCH_PATTERN.test(value) ||
    value.includes("..") ||
    value.includes("//") ||
    value.includes("@{") ||
    value.endsWith(".") ||
    value.endsWith("/") ||
    components.some(
      (component) =>
        component === "" ||
        component.startsWith(".") ||
        component.toLowerCase().endsWith(".lock"),
    )
  ) {
    throw new Error("The configured source branch is not a safe exact Git branch.");
  }
  return components;
}

function requireExactGitPath(gitPath: string): void {
  if (
    !path.isAbsolute(gitPath) ||
    gitPath !== path.resolve(gitPath) ||
    path.basename(gitPath) !== ".git"
  ) {
    throw new Error("Git HEAD binding requires an exact absolute checkout .git path.");
  }
}

async function captureDirectory(
  fileSystem: GitHeadBindingFileSystem,
  requestedPath: string,
  expectedCanonicalPath: string,
  platform: NodeJS.Platform,
  label: string,
): Promise<BoundDirectory> {
  const initialMetadata = await fileSystem.directoryMetadata(requestedPath);
  const initialCanonicalPath = await fileSystem.realpath(requestedPath);
  const finalMetadata = await fileSystem.directoryMetadata(requestedPath);
  const finalCanonicalPath = await fileSystem.realpath(requestedPath);
  if (
    !samePath(initialCanonicalPath, expectedCanonicalPath, platform) ||
    !samePath(finalCanonicalPath, expectedCanonicalPath, platform) ||
    !sameDirectoryMetadata(initialMetadata, finalMetadata)
  ) {
    throw new Error(`${label} is symbolic, aliased or changed during canonical inspection.`);
  }
  return {
    canonicalPath: initialCanonicalPath,
    metadata: initialMetadata,
    requestedPath,
  };
}

async function captureFile(
  fileSystem: GitHeadBindingFileSystem,
  requestedPath: string,
  expectedCanonicalPath: string,
  platform: NodeJS.Platform,
  maxBytes: number,
  label: string,
): Promise<BoundFile> {
  const initialIdentity = await fileSystem.fileIdentity(requestedPath);
  if (initialIdentity.size > maxBytes) {
    throw new Error(`${label} is oversized and cannot be an exact Git metadata file.`);
  }
  const initialCanonicalPath = await fileSystem.realpath(requestedPath);
  const content = await fileSystem.readTextNoFollow(requestedPath);
  const finalIdentity = await fileSystem.fileIdentity(requestedPath);
  const finalCanonicalPath = await fileSystem.realpath(requestedPath);
  if (
    !samePath(initialCanonicalPath, expectedCanonicalPath, platform) ||
    !samePath(finalCanonicalPath, expectedCanonicalPath, platform) ||
    !sameFileIdentity(initialIdentity, finalIdentity) ||
    Buffer.byteLength(content, "utf8") !== initialIdentity.size
  ) {
    throw new Error(`${label} is symbolic, aliased or changed during no-follow inspection.`);
  }
  return {
    canonicalPath: initialCanonicalPath,
    content,
    identity: initialIdentity,
    requestedPath,
  };
}

async function assertDirectoryStable(
  request: GitHeadBindingRequest,
  proof: BoundDirectory,
  label: string,
): Promise<void> {
  const current = await captureDirectory(
    request.fileSystem,
    proof.requestedPath,
    proof.canonicalPath,
    request.platform,
    label,
  );
  if (!sameDirectoryMetadata(proof.metadata, current.metadata)) {
    throw new Error(`${label} identity changed during Git HEAD inspection.`);
  }
}

async function assertFileStable(
  request: GitHeadBindingRequest,
  proof: BoundFile,
  maxBytes: number,
  label: string,
): Promise<void> {
  const current = await captureFile(
    request.fileSystem,
    proof.requestedPath,
    proof.canonicalPath,
    request.platform,
    maxBytes,
    label,
  );
  if (!sameFileIdentity(proof.identity, current.identity) || proof.content !== current.content) {
    throw new Error(`${label} identity or content changed during Git HEAD inspection.`);
  }
}

async function assertCapturedBindingStable(
  request: GitHeadBindingRequest,
  binding: GitHeadBinding,
): Promise<void> {
  await assertDirectoryStable(request, binding.gitDirectory, "The checkout .git directory");
  for (const directory of binding.referenceDirectories) {
    await assertDirectoryStable(request, directory, "A checkout loose-ref directory");
  }
  await assertFileStable(request, binding.head, MAX_HEAD_BYTES, "The checkout HEAD file");
  if (binding.looseReference) {
    await assertFileStable(
      request,
      binding.looseReference,
      MAX_LOOSE_REF_BYTES,
      "The checkout loose branch ref",
    );
  }
}

function sameDirectoryProof(
  left: BoundDirectory,
  right: BoundDirectory,
  platform: NodeJS.Platform,
): boolean {
  return (
    samePath(left.requestedPath, right.requestedPath, platform) &&
    samePath(left.canonicalPath, right.canonicalPath, platform) &&
    sameDirectoryMetadata(left.metadata, right.metadata)
  );
}

function sameFileProof(left: BoundFile, right: BoundFile, platform: NodeJS.Platform): boolean {
  return (
    samePath(left.requestedPath, right.requestedPath, platform) &&
    samePath(left.canonicalPath, right.canonicalPath, platform) &&
    sameFileIdentity(left.identity, right.identity) &&
    left.content === right.content
  );
}

export async function captureGitHeadBinding(
  request: GitHeadBindingRequest,
): Promise<GitHeadBinding> {
  requireExactGitPath(request.gitPath);
  const branchComponents = requireSafeBranch(request.branch);
  const selectedRevision = requireExactRevision(
    request.selectedRevision,
    "The selected Git revision",
  );
  const canonicalCheckout = await request.fileSystem.realpath(path.dirname(request.gitPath));
  const gitDirectory = await captureDirectory(
    request.fileSystem,
    request.gitPath,
    path.join(canonicalCheckout, ".git"),
    request.platform,
    "The checkout .git directory",
  );
  const headPath = path.join(request.gitPath, "HEAD");
  const head = await captureFile(
    request.fileSystem,
    headPath,
    path.join(gitDirectory.canonicalPath, "HEAD"),
    request.platform,
    MAX_HEAD_BYTES,
    "The checkout HEAD file",
  );
  const expectedReference = `refs/heads/${request.branch}`;
  const expectedAttachedContent = `ref: ${expectedReference}\n`;

  let binding: GitHeadBinding;
  if (head.content.startsWith("ref: ")) {
    if (head.content !== expectedAttachedContent) {
      throw new Error("The checkout HEAD does not name the exact configured source branch.");
    }
    const referenceDirectories: BoundDirectory[] = [];
    let requestedDirectory = request.gitPath;
    let canonicalDirectory = gitDirectory.canonicalPath;
    for (const component of ["refs", "heads", ...branchComponents.slice(0, -1)]) {
      requestedDirectory = path.join(requestedDirectory, component);
      canonicalDirectory = path.join(canonicalDirectory, component);
      referenceDirectories.push(await captureDirectory(
        request.fileSystem,
        requestedDirectory,
        canonicalDirectory,
        request.platform,
        "A checkout loose-ref directory",
      ));
    }
    const referencePath = path.join(request.gitPath, "refs", "heads", ...branchComponents);
    if (!(await request.fileSystem.existsNoFollow(referencePath))) {
      throw new Error("The configured branch requires an exact loose ref; packed-only refs are unsupported.");
    }
    const looseReference = await captureFile(
      request.fileSystem,
      referencePath,
      path.join(gitDirectory.canonicalPath, "refs", "heads", ...branchComponents),
      request.platform,
      MAX_LOOSE_REF_BYTES,
      "The checkout loose branch ref",
    );
    if (!COMMIT_PATTERN.test(looseReference.content.slice(0, -1)) || !looseReference.content.endsWith("\n")) {
      throw new Error("The checkout loose branch ref must contain one exact lowercase Git revision and newline.");
    }
    if (looseReference.content !== `${selectedRevision}\n`) {
      throw new Error("The checkout loose branch ref does not match the selected revision.");
    }
    binding = {
      gitDirectory,
      head,
      kind: "attached",
      looseReference,
      reference: expectedReference,
      referenceDirectories,
      revision: selectedRevision,
    };
  } else {
    if (!COMMIT_PATTERN.test(head.content.slice(0, -1)) || !head.content.endsWith("\n")) {
      throw new Error("The checkout detached HEAD must contain one exact lowercase Git revision and newline.");
    }
    if (head.content !== `${selectedRevision}\n`) {
      throw new Error("The checkout detached HEAD does not match the selected revision.");
    }
    binding = {
      gitDirectory,
      head,
      kind: "detached",
      looseReference: null,
      reference: null,
      referenceDirectories: [],
      revision: selectedRevision,
    };
  }

  await assertCapturedBindingStable(request, binding);
  return binding;
}

export async function assertGitHeadBindingStable(
  request: GitHeadBindingRequest,
  binding: GitHeadBinding,
): Promise<void> {
  if (request.selectedRevision !== binding.revision) {
    throw new Error("The selected Git revision changed before final HEAD proof.");
  }
  const current = await captureGitHeadBinding(request);
  const sameDirectories =
    binding.referenceDirectories.length === current.referenceDirectories.length &&
    binding.referenceDirectories.every((directory, index) =>
      sameDirectoryProof(directory, current.referenceDirectories[index]!, request.platform),
    );
  if (
    binding.kind !== current.kind ||
    binding.reference !== current.reference ||
    binding.revision !== current.revision ||
    !sameDirectoryProof(binding.gitDirectory, current.gitDirectory, request.platform) ||
    !sameFileProof(binding.head, current.head, request.platform) ||
    !sameDirectories ||
    (binding.looseReference === null) !== (current.looseReference === null) ||
    (binding.looseReference && current.looseReference &&
      !sameFileProof(binding.looseReference, current.looseReference, request.platform))
  ) {
    throw new Error("The Git HEAD or loose-ref binding changed during hardened inspection.");
  }
}
