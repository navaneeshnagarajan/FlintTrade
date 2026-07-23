import path from "node:path";

import type { Bundle, VerifyOptions } from "sigstore";
import { compress } from "snappyjs";
import { describe, expect, it, vi } from "vitest";

import { createGithubShellAttestationVerifier, sigstorePolicyForRelease } from "./shell-attestation";

const TAG = "v0.6.0-beta.14";
const NAME = "FlintTrade-0.6.0-beta.14-mac-universal.dmg";
const HASH = "0123456789abcdef".repeat(4);
const DIGEST = `sha256:${HASH}`;
const INVOCATION = "https://github.com/navaneeshnagarajan/FlintTrade/actions/runs/123/attempts/1";
const API_URL =
  `https://api.github.com/repos/navaneeshnagarajan/FlintTrade/attestations/${encodeURIComponent(DIGEST)}` +
  "?per_page=100&predicate_type=provenance";
const BUNDLE_URL =
  "https://tmaproduction.blob.core.windows.net/attestations/1182820588/2026/07/22/12345.json.sn" +
  "?se=2026-07-22T17%3A00%3A00Z&sig=YWJjZGVmZ2hpamtsbW5vcA%3D%3D&ske=2026-07-22T18%3A00%3A00Z" +
  "&skoid=322a4be5-8e0b-4548-9b48-4e436a2c7c75&sks=b&skt=2026-07-22T15%3A00%3A00Z" +
  "&sktid=398a6654-997b-47e9-b12b-9515b896b4de&skv=2026-06-06" +
  "&sp=r&spr=https&sr=b&st=2026-07-22T15%3A00%3A00Z&sv=2026-06-06";

type Fetcher = (input: string, init: RequestInit) => Promise<Response>;
type BundleVerifier = (bundle: Bundle, options: VerifyOptions) => Promise<unknown>;

function der(value: string): string {
  return String.fromCharCode(0x0c, value.length) + value;
}

function statement(overrides: Partial<{ commit: string; name: string; repositoryId: string; ref: string }> = {}) {
  const ref = overrides.ref ?? `refs/tags/${TAG}`;
  const names = [
    overrides.name ?? NAME,
    "FlintTrade-0.6.0-beta.14-win-x64.exe",
    "FlintTrade-0.6.0-beta.14-linux-x64.AppImage",
    "FlintTrade-0.6.0-beta.14-linux-arm64.AppImage",
    "SHA256SUMS.txt",
  ];
  return {
    _type: "https://in-toto.io/Statement/v1",
    subject: names.map((name, index) => ({
      name,
      digest: { sha256: index === 0 ? HASH : String(index).repeat(64) },
    })),
    predicateType: "https://slsa.dev/provenance/v1",
    predicate: {
      buildDefinition: {
        buildType: "https://actions.github.io/buildtypes/workflow/v1",
        externalParameters: {
          workflow: {
            ref,
            repository: "https://github.com/navaneeshnagarajan/FlintTrade",
            path: ".github/workflows/desktop-release.yml",
          },
        },
        internalParameters: {
          github: {
            event_name: "workflow_dispatch",
            repository_id: overrides.repositoryId ?? "1182820588",
            repository_owner_id: "259833042",
            runner_environment: "github-hosted",
          },
        },
        resolvedDependencies: [{
          uri: `git+https://github.com/navaneeshnagarajan/FlintTrade@${ref}`,
          digest: { gitCommit: overrides.commit ?? "a".repeat(40) },
        }],
      },
      runDetails: {
        builder: {
          id:
            "https://github.com/navaneeshnagarajan/FlintTrade/.github/workflows/desktop-release.yml@" + ref,
        },
        metadata: {
          invocationId: INVOCATION,
        },
      },
    },
  };
}

function bundle(payload = statement()) {
  return {
    mediaType: "application/vnd.dev.sigstore.bundle.v0.3+json",
    verificationMaterial: {
      certificate: { rawBytes: "certificate" },
      tlogEntries: [{}],
      timestampVerificationData: {},
    },
    dsseEnvelope: {
      payload: Buffer.from(JSON.stringify(payload)).toString("base64"),
      payloadType: "application/vnd.in-toto+json",
      signatures: [{ sig: "signature" }],
    },
  };
}

function response(body: BodyInit, url: string, contentType: string, extraHeaders: HeadersInit = {}): Response {
  const result = new Response(body, {
    headers: { "content-type": contentType, ...extraHeaders },
    status: 200,
  });
  Object.defineProperty(result, "url", { value: url });
  return result;
}

function metadata(overrides: Partial<{ bundleUrl: string; repositoryId: number }> = {}): Response {
  return response(JSON.stringify({
    attestations: [{
      repository_id: overrides.repositoryId ?? 1_182_820_588,
      bundle_url: overrides.bundleUrl ?? BUNDLE_URL,
      initiator: "user",
    }],
  }), API_URL, "application/json; charset=utf-8");
}

function compressedBundle(payload = statement()): Response {
  return response(compress(Buffer.from(JSON.stringify(bundle(payload)))), BUNDLE_URL, "application/x-snappy");
}

function verifier(
  fetcher: ReturnType<typeof vi.fn<Fetcher>>,
  verifyBundle: ReturnType<typeof vi.fn<BundleVerifier>> = vi.fn<BundleVerifier>(async () => undefined),
  timeoutMs = 1_000,
) {
  return {
    subject: createGithubShellAttestationVerifier({
      cachePath: path.resolve("/private/sigstore"),
      fetcher,
      now: () => Date.parse("2026-07-22T16:00:00Z"),
      timeoutMs,
      verifyBundle,
    }),
    verifyBundle,
  };
}

function input() {
  return {
    assetName: NAME,
    digest: DIGEST,
    releaseTag: TAG,
    signal: new AbortController().signal,
  };
}

describe("GitHub shell artifact attestation", () => {
  it("cryptographically verifies and independently binds the exact installer and release workflow", async () => {
    const fetcher = vi.fn<Fetcher>()
      .mockResolvedValueOnce(metadata())
      .mockResolvedValueOnce(compressedBundle());
    const test = verifier(fetcher);

    await expect(test.subject.verify(input())).resolves.toEqual({
      assetName: NAME,
      digest: DIGEST,
      releaseTag: TAG,
    });

    expect(fetcher).toHaveBeenNthCalledWith(1, API_URL, expect.objectContaining({
      headers: {
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
      },
      redirect: "error",
    }));
    expect(fetcher).toHaveBeenNthCalledWith(2, BUNDLE_URL, expect.objectContaining({
      headers: { Accept: "application/x-snappy" },
      redirect: "error",
    }));
    expect(test.verifyBundle).toHaveBeenCalledWith(expect.objectContaining({
      mediaType: "application/vnd.dev.sigstore.bundle.v0.3+json",
    }), expect.objectContaining({
      certificateIdentityURI:
        "^https://github\\.com/navaneeshnagarajan/FlintTrade/\\.github/workflows/desktop-release\\.yml@refs/tags/v0\\.6\\.0-beta\\.14$",
      certificateIssuer: "https://token.actions.githubusercontent.com",
      ctLogThreshold: 1,
      tlogThreshold: 1,
    }));
    expect(test.verifyBundle.mock.calls[0]?.[1]?.certificateOIDs).toMatchObject({
      "1.3.6.1.4.1.57264.1.2": "workflow_dispatch",
      "1.3.6.1.4.1.57264.1.3": "a".repeat(40),
      "1.3.6.1.4.1.57264.1.5": "navaneeshnagarajan/FlintTrade",
      "1.3.6.1.4.1.57264.1.6": "refs/tags/v0.6.0-beta.14",
      "1.3.6.1.4.1.57264.1.10": der("a".repeat(40)),
      "1.3.6.1.4.1.57264.1.13": der("a".repeat(40)),
      "1.3.6.1.4.1.57264.1.15": der("1182820588"),
      "1.3.6.1.4.1.57264.1.17": der("259833042"),
      "1.3.6.1.4.1.57264.1.19": der("a".repeat(40)),
      "1.3.6.1.4.1.57264.1.21": der(INVOCATION),
      "1.3.6.1.4.1.57264.1.22": der("public"),
    });
    const verifiedStatement = statement();
    expect(verifiedStatement.subject.map((subject) => subject.name)).toEqual([
      NAME,
      "FlintTrade-0.6.0-beta.14-win-x64.exe",
      "FlintTrade-0.6.0-beta.14-linux-x64.AppImage",
      "FlintTrade-0.6.0-beta.14-linux-arm64.AppImage",
      "SHA256SUMS.txt",
    ]);
  });

  it("fails closed when Sigstore rejects the certificate, transparency log, or signature", async () => {
    const fetcher = vi.fn<Fetcher>()
      .mockResolvedValueOnce(metadata())
      .mockResolvedValueOnce(compressedBundle());
    const test = verifier(fetcher, vi.fn<BundleVerifier>(async () => { throw new Error("invalid Rekor proof"); }));

    await expect(test.subject.verify(input())).rejects.toThrow(/no cryptographically valid/i);
  });

  it("binds the signed source commit to the certificate workflow and source digest OIDs", async () => {
    const payload = statement({ commit: "b".repeat(40) });
    const fetcher = vi.fn<Fetcher>()
      .mockResolvedValueOnce(metadata())
      .mockResolvedValueOnce(compressedBundle(payload));
    const verifyBundle = vi.fn<BundleVerifier>(async (_bundle, policy) => {
      if (policy.certificateOIDs?.["1.3.6.1.4.1.57264.1.13"] !== der("a".repeat(40))) {
        throw new Error("certificate source digest does not match statement");
      }
    });
    const test = verifier(fetcher, verifyBundle);

    await expect(test.subject.verify(input())).rejects.toThrow(/no cryptographically valid/i);
    expect(verifyBundle.mock.calls[0]?.[1]?.certificateOIDs).toMatchObject({
      "1.3.6.1.4.1.57264.1.3": "b".repeat(40),
      "1.3.6.1.4.1.57264.1.10": der("b".repeat(40)),
      "1.3.6.1.4.1.57264.1.13": der("b".repeat(40)),
      "1.3.6.1.4.1.57264.1.19": der("b".repeat(40)),
    });
  });

  it("rejects a cryptographically valid statement for another asset, repository id, or tag", async () => {
    for (const payload of [
      statement({ name: "FlintTrade-0.6.0-beta.14-win-x64.exe" }),
      statement({ repositoryId: "42" }),
      statement({ ref: "refs/tags/v9.9.9" }),
    ]) {
      const fetcher = vi.fn<Fetcher>()
        .mockResolvedValueOnce(metadata())
        .mockResolvedValueOnce(compressedBundle(payload));
      const test = verifier(fetcher);
      await expect(test.subject.verify(input())).rejects.toThrow(/no cryptographically valid/i);
      expect(test.verifyBundle).toHaveBeenCalledOnce();
    }
  });

  it("rejects duplicate, missing, or extra subjects from the canonical five-asset release", async () => {
    const valid = statement();
    const subjectSets = [
      { ...valid, subject: [...valid.subject.slice(0, 4), valid.subject[0]!] },
      { ...valid, subject: valid.subject.slice(0, 4) },
      { ...valid, subject: [...valid.subject, { name: "unexpected", digest: { sha256: "f".repeat(64) } }] },
    ];
    for (const payload of subjectSets) {
      const fetcher = vi.fn<Fetcher>()
        .mockResolvedValueOnce(metadata())
        .mockResolvedValueOnce(compressedBundle(payload));
      const test = verifier(fetcher);
      await expect(test.subject.verify(input())).rejects.toThrow(/no cryptographically valid/i);
      expect(test.verifyBundle).toHaveBeenCalledOnce();
    }
  });

  it("rejects off-repository metadata, off-host bundles, pagination, and oversized responses before verification", async () => {
    const cases: Response[] = [
      metadata({ repositoryId: 42 }),
      metadata({ bundleUrl: BUNDLE_URL.replace("tmaproduction.blob.core.windows.net", "attacker.example") }),
      response(JSON.stringify({ attestations: [] }), API_URL, "application/json", { link: "<next>; rel=next" }),
      response("{}", API_URL, "application/json", { "content-length": String(256 * 1024 + 1) }),
    ];
    for (const metadataResponse of cases) {
      const test = verifier(vi.fn<Fetcher>(async () => metadataResponse));
      await expect(test.subject.verify(input())).rejects.toThrow();
      expect(test.verifyBundle).not.toHaveBeenCalled();
    }
  });

  it("keeps the attestation deadline active through a never-closing metadata body", async () => {
    vi.useFakeTimers();
    try {
      const stream = new ReadableStream<Uint8Array>({
        cancel() {
          return new Promise<void>(() => undefined);
        },
        pull() {
          return new Promise<void>(() => undefined);
        },
      }, { highWaterMark: 0 });
      const fetcher = vi.fn<Fetcher>(async () => response(stream, API_URL, "application/json"));
      const pending = verifier(fetcher, undefined, 25).subject.verify(input());
      const rejected = expect(pending).rejects.toThrow(/timed out/i);

      await vi.advanceTimersByTimeAsync(26);
      await rejected;
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps outer cancellation active through a never-closing attestation bundle body", async () => {
    let bodyStarted!: () => void;
    const started = new Promise<void>((resolve) => { bodyStarted = resolve; });
    const stream = new ReadableStream<Uint8Array>({
      cancel() {
        return new Promise<void>(() => undefined);
      },
      pull() {
        bodyStarted();
        return new Promise<void>(() => undefined);
      },
    }, { highWaterMark: 0 });
    const fetcher = vi.fn<Fetcher>()
      .mockResolvedValueOnce(metadata())
      .mockResolvedValueOnce(response(stream, BUNDLE_URL, "application/x-snappy"));
    const controller = new AbortController();
    const pending = verifier(fetcher).subject.verify({ ...input(), signal: controller.signal });

    await started;
    controller.abort(new DOMException("quit requested", "AbortError"));
    await expect(pending).rejects.toThrow(/quit requested/i);
  });

  it("abandons a never-settling Sigstore verifier when outer shutdown aborts", async () => {
    let verificationStarted!: () => void;
    const started = new Promise<void>((resolve) => { verificationStarted = resolve; });
    const verifyBundle = vi.fn<BundleVerifier>(async () => {
      verificationStarted();
      return await new Promise<never>(() => undefined);
    });
    const fetcher = vi.fn<Fetcher>()
      .mockResolvedValueOnce(metadata())
      .mockResolvedValueOnce(compressedBundle());
    const controller = new AbortController();
    const pending = verifier(fetcher, verifyBundle).subject.verify({ ...input(), signal: controller.signal });

    await started;
    controller.abort(new DOMException("quit requested", "AbortError"));
    await expect(pending).rejects.toThrow(/quit requested/i);
    expect(verifyBundle).toHaveBeenCalledOnce();
  });

  it("requires exact lower-case digest, release tag, asset name, cache path, and timeout", async () => {
    expect(() => sigstorePolicyForRelease("latest", "a".repeat(40), INVOCATION, "/cache")).toThrow(/valid tag/i);
    expect(() => sigstorePolicyForRelease(TAG, "invalid", INVOCATION, "/cache")).toThrow(/source commit/i);
    expect(() => sigstorePolicyForRelease(TAG, "a".repeat(40), "invalid", "/cache")).toThrow(/invocation/i);
    expect(() => sigstorePolicyForRelease(TAG, "a".repeat(40), INVOCATION, "relative")).toThrow(/absolute cache/i);
    expect(() => createGithubShellAttestationVerifier({
      cachePath: "/cache",
      fetcher: vi.fn<Fetcher>(),
      timeoutMs: 0,
    })).toThrow(/between 1 and 60000/i);

    const test = verifier(vi.fn<Fetcher>());
    await expect(test.subject.verify({ ...input(), digest: `sha256:${HASH.toUpperCase()}` })).rejects.toThrow(
      /installer identity/i,
    );
    await expect(test.subject.verify({ ...input(), assetName: `../${NAME}` })).rejects.toThrow(/installer identity/i);
  });
});
