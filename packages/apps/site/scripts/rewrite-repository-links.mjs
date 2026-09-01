import fs from 'node:fs';
import path from 'node:path';

/**
 * Rewrite repo-relative markdown links that Fumadocs would otherwise resolve
 * as `/docs/...` routes. Docs pages stay on-site; real repository files and
 * directories become GitHub blob/tree URLs for the deployment ref.
 */

export function splitLinkTarget(target) {
  const hashIndex = target.indexOf('#');
  if (hashIndex === -1) return [target, ''];
  return [target.slice(0, hashIndex), target.slice(hashIndex)];
}

export function resolveRelativeTarget(targetPath, sourcePath) {
  const normalisedTarget = targetPath.replace(/^\.\//, '');
  const sourceDir = path.posix.dirname(sourcePath);
  const candidates = [
    path.posix.normalize(path.posix.join(sourceDir, normalisedTarget)),
    path.posix.normalize(normalisedTarget),
  ];

  if (normalisedTarget.startsWith('docs/')) {
    candidates.push(path.posix.normalize(normalisedTarget));
  }

  return [...new Set(candidates)];
}

function slashVariants(candidate) {
  const stripped = candidate.replace(/\/+$/, '');
  if (!stripped) return [candidate];
  return stripped === candidate ? [candidate, `${candidate}/`] : [candidate, stripped];
}

function lookupMap(map, candidate) {
  for (const key of slashVariants(candidate)) {
    if (map.has(key)) return map.get(key);
  }
  return undefined;
}

export function repositoryBrowseUrl({ owner, name, ref, repoPath, isDirectory }) {
  const kind = isDirectory ? 'tree' : 'blob';
  const clean = repoPath.replace(/\/+$/, '');
  return `https://github.com/${owner}/${name}/${kind}/${ref}/${clean}`;
}

const REPO_ROOT_DIRECTORIES = new Set([
  '.github',
  'docs',
  'infra',
  'packaging',
  'packages',
  'scripts',
  'templates',
  'tests',
]);

const REPO_ROOT_FILES = new Set([
  'AGENTS.md',
  'CLAUDE.md',
  'LICENSE',
  'Makefile',
  'PLAN.md',
  'VERSION',
  'changelog.md',
  'contributing.md',
  'disclaimer.md',
  'flint.toml',
  'readme.md',
  'security.md',
]);

function isSafeRepoRelativePath(relativePath) {
  const cleaned = relativePath.replace(/\/+$/, '');
  if (!cleaned || cleaned === '.' || cleaned.startsWith('..') || path.posix.isAbsolute(cleaned)) {
    return null;
  }
  if (/^[A-Za-z]:/.test(cleaned)) return null;
  return cleaned;
}

/**
 * When the working tree is missing (source-less / GitHub-fetch generation),
 * still rewrite links that clearly point at repository roots rather than docs
 * pages. Trailing slash or no extension means a directory (`tree/`); an
 * extension means a file (`blob/`).
 */
export function inferRepoSourcePath(relativePath) {
  const cleaned = isSafeRepoRelativePath(relativePath);
  if (!cleaned) return null;

  const first = cleaned.split('/')[0];
  if (!REPO_ROOT_DIRECTORIES.has(first) && !REPO_ROOT_FILES.has(first) && !REPO_ROOT_FILES.has(cleaned)) {
    return null;
  }

  const hasExtension = Boolean(path.posix.extname(cleaned));
  return {
    repoPath: cleaned,
    isDirectory: relativePath.endsWith('/') || !hasExtension,
  };
}

export function statRepositoryPath(repoRoot, relativePath) {
  const cleaned = isSafeRepoRelativePath(relativePath);
  if (!cleaned) return null;

  const absolute = path.resolve(repoRoot, cleaned);
  const relative = path.relative(repoRoot, absolute);
  if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) {
    return null;
  }

  try {
    const stat = fs.statSync(absolute);
    return { isDirectory: stat.isDirectory() };
  } catch {
    return null;
  }
}

export function rewriteRepositoryLink(target, sourcePath, options) {
  if (/^(?:https?:|mailto:|tel:|#|\/)/.test(target)) return null;

  const {
    repoRoot,
    owner,
    name,
    ref,
    docRouteBySourcePath,
    repositoryFileUrls = new Map(),
    onRepoPath,
  } = options;

  const [targetPath, anchor] = splitLinkTarget(target);
  const candidates = resolveRelativeTarget(targetPath, sourcePath);

  for (const candidate of candidates) {
    const docRoute = lookupMap(docRouteBySourcePath, candidate);
    if (docRoute) return `${docRoute}${anchor}`;
  }

  for (const candidate of candidates) {
    const stat = statRepositoryPath(repoRoot, candidate);
    if (!stat) continue;

    const repoPath = candidate.replace(/\/+$/, '');
    const url = repositoryBrowseUrl({
      owner,
      name,
      ref,
      repoPath,
      isDirectory: stat.isDirectory,
    });
    onRepoPath?.(repoPath, url, stat.isDirectory);
    return `${url}${anchor}`;
  }

  for (const candidate of candidates) {
    const repositoryUrl = lookupMap(repositoryFileUrls, candidate);
    if (repositoryUrl) return `${repositoryUrl}${anchor}`;
  }

  for (const candidate of candidates) {
    const inferred = inferRepoSourcePath(candidate);
    if (!inferred) continue;

    const url = repositoryBrowseUrl({
      owner,
      name,
      ref,
      repoPath: inferred.repoPath,
      isDirectory: inferred.isDirectory,
    });
    onRepoPath?.(inferred.repoPath, url, inferred.isDirectory);
    return `${url}${anchor}`;
  }

  return null;
}

export function rewriteMarkdownRepositoryLinks(markdown, sourcePath, options) {
  return markdown.replace(/\]\(([^)\s]+)\)/g, (match, target) => {
    const rewritten = rewriteRepositoryLink(target, sourcePath, options);
    return rewritten ? `](${rewritten})` : match;
  });
}
