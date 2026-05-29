import versionJson from '@/generated/version.json';

type VersionInfo = {
  version: string;
  versionTag: string;
  sourcePath: string;
};

export const versionInfo = versionJson as VersionInfo;
export const APP_VERSION = versionInfo.version;
export const APP_VERSION_TAG = versionInfo.versionTag;
