import path from "node:path";

import { verify as verifySigstore, type Bundle, type VerifyOptions } from "sigstore";
import { uncompress } from "snappyjs";

import { fetchBoundedResponse, raceWithAbort, type FetchLike } from "./bounded-response";

const REPOSITORY = "navaneeshnagarajan/FlintTrade";
const REPOSITORY_ID = 1_182_820_588;
const REPOSITORY_OWNER_ID = 259_833_042;
const REPOSITORY_URL = `https://github.com/${REPOSITORY}`;
const WORKFLOW_PATH = ".github/workflows/desktop-release.yml";
const WORKFLOW_URI_PATH = `/${WORKFLOW_PATH}`;
const GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com";
const GITHUB_API_VERSION = "2026-03-10";
const ATTESTATION_API_PREFIX = `https://api.github.com/repos/${REPOSITORY}/attestations/`;
const ATTESTATION_BUNDLE_HOST = "tmaproduction.blob.core.windows.net";
const MAX_ATTESTATION_METADATA_BYTES = 256 * 1024;
const MAX_ATTESTATION_BUNDLE_BYTES = 2 * 1024 * 1024;
const MAX_ATTESTATIONS = 16;
const DEFAULT_TIMEOUT_MS = 10_000;
const SLSA_PREDICATE_TYPE = "https://slsa.dev/provenance/v1";
const SLSA_GITHUB_WORKFLOW_BUILD_TYPE =
  "https://actions.github.io/buildtypes/workflow/v1";

type SigstoreVerify = (bundle: Bundle, options: VerifyOptions) => Promise<unknown>;

export interface ShellAttestationInput {
  assetName: string;
  digest: string;
  releaseTag: string;
  signal: AbortSignal;
}

export interface VerifiedShellAttestation {
  assetName: string;
  digest: string;
  releaseTag: string;
}

export interface ShellAttestationVerifier {
  verify(input: ShellAttestationInput): Promise<VerifiedShellAttestation>;
}

export interface GithubShellAttestationVerifierOptions {
  cachePath: string;
  fetcher: FetchLike;
  now?: () => number;
  timeoutMs?: number;
  verifyBundle?: SigstoreVerify;
}

interface GithubAttestationMetadata {
  bundleUrl: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  return actual.length === expected.length && actual.every((key, index) => key === [...expected].sort()[index]);
}

function isSha256Digest(value: string): boolean {
  return /^sha256:[0-9a-f]{64}$/.test(value);
}

function isReleaseTag(value: string): boolean {
  return /^v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/.test(value);
}

function isAssetName(value: string, releaseTag: string): boolean {
  if (!value || value !== path.basename(value) || value.includes("/") || value.includes("\\")) return false;
  const escapedVersion = releaseTag.slice(1).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(
    `^FlintTrade-${escapedVersion}-(?:mac-universal\\.dmg|win-x64\\.exe|linux-(?:x64|arm64)\\.AppImage)$`,
  ).test(value);
}

function canonicalReleaseSubjectNames(releaseTag: string): readonly string[] {
  const version = releaseTag.slice(1);
  return [
    `FlintTrade-${version}-mac-universal.dmg`,
    `FlintTrade-${version}-win-x64.exe`,
    `FlintTrade-${version}-linux-x64.AppImage`,
    `FlintTrade-${version}-linux-arm64.AppImage`,
    "SHA256SUMS.txt",
  ];
}

function attestationApiUrl(digest: string): string {
  return `${ATTESTATION_API_PREFIX}${encodeURIComponent(digest)}?per_page=100&predicate_type=provenance`;
}

function isExactAttestationApiUrl(value: string, digest: string): boolean {
  try {
    const url = new URL(value);
    return value === attestationApiUrl(digest) &&
      url.href === attestationApiUrl(digest) &&
      url.protocol === "https:" &&
      url.hostname === "api.github.com" &&
      url.port === "" &&
      url.username === "" &&
      url.password === "" &&
      url.hash === "";
  } catch {
    return false;
  }
}

function hasOneQueryValue(url: URL, name: string): boolean {
  return url.searchParams.getAll(name).length === 1 && Boolean(url.searchParams.get(name));
}

function isTrustedBundleUrl(value: string, now: number): boolean {
  if (value.length > 8_192) return false;
  try {
    const url = new URL(value);
    const allowedParameters = new Set([
      "se",
      "sig",
      "ske",
      "skoid",
      "sks",
      "skt",
      "sktid",
      "skv",
      "sp",
      "spr",
      "sr",
      "st",
      "sv",
    ]);
    if (
      url.protocol !== "https:" ||
      url.hostname !== ATTESTATION_BUNDLE_HOST ||
      url.port !== "" ||
      url.username !== "" ||
      url.password !== "" ||
      url.hash !== "" ||
      !new RegExp(`^/attestations/${REPOSITORY_ID}/\\d{4}/\\d{2}/\\d{2}/[A-Za-z0-9._-]{1,160}\\.json\\.sn$`).test(
        url.pathname,
      ) ||
      [...url.searchParams.keys()].some((name) => !allowedParameters.has(name)) ||
      [...allowedParameters].some((name) => !hasOneQueryValue(url, name)) ||
      url.searchParams.get("sp") !== "r" ||
      url.searchParams.get("spr") !== "https" ||
      url.searchParams.get("sr") !== "b" ||
      url.searchParams.get("sks") !== "b"
    ) {
      return false;
    }
    const timestampNames = ["se", "ske", "skt", "st"] as const;
    const timestamps = timestampNames.map((name) => url.searchParams.get(name)!);
    const parsedTimestamps = timestamps.map((entry) => Date.parse(entry));
    const [expires, keyExpires, keyStarts, starts] = parsedTimestamps;
    const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
    return [...url.searchParams.values()].every((entry) => entry.length <= 1_024) &&
      timestamps.every((entry) => /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(entry)) &&
      parsedTimestamps.every(Number.isFinite) &&
      starts! <= now + 5 * 60_000 &&
      now <= expires! &&
      keyStarts! <= starts! &&
      expires! <= keyExpires! &&
      expires! - starts! <= 24 * 60 * 60_000 &&
      uuidPattern.test(url.searchParams.get("skoid")!) &&
      uuidPattern.test(url.searchParams.get("sktid")!) &&
      /^[A-Za-z0-9+/]{8,1022}={0,2}$/.test(url.searchParams.get("sig")!) &&
      /^\d{4}-\d{2}-\d{2}$/.test(url.searchParams.get("skv")!) &&
      /^\d{4}-\d{2}-\d{2}$/.test(url.searchParams.get("sv")!);
  } catch {
    return false;
  }
}

function parseMetadata(value: unknown, now: number): readonly GithubAttestationMetadata[] {
  if (!isRecord(value) || !exactKeys(value, ["attestations"]) || !Array.isArray(value.attestations)) {
    throw new Error("The GitHub attestation response had an invalid shape.");
  }
  if (value.attestations.length === 0 || value.attestations.length > MAX_ATTESTATIONS) {
    throw new Error("The GitHub attestation response had an invalid attestation count.");
  }
  return value.attestations.map((entry) => {
    if (
      !isRecord(entry) ||
      !exactKeys(entry, ["bundle_url", "initiator", "repository_id"]) ||
      entry.repository_id !== REPOSITORY_ID ||
      typeof entry.bundle_url !== "string" ||
      !isTrustedBundleUrl(entry.bundle_url, now) ||
      typeof entry.initiator !== "string" ||
      entry.initiator.length === 0 ||
      entry.initiator.length > 256
    ) {
      throw new Error("The GitHub attestation response contained invalid repository metadata.");
    }
    return { bundleUrl: entry.bundle_url };
  });
}

function declaredSnappyLength(input: Uint8Array): number {
  let result = 0;
  let shift = 0;
  for (let index = 0; index < Math.min(input.length, 5); index += 1) {
    const byte = input[index]!;
    result += (byte & 0x7f) * (2 ** shift);
    if ((byte & 0x80) === 0) return result;
    shift += 7;
  }
  throw new Error("The GitHub attestation bundle had an invalid Snappy length.");
}

function decodeSnappyJson(input: Uint8Array): unknown {
  const declaredLength = declaredSnappyLength(input);
  if (declaredLength <= 0 || declaredLength > MAX_ATTESTATION_BUNDLE_BYTES) {
    throw new Error("The GitHub attestation bundle exceeded its decompressed size limit.");
  }
  let output: Uint8Array;
  try {
    const decompressed = uncompress(input);
    output = decompressed instanceof Uint8Array ? decompressed : new Uint8Array(decompressed);
  } catch (error) {
    throw new Error("The GitHub attestation bundle was not valid Snappy data.", { cause: error });
  }
  if (output.byteLength !== declaredLength) {
    throw new Error("The GitHub attestation bundle decompressed to an unexpected size.");
  }
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(output)) as unknown;
  } catch (error) {
    throw new Error("The GitHub attestation bundle was not valid UTF-8 JSON.", { cause: error });
  }
}

function requireSigstoreBundle(value: unknown): Bundle {
  if (
    !isRecord(value) ||
    value.mediaType !== "application/vnd.dev.sigstore.bundle.v0.3+json" ||
    !isRecord(value.verificationMaterial) ||
    !isRecord(value.dsseEnvelope) ||
    "messageSignature" in value ||
    !Array.isArray(value.verificationMaterial.tlogEntries) ||
    value.verificationMaterial.tlogEntries.length === 0 ||
    !isRecord(value.verificationMaterial.certificate) ||
    typeof value.verificationMaterial.certificate.rawBytes !== "string" ||
    value.verificationMaterial.certificate.rawBytes.length === 0 ||
    typeof value.dsseEnvelope.payload !== "string" ||
    value.dsseEnvelope.payloadType !== "application/vnd.in-toto+json" ||
    !Array.isArray(value.dsseEnvelope.signatures) ||
    value.dsseEnvelope.signatures.length !== 1
  ) {
    throw new Error("The GitHub attestation was not a supported Sigstore DSSE bundle.");
  }
  return value as Bundle;
}

function strictBase64(value: string): Buffer {
  if (value.length === 0 || value.length > 512 * 1024 || value.length % 4 !== 0 || !/^[A-Za-z0-9+/]*={0,2}$/.test(value)) {
    throw new Error("The signed attestation payload was not canonical base64.");
  }
  const decoded = Buffer.from(value, "base64");
  if (decoded.toString("base64") !== value) {
    throw new Error("The signed attestation payload was not canonical base64.");
  }
  return decoded;
}

function requireStringRecord(value: unknown, label: string): Record<string, unknown> {
  if (!isRecord(value)) throw new Error(`The signed attestation ${label} was invalid.`);
  return value;
}

function parseSignedStatement(bundle: Bundle): Record<string, unknown> {
  const envelope = requireStringRecord(bundle.dsseEnvelope, "DSSE envelope");
  const payload = strictBase64(String(envelope.payload ?? ""));
  let statement: unknown;
  try {
    statement = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(payload)) as unknown;
  } catch (error) {
    throw new Error("The signed attestation statement was not valid UTF-8 JSON.", { cause: error });
  }
  return requireStringRecord(statement, "statement");
}

interface SignedCertificateBindings {
  invocationId: string;
  sourceCommit: string;
}

function extractSignedCertificateBindings(bundle: Bundle): SignedCertificateBindings {
  const root = parseSignedStatement(bundle);
  const predicate = requireStringRecord(root.predicate, "predicate");
  const buildDefinition = requireStringRecord(predicate.buildDefinition, "build definition");
  if (!Array.isArray(buildDefinition.resolvedDependencies) || buildDefinition.resolvedDependencies.length !== 1) {
    throw new Error("The signed attestation source dependency was ambiguous.");
  }
  const dependency = requireStringRecord(buildDefinition.resolvedDependencies[0], "source dependency");
  const dependencyDigest = requireStringRecord(dependency.digest, "source dependency digest");
  if (
    !exactKeys(dependencyDigest, ["gitCommit"]) ||
    typeof dependencyDigest.gitCommit !== "string" ||
    !/^[0-9a-f]{40}$/.test(dependencyDigest.gitCommit)
  ) {
    throw new Error("The signed attestation source commit was invalid.");
  }
  const runDetails = requireStringRecord(predicate.runDetails, "run details");
  const metadata = requireStringRecord(runDetails.metadata, "run metadata");
  if (
    typeof metadata.invocationId !== "string" ||
    !new RegExp(`^${escapeRegExp(REPOSITORY_URL)}/actions/runs/[1-9]\\d*/attempts/[1-9]\\d*$`).test(metadata.invocationId)
  ) {
    throw new Error("The signed attestation run invocation was invalid.");
  }
  return { invocationId: metadata.invocationId, sourceCommit: dependencyDigest.gitCommit };
}

function validateSignedStatement(bundle: Bundle, input: ShellAttestationInput): void {
  const root = parseSignedStatement(bundle);
  if (
    root._type !== "https://in-toto.io/Statement/v1" ||
    root.predicateType !== SLSA_PREDICATE_TYPE ||
    !Array.isArray(root.subject) ||
    root.subject.length !== 5
  ) {
    throw new Error("The signed attestation was not an exact SLSA v1 statement.");
  }
  const expectedNames = new Set(canonicalReleaseSubjectNames(input.releaseTag));
  const seenNames = new Set<string>();
  let selectedMatches = 0;
  for (const entry of root.subject) {
    const subject = requireStringRecord(entry, "subject");
    const subjectDigest = requireStringRecord(subject.digest, "subject digest");
    if (
      !exactKeys(subject, ["digest", "name"]) ||
      typeof subject.name !== "string" ||
      !expectedNames.has(subject.name) ||
      seenNames.has(subject.name) ||
      !exactKeys(subjectDigest, ["sha256"]) ||
      typeof subjectDigest.sha256 !== "string" ||
      !/^[0-9a-f]{64}$/.test(subjectDigest.sha256)
    ) {
      throw new Error("The signed attestation release subject set was invalid.");
    }
    seenNames.add(subject.name);
    if (subject.name === input.assetName && subjectDigest.sha256 === input.digest.slice("sha256:".length)) {
      selectedMatches += 1;
    }
  }
  if (seenNames.size !== expectedNames.size || [...expectedNames].some((name) => !seenNames.has(name)) || selectedMatches !== 1) {
    throw new Error("The signed attestation subject did not match the selected installer.");
  }

  const predicate = requireStringRecord(root.predicate, "predicate");
  const buildDefinition = requireStringRecord(predicate.buildDefinition, "build definition");
  const externalParameters = requireStringRecord(buildDefinition.externalParameters, "external parameters");
  const workflow = requireStringRecord(externalParameters.workflow, "workflow parameters");
  const internalParameters = requireStringRecord(buildDefinition.internalParameters, "internal parameters");
  const github = requireStringRecord(internalParameters.github, "GitHub parameters");
  const runDetails = requireStringRecord(predicate.runDetails, "run details");
  const builder = requireStringRecord(runDetails.builder, "builder");
  const metadata = requireStringRecord(runDetails.metadata, "run metadata");
  const expectedRef = `refs/tags/${input.releaseTag}`;
  const expectedWorkflowUri = `${REPOSITORY_URL}${WORKFLOW_URI_PATH}@${expectedRef}`;
  if (
    buildDefinition.buildType !== SLSA_GITHUB_WORKFLOW_BUILD_TYPE ||
    workflow.repository !== REPOSITORY_URL ||
    workflow.path !== WORKFLOW_PATH ||
    workflow.ref !== expectedRef ||
    github.event_name !== "workflow_dispatch" ||
    github.repository_id !== String(REPOSITORY_ID) ||
    github.repository_owner_id !== String(REPOSITORY_OWNER_ID) ||
    github.runner_environment !== "github-hosted" ||
    builder.id !== expectedWorkflowUri ||
    typeof metadata.invocationId !== "string" ||
    !new RegExp(`^${escapeRegExp(REPOSITORY_URL)}/actions/runs/[1-9]\\d*/attempts/[1-9]\\d*$`).test(metadata.invocationId)
  ) {
    throw new Error("The signed attestation build identity did not match the FlintTrade release workflow.");
  }
  if (!Array.isArray(buildDefinition.resolvedDependencies) || buildDefinition.resolvedDependencies.length !== 1) {
    throw new Error("The signed attestation source dependency was ambiguous.");
  }
  const dependency = requireStringRecord(buildDefinition.resolvedDependencies[0], "source dependency");
  const dependencyDigest = requireStringRecord(dependency.digest, "source dependency digest");
  if (
    dependency.uri !== `git+${REPOSITORY_URL}@${expectedRef}` ||
    !exactKeys(dependencyDigest, ["gitCommit"]) ||
    typeof dependencyDigest.gitCommit !== "string" ||
    !/^[0-9a-f]{40}$/.test(dependencyDigest.gitCommit)
  ) {
    throw new Error("The signed attestation source identity did not match the selected release tag.");
  }
  // Keep this calculated here so the statement and certificate use one exact workflow identity.
  if (expectedWorkflowUri.length > 512) throw new Error("The release workflow identity was unexpectedly long.");
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function derUtf8String(value: string): string {
  const length = Buffer.byteLength(value, "utf8");
  if (length > 127 || length !== value.length) throw new Error("The certificate policy value was not bounded ASCII.");
  return String.fromCharCode(0x0c, length) + value;
}

export function sigstorePolicyForRelease(
  releaseTag: string,
  sourceCommit: string,
  invocationId: string,
  cachePath: string,
): VerifyOptions {
  if (
    !isReleaseTag(releaseTag) ||
    !/^[0-9a-f]{40}$/.test(sourceCommit) ||
    !new RegExp(`^${escapeRegExp(REPOSITORY_URL)}/actions/runs/[1-9]\\d*/attempts/[1-9]\\d*$`).test(invocationId) ||
    !path.isAbsolute(cachePath)
  ) {
    throw new Error("The Sigstore release policy requires a valid tag, source commit, invocation and absolute cache path.");
  }
  const ref = `refs/tags/${releaseTag}`;
  const workflowIdentity = `${REPOSITORY_URL}${WORKFLOW_URI_PATH}@${ref}`;
  return {
    certificateIdentityURI: `^${escapeRegExp(workflowIdentity)}$`,
    certificateIssuer: GITHUB_OIDC_ISSUER,
    certificateOIDs: {
      "1.3.6.1.4.1.57264.1.2": "workflow_dispatch",
      "1.3.6.1.4.1.57264.1.3": sourceCommit,
      "1.3.6.1.4.1.57264.1.4": "Desktop Release",
      "1.3.6.1.4.1.57264.1.5": REPOSITORY,
      "1.3.6.1.4.1.57264.1.6": ref,
      "1.3.6.1.4.1.57264.1.8": derUtf8String(GITHUB_OIDC_ISSUER),
      "1.3.6.1.4.1.57264.1.9": derUtf8String(workflowIdentity),
      "1.3.6.1.4.1.57264.1.10": derUtf8String(sourceCommit),
      "1.3.6.1.4.1.57264.1.11": derUtf8String("github-hosted"),
      "1.3.6.1.4.1.57264.1.12": derUtf8String(REPOSITORY_URL),
      "1.3.6.1.4.1.57264.1.13": derUtf8String(sourceCommit),
      "1.3.6.1.4.1.57264.1.14": derUtf8String(ref),
      "1.3.6.1.4.1.57264.1.15": derUtf8String(String(REPOSITORY_ID)),
      "1.3.6.1.4.1.57264.1.16": derUtf8String("https://github.com/navaneeshnagarajan"),
      "1.3.6.1.4.1.57264.1.17": derUtf8String(String(REPOSITORY_OWNER_ID)),
      "1.3.6.1.4.1.57264.1.18": derUtf8String(workflowIdentity),
      "1.3.6.1.4.1.57264.1.19": derUtf8String(sourceCommit),
      "1.3.6.1.4.1.57264.1.20": derUtf8String("workflow_dispatch"),
      "1.3.6.1.4.1.57264.1.21": derUtf8String(invocationId),
      "1.3.6.1.4.1.57264.1.22": derUtf8String("public"),
    },
    ctLogThreshold: 1,
    retry: { retries: 0 },
    timeout: DEFAULT_TIMEOUT_MS,
    tlogThreshold: 1,
    tufCachePath: cachePath,
  };
}

export function createGithubShellAttestationVerifier(
  options: GithubShellAttestationVerifierOptions,
): ShellAttestationVerifier {
  if (!path.isAbsolute(options.cachePath)) throw new Error("The Sigstore cache path must be absolute.");
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs <= 0 || timeoutMs > 60_000) {
    throw new Error("The GitHub attestation timeout must be between 1 and 60000 milliseconds.");
  }
  const verifyBundle = options.verifyBundle ?? ((bundle, policy) => verifySigstore(bundle, policy));
  const now = options.now ?? Date.now;

  return {
    async verify(input): Promise<VerifiedShellAttestation> {
      if (!isReleaseTag(input.releaseTag) || !isSha256Digest(input.digest) || !isAssetName(input.assetName, input.releaseTag)) {
        throw new Error("The selected shell installer identity was invalid.");
      }
      const apiUrl = attestationApiUrl(input.digest);
      const metadataBytes = await fetchBoundedResponse({
        fetcher: options.fetcher,
        init: {
          headers: {
            Accept: "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
          },
          redirect: "error",
        },
        label: "The GitHub attestation response",
        maximumBytes: MAX_ATTESTATION_METADATA_BYTES,
        signal: input.signal,
        timeoutMs,
        url: apiUrl,
        validateResponse(metadataResponse) {
          if (
            metadataResponse.status !== 200 ||
            // Electron net.fetch() reports an empty Response.url. The request
            // itself is exact and redirect:"error" rejects redirects; retain
            // strict endpoint validation whenever Electron supplies a URL.
            (metadataResponse.url !== "" && !isExactAttestationApiUrl(metadataResponse.url, input.digest)) ||
            metadataResponse.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase() !== "application/json" ||
            metadataResponse.headers.has("link")
          ) {
            throw new Error("The official GitHub attestation endpoint was unavailable or paginated.");
          }
        },
      });
      let metadataInput: unknown;
      try {
        metadataInput = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(metadataBytes)) as unknown;
      } catch (error) {
        throw new Error("The GitHub attestation response was not valid UTF-8 JSON.", { cause: error });
      }
      const requestTime = now();
      if (!Number.isFinite(requestTime) || requestTime < 0) throw new Error("The system clock was invalid.");
      const attestations = parseMetadata(metadataInput, requestTime);
      let lastFailure: unknown = null;
      for (const attestation of attestations) {
        try {
          const compressed = await fetchBoundedResponse({
            fetcher: options.fetcher,
            init: {
              headers: { Accept: "application/x-snappy" },
              redirect: "error",
            },
            label: "The GitHub attestation bundle response",
            maximumBytes: MAX_ATTESTATION_BUNDLE_BYTES,
            signal: input.signal,
            timeoutMs,
            url: attestation.bundleUrl,
            validateResponse(bundleResponse) {
              if (
                bundleResponse.status !== 200 ||
                (bundleResponse.url !== "" && (
                  bundleResponse.url !== attestation.bundleUrl ||
                  !isTrustedBundleUrl(bundleResponse.url, requestTime)
                )) ||
                bundleResponse.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase() !== "application/x-snappy"
              ) {
                throw new Error("The GitHub attestation bundle endpoint was unavailable.");
              }
            },
          });
          const bundle = requireSigstoreBundle(decodeSnappyJson(compressed));
          const bindings = extractSignedCertificateBindings(bundle);
          const policy = {
            ...sigstorePolicyForRelease(
              input.releaseTag,
              bindings.sourceCommit,
              bindings.invocationId,
              options.cachePath,
            ),
            timeout: timeoutMs,
          };
          const verification = Promise.resolve().then(() => verifyBundle(bundle, policy));
          await raceWithAbort(verification, input.signal, "Sigstore release verification");
          validateSignedStatement(bundle, input);
          return {
            assetName: input.assetName,
            digest: input.digest,
            releaseTag: input.releaseTag,
          };
        } catch (error) {
          if (input.signal.aborted) throw error;
          lastFailure = error;
        }
      }
      throw new Error("No cryptographically valid FlintTrade release attestation matched the selected installer.", {
        cause: lastFailure,
      });
    },
  };
}
