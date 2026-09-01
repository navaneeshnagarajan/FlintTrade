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

export function statRepositoryPath(repoRoot, relativePath) {
  const cleaned = relativePath.replace(/\/+$/, '');
  if (!cleaned || cleaned === '.' || cleaned.startsWith('..') || path.posix.isAbsolute(cleaned)) {
    return null;
  }
  if (/^[A-Za-z]:/.test(cleaned)) return null;

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

  return null;
}

export function rewriteMarkdownRepositoryLinks(markdown, sourcePath, options) {
  return markdown.replace(/\]\(([^)\s]+)\)/g, (match, target) => {
    const rewritten = rewriteRepositoryLink(target, sourcePath, options);
    return rewritten ? `](${rewritten})` : match;
  });
}
