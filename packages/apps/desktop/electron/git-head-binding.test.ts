import { mkdir, mkdtemp, realpath, rename, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { createNodeBootstrapDependencies } from "./bootstrap-io";
import {
  assertGitHeadBindingStable,
  captureGitHeadBinding,
  type GitHeadBindingRequest,
} from "./git-head-binding";

const revision = "a".repeat(40);
const otherRevision = "b".repeat(40);
const temporaryRoots: string[] = [];
let replacementSequence = 0;

afterEach(async () => {
  await Promise.all(temporaryRoots.splice(0).map((root) => rm(root, { force: true, recursive: true })));
});

interface HeadFixture {
  gitPath: string;
  headPath: string;
  refPath: string;
  request: GitHeadBindingRequest;
  root: string;
}

async function createFixture(options: {
  branch?: string;
  headContent?: string;
  includeLooseRef?: boolean;
  refContent?: string;
} = {}): Promise<HeadFixture> {
  const branch = options.branch ?? "main";
  const root = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-git-head-binding-")));
  temporaryRoots.push(root);
  const gitPath = path.join(root, "checkout", ".git");
  const refPath = path.join(gitPath, "refs", "heads", ...branch.split("/"));
  const headPath = path.join(gitPath, "HEAD");
  await mkdir(path.dirname(refPath), { recursive: true });
  await writeFile(headPath, options.headContent ?? `ref: refs/heads/${branch}\n`);
  if (options.includeLooseRef ?? true) {
    await writeFile(refPath, options.refContent ?? `${revision}\n`);
  }
  const fileSystem = createNodeBootstrapDependencies(process.platform).fileSystem;
  return {
    gitPath,
    headPath,
    refPath,
    request: {
      branch,
      fileSystem,
      gitPath,
      platform: process.platform,
      selectedRevision: revision,
    },
    root,
  };
}

async function replaceFile(target: string, content: string): Promise<void> {
  replacementSequence += 1;
  const displaced = `${target}.displaced-${replacementSequence}`;
  const replacement = `${target}.replacement-${replacementSequence}`;
  await writeFile(replacement, content);
  await rename(target, displaced);
  await rename(replacement, target);
}

describe("Git HEAD binding", () => {
  it("binds an exact attached HEAD and a slash-separated loose branch ref", async () => {
    const test = await createFixture({ branch: "release/stable" });

    const binding = await captureGitHeadBinding(test.request);

    expect(binding).toMatchObject({
      kind: "attached",
      reference: "refs/heads/release/stable",
      revision,
    });
    await expect(assertGitHeadBindingStable(test.request, binding)).resolves.toBeUndefined();
  });

  it("binds an exact detached lowercase revision", async () => {
    const test = await createFixture({ headContent: `${revision}\n` });

    const binding = await captureGitHeadBinding(test.request);

    expect(binding).toMatchObject({ kind: "detached", reference: null, revision });
    await expect(assertGitHeadBindingStable(test.request, binding)).resolves.toBeUndefined();
  });

  it("rejects an attached HEAD for any branch other than the configured branch", async () => {
    const test = await createFixture({ headContent: "ref: refs/heads/other\n" });

    await expect(captureGitHeadBinding(test.request)).rejects.toThrow(/configured|exact.*branch|HEAD/i);
  });

  it("rejects a packed-only attached branch", async () => {
    const test = await createFixture({ includeLooseRef: false });
    await writeFile(path.join(test.gitPath, "packed-refs"), `${revision} refs/heads/main\n`);

    await expect(captureGitHeadBinding(test.request)).rejects.toThrow(/loose|packed/i);
  });

  it("rejects a loose ref whose exact revision differs from the selected revision", async () => {
    const test = await createFixture({ refContent: `${otherRevision}\n` });

    await expect(captureGitHeadBinding(test.request)).rejects.toThrow(/selected revision|match/i);
  });

  it("rejects a detached HEAD whose exact revision differs from the selected revision", async () => {
    const test = await createFixture({ headContent: `${otherRevision}\n` });

    await expect(captureGitHeadBinding(test.request)).rejects.toThrow(/selected revision|match/i);
  });

  it("detects a concurrent loose-ref replacement during capture", async () => {
    const test = await createFixture();
    const baseFileSystem = test.request.fileSystem;
    let armed = true;
    const request: GitHeadBindingRequest = {
      ...test.request,
      fileSystem: {
        ...baseFileSystem,
        async readTextNoFollow(target) {
          const content = await baseFileSystem.readTextNoFollow(target);
          if (armed && target === test.refPath) {
            armed = false;
            await replaceFile(target, `${otherRevision}\n`);
          }
          return content;
        },
      },
    };

    await expect(captureGitHeadBinding(request)).rejects.toThrow(/changed|identity|stable/i);
  });

  it("detects loose-ref replacement even when the original content is restored", async () => {
    const test = await createFixture();
    const binding = await captureGitHeadBinding(test.request);
    await replaceFile(test.refPath, `${otherRevision}\n`);
    await replaceFile(test.refPath, `${revision}\n`);

    await expect(assertGitHeadBindingStable(test.request, binding)).rejects.toThrow(
      /changed|identity|stable/i,
    );
  });

  it("detects an exact HEAD change after capture", async () => {
    const test = await createFixture();
    const binding = await captureGitHeadBinding(test.request);
    await replaceFile(test.headPath, `${otherRevision}\n`);

    await expect(assertGitHeadBindingStable(test.request, binding)).rejects.toThrow(
      /changed|identity|stable|HEAD/i,
    );
  });

  it("detects a direct .git ancestor rename-and-restore ABA after capture", async () => {
    const test = await createFixture();
    const binding = await captureGitHeadBinding(test.request);
    const displaced = `${test.gitPath}.displaced`;
    const replacement = `${test.gitPath}.replacement`;
    await rename(test.gitPath, displaced);
    await mkdir(test.gitPath);
    await rename(test.gitPath, replacement);
    await rename(displaced, test.gitPath);

    await expect(assertGitHeadBindingStable(test.request, binding)).rejects.toThrow(
      /changed|identity|stable|directory/i,
    );
  });

  it("rejects symbolic intermediate branch directories", async () => {
    const test = await createFixture({ branch: "release/stable", includeLooseRef: false });
    const releaseDirectory = path.join(test.gitPath, "refs", "heads", "release");
    const outside = path.join(test.root, "outside-release");
    await rm(releaseDirectory, { force: true, recursive: true });
    await mkdir(outside);
    await writeFile(path.join(outside, "stable"), `${revision}\n`);
    await symlink(outside, releaseDirectory, process.platform === "win32" ? "junction" : "dir");

    await expect(captureGitHeadBinding(test.request)).rejects.toThrow(/symbolic|canonical|directory/i);
  });

  it("rejects a symbolic loose-ref file", async () => {
    const test = await createFixture({ includeLooseRef: false });
    const outside = path.join(test.root, "outside-ref");
    await writeFile(outside, `${revision}\n`);
    await symlink(outside, test.refPath, "file");

    await expect(captureGitHeadBinding(test.request)).rejects.toThrow(/symbolic|canonical|regular file/i);
  });

  it.each([
    ["uppercase detached revision", `${revision.toUpperCase()}\n`],
    ["missing detached newline", revision],
    ["CRLF detached revision", `${revision}\r\n`],
    ["extra detached data", `${revision}\nextra\n`],
    ["inexact attached prefix", ` ref: refs/heads/main\n`],
    ["extra attached data", `ref: refs/heads/main\nextra\n`],
  ])("rejects malformed HEAD content: %s", async (_label, headContent) => {
    const test = await createFixture({ headContent });

    await expect(captureGitHeadBinding(test.request)).rejects.toThrow(/exact|HEAD|lowercase/i);
  });

  it.each([
    ["uppercase loose revision", `${revision.toUpperCase()}\n`],
    ["missing loose newline", revision],
    ["CRLF loose revision", `${revision}\r\n`],
    ["extra loose data", `${revision}\nextra\n`],
  ])("rejects malformed loose-ref content: %s", async (_label, refContent) => {
    const test = await createFixture({ refContent });

    await expect(captureGitHeadBinding(test.request)).rejects.toThrow(/exact|loose|lowercase|revision/i);
  });

  it.each([
    "feature//unsafe",
    "feature/../unsafe",
    "feature/.hidden",
    "feature/topic.lock/nested",
  ])("rejects an unsafe configured branch before resolving refs: %s", async (branch) => {
    const test = await createFixture();

    await expect(captureGitHeadBinding({ ...test.request, branch })).rejects.toThrow(/safe|branch/i);
  });
});
