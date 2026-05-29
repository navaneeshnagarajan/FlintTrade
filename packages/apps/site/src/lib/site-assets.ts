export const siteAssetVersion = '20260529';

export function flinttradeAsset(path: string): string {
  return `/flinttrade/${path}?v=${siteAssetVersion}`;
}
