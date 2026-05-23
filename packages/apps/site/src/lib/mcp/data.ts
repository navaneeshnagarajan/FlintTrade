import docsIndexJson from '@/generated/docs-index.json';
import packagesIndexJson from '@/generated/packages-index.json';

import type { DocsIndex, PackageEntry } from './types';

export const docsIndex = docsIndexJson as DocsIndex;
export const packageIndex = packagesIndexJson as PackageEntry[];

export const docsAndPackages = [...docsIndex.docs, ...docsIndex.packages];
