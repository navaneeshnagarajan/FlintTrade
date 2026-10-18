'use strict';
// Explicit-fixture regression: run ONLY in an existing no-egress sandbox with
// a disposable HOME/cache. Never downloads/provisions its own test fixture.
// node probe-packaging.cjs <desktop-dir> <published-electron.zip> <out-dir> <case>
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');

const [desktopArgument, archiveArgument, outputArgument, mode] = process.argv.slice(2);
const modes = ['original', 'api', 'framework', 'corrupt', 'mismatch', 'missing-entry', 'without-force', 'mirror-options', 'launcher'];
assert(modes.includes(mode), 'An explicit supported case is required');
const desktop = path.resolve(desktopArgument);
const archive = path.resolve(archiveArgument);
const output = path.resolve(outputArgument);
fs.mkdirSync(output, { recursive: true });
const req = createRequire(path.join(desktop, 'package.json'));
const builderReq = createRequire(req.resolve('electron-builder/package.json'));
const libPath = builderReq.resolve('app-builder-lib/package.json');
const libReq = createRequire(libPath);
const getPath = libReq.resolve('@electron/get');
const getReq = createRequire(getPath);
// Enable the library's own diagnostics, not a substitute downloader/hook.
getReq('debug').enable('@electron/get:index');
const { Cache } = getReq('./Cache.js');
const { getConfig, validateConfiguration } = libReq('./out/util/config/config.js');
const { DebugLogger } = libReq('builder-util');
const { downloadElectronArtifactZip } = libReq('./out/util/electronGet.js');
const digest = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const hashBytes = (bytes) => crypto.createHash('sha256').update(bytes).digest('hex');
const record = {
  case: mode, node: process.version, execPath: process.execPath, archive,
  scope: 'Real installed acquisition API and framework extraction only; no AppImage build or runtime qualification',
  dependencyFiles: {},
};
for (const file of [libPath, libReq.resolve('./scheme.json'), libReq.resolve('./out/util/electronGet.js'),
  libReq.resolve('./out/electron/ElectronFramework.js'), getPath, getReq.resolve('./Cache.js')]) {
  record.dependencyFiles[file] = digest(file);
}
record.packageSha256 = digest(path.join(desktop, 'package.json'));
async function main() {
  for (const key of ['NODE_OPTIONS', 'ELECTRON_MIRROR', 'ELECTRON_DOWNLOAD_CACHE_MODE', 'ELECTRON_BUILDER_CACHE',
    'ELECTRON_BUILDER_BINARIES_MIRROR', 'ELECTRON_BUILDER_7ZIP_PATH', 'APPIMAGE_TOOLS_PATH']) {
    assert.equal(process.env[key], undefined, `Unexpected override ${key}`);
  }
  const config = await getConfig(desktop);
  await validateConfiguration(config, new DebugLogger(false));
  assert.equal(config.electronDist, undefined);
  const filename = path.basename(archive);
  const match = /^electron-v([0-9.]+)-(darwin|linux|win32)-(arm64|x64)\.zip$/.exec(filename);
  assert(match, 'Expected a published platform Electron ZIP filename');
  const [, version, platform, arch] = match;
  assert.equal(version, config.electronVersion);
  const checksumBytes = fs.readFileSync(path.join(__dirname, `electron-v${version}-SHASUMS256.txt`));
  assert.equal(hashBytes(checksumBytes), 'ae1159fdb6d008ca267c267edb6dd82ded692529c9a930386452511aaaddb7b1');
  const published = Object.fromEntries(checksumBytes.toString('utf8').trim().split(/\r?\n/).map(line => {
    const row = /^([a-f0-9]{64}) [ *](\S+)$/.exec(line);
    assert(row, 'Malformed published checksum record');
    return [row[2], row[1]];
  }));
  assert.equal(digest(archive), published[filename], 'Input ZIP does not match the retained published checksum');
  const url = `https://github.com/electron/electron/releases/download/v${version}/${filename}`;
  const cachePath = new Cache().getCachePath(url, filename);
  assert.notEqual(cachePath, archive);
  fs.mkdirSync(path.dirname(cachePath), { recursive: true });
  fs.copyFileSync(archive, cachePath);
  fs.writeFileSync(path.join(path.dirname(cachePath), 'SHASUMS256.txt'), checksumBytes);
  record.cachePath = cachePath;
  record.archiveSha256 = digest(archive);
  if (mode === 'original') delete config.electronDownload;
  if (mode === 'without-force') delete config.electronDownload.force;
  if (mode === 'mirror-options') config.electronDownload.mirrorOptions = {};
  if (mode === 'mismatch') config.electronDownload.checksums[filename] = '0'.repeat(64);
  if (mode === 'missing-entry') delete config.electronDownload.checksums[filename];
  if (mode === 'corrupt') {
    const fd = fs.openSync(cachePath, 'r+');
    try {
      const byte = Buffer.alloc(1);
      fs.readSync(fd, byte, 0, 1, 128);
      byte[0] ^= 1;
      fs.writeSync(fd, byte, 0, 1, 128);
    } finally { fs.closeSync(fd); }
  }
  record.cachedSha256Before = digest(cachePath);
  record.electronDownload = config.electronDownload ?? null;
  if (mode === 'launcher') {
    const { default: AppImageTarget } = libReq('./out/targets/appimage/AppImageTarget.js');
    const { LinuxTargetHelper } = libReq('./out/targets/LinuxTargetHelper.js');
    const metadata = JSON.parse(fs.readFileSync(path.join(desktop, 'package.json'), 'utf8'));
    const entries = {};
    for (const state of ['original', 'corrected']) {
      const selected = structuredClone(config);
      if (state === 'original') delete selected.appImage.executableArgs;
      const packager = { config: selected, platformSpecificBuildOptions: selected.linux,
        executableName: selected.executableName, fileAssociations: [], info: { metadata },
        appInfo: { productName: selected.productName, productFilename: selected.productName,
          description: metadata.description, buildVersion: metadata.version } };
      const text = await new AppImageTarget('appImage', packager, new LinuxTargetHelper(packager), output).desktopEntry.value;
      fs.writeFileSync(path.join(output, `${state}.desktop`), text);
      entries[state] = text.split(/\r?\n/).filter(line => line.startsWith('Exec='));
    }
    assert.deepEqual(entries.original, ['Exec=AppRun --no-sandbox %U']);
    assert.deepEqual(entries.corrected, ['Exec=AppRun %U']);
    record.result = { entries, metadataSha256: record.packageSha256,
      desktopName: metadata.desktopName ?? null,
      inheritedWarning: metadata.desktopName ? null : 'desktopName is not set in package.json; retained in stdout; no registration repair in R121',
      toolsets: config.toolsets ?? null };
  } else if (mode === 'framework' || mode === 'mirror-options') {
    const { Platform } = libReq('./out/index.js');
    const { createElectronFrameworkSupport } = libReq('./out/electron/ElectronFramework.js');
    const metadata = JSON.parse(fs.readFileSync(path.join(desktop, 'package.json'), 'utf8'));
    const packager = { config, projectDir: desktop, appInfo: { type: metadata.type },
      platform: platform === 'linux' ? Platform.LINUX : platform === 'darwin' ? Platform.MAC : Platform.WINDOWS,
      info: { getWorkspaceRoot: async () => path.resolve(desktop, '../../..') } };
    const framework = await createElectronFrameworkSupport(config, packager);
    const appOutDir = path.join(output, 'framework-output');
    assert(!fs.existsSync(appOutDir), 'Framework output must be fresh');
    await framework.prepareApplicationStageDirectory({ packager, appOutDir, platformName: platform, arch, version });
    // Linux fixture is exercised here; other archives require their native validation.
    assert.equal(platform, 'linux', 'This extraction oracle is Linux-only');
    assert(fs.statSync(path.join(appOutDir, 'electron')).isFile());
    assert(fs.statSync(path.join(appOutDir, 'resources')).isDirectory());
    assert(!fs.existsSync(path.join(appOutDir, 'resources/default_app.asar')));
    assert(!fs.existsSync(path.join(appOutDir, 'version')));
    record.result = { appOutDir, electronSha256: digest(path.join(appOutDir, 'electron')), cleanedDefaultApp: true };
  } else {
    const returned = await downloadElectronArtifactZip({ electronDownload: config.electronDownload,
      artifactName: 'electron', platformName: platform, arch, version });
    record.result = { path: returned, sha256: digest(returned) };
    assert.equal(returned, cachePath);
    assert.equal(record.result.sha256, published[filename]);
  }
  record.status = 'returned';
}
main().catch(error => {
  record.status = 'refused';
  record.error = { name: error.name, code: error.code, message: error.message, stack: error.stack };
  process.exitCode = 1;
}).finally(() => {
  record.archiveSha256After = digest(archive);
  fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(record, null, 2) + '\n');
  console.log(JSON.stringify({ case: mode, status: record.status, result: record.result, error: record.error }, null, 2));
});
