export const THREE_RUNTIME_GZIP_LIMIT: number;
export const TOTAL_ENHANCEMENT_GZIP_LIMIT: number;

export interface BundleArtifact {
  path: string;
  bytes: Buffer;
}

export interface ScrollWorldBundleReport {
  pilotFiles: string[];
  threeFiles: string[];
  cssFiles: string[];
  threeRuntimeGzip: number;
  totalEnhancementGzip: number;
  files: Array<{ path: string; raw: number; gzip: number }>;
}

export function auditArtifacts(artifacts: BundleArtifact[]): ScrollWorldBundleReport;
export function assertPayloadBudgets(report: ScrollWorldBundleReport): void;
export function auditScrollWorldBuild(staticDirectory?: string): Promise<ScrollWorldBundleReport>;
