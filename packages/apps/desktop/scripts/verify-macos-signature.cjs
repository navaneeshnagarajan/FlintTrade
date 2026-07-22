#!/usr/bin/env node

const { spawnSync } = require("node:child_process");
const path = require("node:path");

function codesign(arguments_, options = {}) {
  return spawnSync("/usr/bin/codesign", arguments_, {
    encoding: "utf8",
    ...options,
  });
}

module.exports = async function verifyMacosSignature(context) {
  if (context.electronPlatformName !== "darwin") return;
  const application = path.join(
    context.appOutDir,
    `${context.packager.appInfo.productFilename}.app`,
  );
  const verification = codesign(["--verify", "--deep", "--strict", "--verbose=2", application]);
  if (verification.status !== 0) {
    throw new Error(`The packaged macOS application is not consistently sealed: ${verification.stderr.trim()}`);
  }

  const details = codesign(["--display", "--verbose=4", application]);
  const signature = `${details.stdout}\n${details.stderr}`;
  if (process.env.FLINTTRADE_REQUIRE_DISTRIBUTION_SIGNATURE === "1") {
    if (/Signature=adhoc/i.test(signature) || !/^Authority=/m.test(signature) || /TeamIdentifier=not set/i.test(signature)) {
      throw new Error("A distribution-signed package was required, but the macOS application has only an ad-hoc seal.");
    }
    if (!/flags=.*runtime/i.test(signature)) {
      throw new Error("A distribution-signed package was required, but hardened runtime is not present.");
    }
  }
  console.log(`Verified macOS code signature for ${application}`);
};
