export const siteAssetVersion = '20260613';

export function flinttradeAsset(path: string): string {
  return `/flinttrade/${path}?v=${siteAssetVersion}`;
}
