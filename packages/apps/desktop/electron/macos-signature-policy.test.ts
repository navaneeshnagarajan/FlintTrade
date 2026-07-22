import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

import { describe, expect, it } from "vitest";

interface MacosSignatureVerifier {
  verifyDistributionBinding(applicationSignature: string, promoterSignature: string): void;
}

const require = createRequire(import.meta.url);
const verifier = require("../scripts/verify-macos-signature.cjs") as MacosSignatureVerifier;
const atomicPromoterBuilder = path.resolve(import.meta.dirname, "..", "scripts", "build-atomic-promoter.mjs");

function distributionSignature(options: { runtime?: boolean; team?: string; adHoc?: boolean } = {}): string {
  const { runtime = true, team = "FLINTTEAM1", adHoc = false } = options;
  return [
    `flags=0x${runtime ? "10000(runtime)" : "0(none)"}`,
    adHoc ? "Signature=adhoc" : "Authority=Developer ID Application: FlintTrade",
    `TeamIdentifier=${team}`,
  ].join("\n");
}

describe("macOS native-helper signing policy", () => {
  it("binds distribution application and helper signatures to hardened runtime and one team", () => {
    expect(() => verifier.verifyDistributionBinding(
      distributionSignature(),
      distributionSignature(),
    )).not.toThrow();
  });

  it("rejects an ad-hoc atomic promoter in a distribution package", () => {
    expect(() => verifier.verifyDistributionBinding(
      distributionSignature(),
      distributionSignature({ adHoc: true, team: "not set" }),
    )).toThrow(/atomic promoter has only an ad-hoc seal/i);
  });

  it("rejects an atomic promoter without hardened runtime", () => {
    expect(() => verifier.verifyDistributionBinding(
      distributionSignature(),
      distributionSignature({ runtime: false }),
    )).toThrow(/atomic promoter lacks hardened runtime/i);
  });

  it("rejects an atomic promoter signed by a different team", () => {
    expect(() => verifier.verifyDistributionBinding(
      distributionSignature({ team: "FLINTTEAM1" }),
      distributionSignature({ team: "FOREIGNTEAM" }),
    )).toThrow(/do not share one signing team identity/i);
  });

  it("requests hardened runtime when the native helper uses a distribution identity", () => {
    const builder = readFileSync(atomicPromoterBuilder, "utf8");

    expect(builder).toContain('signingArguments.push("--options", "runtime", "--timestamp")');
  });
});
