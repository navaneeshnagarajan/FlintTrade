#!/usr/bin/env node

const { spawnSync } = require("node:child_process");
const path = require("node:path");

function codesign(arguments_, options = {}) {
  return spawnSync("/usr/bin/codesign", arguments_, {
    encoding: "utf8",
    ...options,
  });
}

function requireDistributionSignature(signature, label) {
  if (/Signature=adhoc/i.test(signature) || !/^Authority=/m.test(signature) || /TeamIdentifier=not set/i.test(signature)) {
    throw new Error(`A distribution-signed package was required, but the ${label} has only an ad-hoc seal.`);
  }
  if (!/flags=.*runtime/i.test(signature)) {
    throw new Error(`A distribution-signed package was required, but the ${label} lacks hardened runtime.`);
  }
  const team = signature.match(/^TeamIdentifier=(.+)$/m)?.[1];
  if (!team) throw new Error(`The ${label} does not expose a signing team identity.`);
  return team;
}

function verifyDistributionBinding(applicationSignature, promoterSignature) {
  const applicationTeam = requireDistributionSignature(applicationSignature, "macOS application");
  const promoterTeam = requireDistributionSignature(promoterSignature, "macOS atomic promoter");
  if (applicationTeam !== promoterTeam) {
    throw new Error("The macOS application and atomic promoter do not share one signing team identity.");
  }
}

async function verifyMacosSignature(context) {
  if (context.electronPlatformName !== "darwin") return;
  const application = path.join(
    context.appOutDir,
    `${context.packager.appInfo.productFilename}.app`,
  );
  const verification = codesign(["--verify", "--deep", "--strict", "--verbose=2", application]);
  if (verification.status !== 0) {
    throw new Error(`The packaged macOS application is not consistently sealed: ${verification.stderr.trim()}`);
  }

  const nativePromoter = path.join(
    application,
    "Contents",
    "Resources",
    "bootstrap",
    "flinttrade-fs-promoter.node",
  );
  const promoterVerification = codesign(["--verify", "--strict", "--verbose=2", nativePromoter]);
  if (promoterVerification.status !== 0) {
    throw new Error(`The packaged macOS atomic promoter is not consistently sealed: ${promoterVerification.stderr.trim()}`);
  }

  const details = codesign(["--display", "--verbose=4", application]);
  const signature = `${details.stdout}\n${details.stderr}`;
  const promoterDetails = codesign(["--display", "--verbose=4", nativePromoter]);
  const promoterSignature = `${promoterDetails.stdout}\n${promoterDetails.stderr}`;
  if (details.status !== 0 || promoterDetails.status !== 0) {
    throw new Error("The packaged macOS signature identities could not be inspected.");
  }
  if (process.env.FLINTTRADE_REQUIRE_DISTRIBUTION_SIGNATURE === "1") {
    verifyDistributionBinding(signature, promoterSignature);
  }
  console.log(`Verified macOS code signature for ${application}`);
}

verifyMacosSignature.verifyDistributionBinding = verifyDistributionBinding;
module.exports = verifyMacosSignature;
