export const siteAssetVersion = '20260530';

export function flinttradeAsset(path: string): string {
  return `/flinttrade/${path}?v=${siteAssetVersion}`;
}
