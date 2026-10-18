// Test source: GNU AGPL v3, as licensed in the repository LICENSE.
import configuration from '../../vite.config';
export default { ...configuration, cacheDir: process.env.INCIDENT_PROBE_CACHE ?? configuration.cacheDir };
