import { SpeedInsights } from '@vercel/speed-insights/next';

/**
 * Vercel Speed Insights, loaded only on Vercel-hosted deploys.
 *
 * A Hostinger / generic Node host must be able to boot this app without
 * talking to Vercel. `VERCEL` is set to `"1"` on Vercel's runtime; anywhere
 * else this is a no-op.
 */
export function OptionalSpeedInsights() {
  if (process.env.VERCEL !== '1') {
    return null;
  }
  return <SpeedInsights />;
}
