import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

import { describe, expect, it } from "vitest";

const desktop = path.resolve(import.meta.dirname, "..");
const metadata = JSON.parse(readFileSync(path.join(desktop, "package.json"), "utf8"));
const require = createRequire(import.meta.url);
// Resolve the builder's own dependency, not an unrelated top-level @electron/get.
const builderRequire = createRequire(require.resolve("electron-builder/package.json"));
const libraryRequire = createRequire(builderRequire.resolve("app-builder-lib/package.json"));
const { getConfig, validateConfiguration } = libraryRequire("./out/util/config/config.js");
const { DebugLogger } = libraryRequire("builder-util");

// Published bytes, not checksums recomputed from a potentially poisoned cache.
const checksumFile = readFileSync(path.join(import.meta.dirname, "fixtures/electron-v44.7.0-SHASUMS256.txt"));
const published = Object.fromEntries(checksumFile.toString("utf8").trim().split(/\r?\n/).map((line) => {
  const match = /^([a-f0-9]{64}) [ *](\S+)$/.exec(line);
  if (!match) throw new Error("Malformed published Electron checksum record");
  return [match[2], match[1]];
}));

// These are the existing package-script targets; metadata coverage is NOT
// evidence of a native macOS, Windows or Linux arm64 build.
const targets = ["darwin-arm64", "darwin-x64", "linux-arm64", "linux-x64", "win32-x64"];

describe("packaging configuration integrity", () => {
  it("pins published Electron checksums through the real reader's cache-preserving options", async () => {
    expect(createHash("sha256").update(checksumFile).digest("hex")).toBe(
      "ae1159fdb6d008ca267c267edb6dd82ded692529c9a930386452511aaaddb7b1",
    );
    const config = await getConfig(desktop);
    expect(config.electronVersion).toBe(metadata.devDependencies.electron);
    const checksums = Object.fromEntries(targets.map((target) => {
      const filename = `electron-v${config.electronVersion}-${target}.zip`;
      expect(published[filename]).toMatch(/^[a-f0-9]{64}$/);
      return [filename, published[filename]];
    }));
    // force:false discriminates ElectronGetOptions in app-builder-lib 26.15.3.
    // checksums alone takes its legacy branch; mirrorOptions takes the other
    // lossy branch in ElectronFramework.createDownloadOpts. Neither is safe.
    expect(config.electronDownload).toEqual({ force: false, checksums });
    expect(config.electronDist).toBeUndefined();
    await validateConfiguration(config, new DebugLogger(false));
  });

  it("generates an AppImage desktop Exec without sandbox-disabling arguments", async () => {
    const config = await getConfig(desktop);
    const { default: AppImageTarget } = libraryRequire("./out/targets/appimage/AppImageTarget.js");
    const { LinuxTargetHelper } = libraryRequire("./out/targets/LinuxTargetHelper.js");
    // Only inert packager metadata is a fixture. Both argument selection and
    // desktop serialization are the installed builder's unchanged consumers.
    const packager = {
      config,
      platformSpecificBuildOptions: config.linux,
      executableName: config.executableName,
      appInfo: {
        productName: config.productName,
        productFilename: config.productName,
        description: metadata.description,
        buildVersion: metadata.version,
      },
      info: { metadata: { ...metadata, desktopName: metadata.desktopName ?? config.executableName } },
      fileAssociations: [],
    };
    const generated = await new AppImageTarget(
      "appImage", packager, new LinuxTargetHelper(packager), desktop,
    ).desktopEntry.value;
    expect(generated.split(/\r?\n/).filter((line: string) => line.startsWith("Exec="))).toEqual(["Exec=AppRun %U"]);
    expect(generated).not.toMatch(/--(?:no-sandbox|disable-setuid-sandbox|disable-seccomp-filter-sandbox|disable-gpu-sandbox)/);
    expect(config.appImage?.executableArgs).toEqual([]);
    await validateConfiguration(config, new DebugLogger(false));
  });

  it("rejects an unsupported acquisition field with the installed builder schema", async () => {
    const config = await getConfig(desktop);
    config.electronDownload = { ...config.electronDownload, inventedOfflineMode: true };
    await expect(validateConfiguration(config, new DebugLogger(false))).rejects.toThrow(/configuration\.electronDownload/);
  });
});
