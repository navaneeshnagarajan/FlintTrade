import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// Use fileURLToPath (not URL.pathname): on Windows `.pathname` yields "/C:/…",
// and path.resolve("/C:/…", "..") produces a doubled-drive "C:\C:\…" that breaks
// every mkdir/read below. fileURLToPath converts file URLs correctly on all OSes.
const siteRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = process.env.FLINTTRADE_REPO_ROOT
  ? path.resolve(process.env.FLINTTRADE_REPO_ROOT)
  : path.resolve(siteRoot, '..', '..', '..');

const contentRoot = path.join(siteRoot, 'content', 'docs');
const generatedRoot = path.join(siteRoot, 'src', 'generated');
const publicRoot = path.join(siteRoot, 'public', 'flinttrade');
const generationLockDir = path.join(siteRoot, '.content-generation.lock');
const repositoryOwner = 'navaneeshnagarajan';
const repositoryName = 'FlintTrade';
const repositoryRef = process.env.VERCEL_GIT_COMMIT_SHA || process.env.VERCEL_GIT_COMMIT_REF || 'main';

const fallbackPackagePaths = [
  'apps/site',
  'apps/terminal',
  'core/core',
  'core/data',
  'core/design-system',
  'core/historical',
  'core/indicators',
  'core/ticks',
  'integrations/gateway',
  'integrations/webhooks',
  'services/ai',
  'services/automation',
  'services/backtest',
  'services/ditto',
  'services/engine',
  'services/journal',
  'services/screener',
];

const fallbackScreenshotFiles = [
  '01-welcome.png',
  '02-explore.png',
  '03-invest.png',
  '04-trade-dismissed.png',
  '04-trade.png',
  '05-learn.png',
  '06-lab.png',
  '07-automate.png',
  '08-ai.png',
  '09-ditto.png',
  '10-settings.png',
];

const rootDocs = [
  ['docs/README.md', 'index', 'Docs', 'Project documentation index'],
  ['docs/INVENTORY.md', 'inventory', 'Docs', 'Build-status inventory: built & working, built but untested, referenced but not built'],
  ['disclaimer.md', 'disclaimer', 'Safety', 'Alpha-stage, no-advice, trading-risk, and user-responsibility notice'],
  ['docs/DESKTOP.md', 'desktop', 'Setup', 'End-user desktop app install, uninstall, configuration, and local build guide'],
  ['docs/USER_GUIDE.md', 'user-guide', 'Docs', 'User guide for local setup and FlintTrade workspaces'],
  ['docs/DEVELOPER_GUIDE.md', 'developer-guide', 'Contributing', 'Contributor setup and extension guide'],
  ['docs/ARCHITECTURE.md', 'architecture', 'Architecture', 'System architecture and package flow'],
  ['docs/API.md', 'api', 'API', 'HTTP, WebSocket, and integration reference'],
  ['docs/COMPATIBILITY.md', 'compatibility', 'Docs', 'Supported brokers, exchanges, and environments'],
  ['docs/ORDER_SAFETY.md', 'order-safety', 'Operations', 'Audit, retention, and order-safety notes'],
  ['docs/CI.md', 'ci', 'Contributing', 'Continuous integration and quality checks'],
  ['docs/REFERENCES.md', 'references', 'Credits', 'Public attribution and project influence notes'],
];

const setupDocs = [
  ['docs/setup/QUICKSTART.md', 'setup/quickstart', 'Setup', 'Fast setup path for a new contributor machine'],
  ['docs/setup/macos.md', 'setup/macos', 'Setup', 'macOS setup guide'],
  ['docs/setup/linux.md', 'setup/linux', 'Setup', 'Linux setup guide'],
  ['docs/setup/windows.md', 'setup/windows', 'Setup', 'Windows setup guide'],
  ['docs/setup/raspberry-pi.md', 'setup/raspberry-pi', 'Setup', 'Raspberry Pi setup guide'],
  ['docs/setup/static-ip-setup.md', 'setup/static-ip-setup', 'Setup', 'Static IP setup notes for broker API access'],
  ['docs/setup/email.md', 'setup/email', 'Setup', 'SMTP and SES setup for recovery email'],
  ['docs/setup/backup.md', 'setup/backup', 'Setup', 'Local backup and restore guide'],
  ['docs/setup/multi-user.md', 'setup/multi-user', 'Setup', 'Why multi-user mode was removed as overscope'],
];

const releaseDocs = [
  ['docs/releases/v0.6.0-beta.7.md', 'releases/v0.6.0-beta.7', 'Releases', 'FlintTrade v0.6.0-beta.7 release notes'],
  ['docs/releases/v0.6.0-beta.6.md', 'releases/v0.6.0-beta.6', 'Releases', 'FlintTrade v0.6.0-beta.6 release notes'],
  ['docs/releases/v0.6.0-beta.5.md', 'releases/v0.6.0-beta.5', 'Releases', 'FlintTrade v0.6.0-beta.5 release notes'],
  ['docs/releases/v0.6.0-beta.4.md', 'releases/v0.6.0-beta.4', 'Releases', 'FlintTrade v0.6.0-beta.4 release notes'],
  ['docs/releases/v0.6.0-beta.3.md', 'releases/v0.6.0-beta.3', 'Releases', 'FlintTrade v0.6.0-beta.3 release notes'],
  ['docs/releases/v0.6.0-beta.2.md', 'releases/v0.6.0-beta.2', 'Releases', 'FlintTrade v0.6.0-beta.2 release notes'],
  ['docs/releases/v0.6.0-beta.1.md', 'releases/v0.6.0-beta.1', 'Releases', 'FlintTrade v0.6.0-beta.1 release notes'],
  ['docs/releases/v0.6.0-beta.md', 'releases/v0.6.0-beta', 'Releases', 'FlintTrade v0.6.0 beta release notes'],
  ['docs/releases/v0.6.0-alpha.md', 'releases/v0.6.0-alpha', 'Releases', 'FlintTrade v0.6.0 alpha release notes'],
  ['docs/releases/v0.5.2-dev.md', 'releases/v0.5.2-dev', 'Releases', 'FlintTrade v0.5.2 development notes'],
  ['docs/releases/v0.5.1.md', 'releases/v0.5.1', 'Releases', 'FlintTrade v0.5.1 release notes'],
];
const releasePages = releaseDocs.map(([, slug]) => slug.replace(/^releases\//, ''));

const manualDocs = [
  {
    slug: 'mcp',
    area: 'MCP',
    title: 'Docs and Contribution MCP',
    description: 'Read-only MCP surfaces for development, documentation, and contribution workflows.',
    sourcePath: 'packages/apps/site/src/app/mcp/page.tsx',
    content: `The FlintTrade docs MCP is a read-only development assistant. It exposes repository documentation, package orientation, testing recommendations, and contribution prompts. It does not expose broker credentials, live trading, account state, fund data, order IDs, or order-placement tools.`,
  },
  {
    slug: 'contributing',
    area: 'Contributing',
    title: 'Contributing Through the Site',
    description: 'How the public site guides developers from reading docs to opening focused pull requests.',
    sourcePath: 'packages/apps/site/src/app/contribute/page.tsx',
    content: `The contribution surface points developers to the Developer Guide, package READMEs, CI contract, setup guides, API reference, and MCP prompts for planning safe changes. Documentation remains canonical in the repository root docs folder.`,
  },
];

const docsToGenerate = [...rootDocs, ...setupDocs, ...releaseDocs];

const docRouteBySourcePath = new Map(
  docsToGenerate.map(([sourcePath, slug]) => [sourcePath, `/docs/${slug === 'index' ? '' : slug}`]),
);

const repositoryFileUrls = new Map([
  ['changelog.md', 'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/changelog.md'],
  ['contributing.md', 'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/contributing.md'],
  ['docs/releases/', 'https://github.com/navaneeshnagarajan/FlintTrade/tree/main/docs/releases'],
  ['docs/screenshots/', 'https://github.com/navaneeshnagarajan/FlintTrade/tree/main/docs/screenshots'],
  ['docs/setup/', 'https://github.com/navaneeshnagarajan/FlintTrade/tree/main/docs/setup'],
  ['docs/superpowers/specs/', 'https://github.com/navaneeshnagarajan/FlintTrade/tree/main/docs/superpowers/specs'],
  ['docs/DESKTOP.md', 'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/docs/DESKTOP.md'],
  ['disclaimer.md', 'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/disclaimer.md'],
  ['flint.toml', 'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/flint.toml'],
  ['LICENSE', 'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/LICENSE'],
  ['readme.md', 'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/readme.md'],
  ['security.md', 'https://github.com/navaneeshnagarajan/FlintTrade/blob/main/security.md'],
]);

function titleFromMarkdown(markdown, fallback) {
  const heading = markdown.match(/^#\s+(.+)$/m);
  return heading ? stripInlineMarkdown(heading[1]).trim() : fallback;
}

function stripInlineMarkdown(value) {
  return value
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[*_~]/g, '');
}

function normaliseVersion(value) {
  return value.trim().replace(/^v/, '');
}

function tagVersion(value) {
  const normalised = normaliseVersion(value);
  return normalised.startsWith('v') ? normalised : `v${normalised}`;
}

function descriptionFromMarkdown(markdown, fallback) {
  const withoutTitle = markdown.replace(/^#\s+.+$/m, '').trim();
  const paragraph = withoutTitle
    .split(/\n\s*\n/)
    .map((part) => part.trim())
    .find((part) => part && !part.startsWith('```') && !part.startsWith('|') && !part.startsWith('<'));

  if (!paragraph) return fallback;
  return stripInlineMarkdown(paragraph)
    .replace(/^>\s*/, '')
    .replace(/\s+/g, ' ')
    .slice(0, 180)
    .trim();
}

function headingsFromMarkdown(markdown) {
  return [...markdown.matchAll(/^(#{2,4})\s+(.+)$/gm)].map((match) => ({
    level: match[1].length,
    title: stripInlineMarkdown(match[2]).trim(),
  }));
}

function escapeFrontmatter(value) {
  return JSON.stringify(value).slice(1, -1);
}

async function writeFileAtomic(destination, content) {
  await fs.mkdir(path.dirname(destination), { recursive: true });
  const temporary = path.join(path.dirname(destination), `.${path.basename(destination)}.${process.pid}.${Date.now()}.tmp`);
  await fs.writeFile(temporary, content, 'utf8');
  await fs.rename(temporary, destination);
}

async function writeBinaryFileAtomic(destination, content) {
  await fs.mkdir(path.dirname(destination), { recursive: true });
  const temporary = path.join(path.dirname(destination), `.${path.basename(destination)}.${process.pid}.${Date.now()}.tmp`);
  await fs.writeFile(temporary, content);
  await fs.rename(temporary, destination);
}

function removeFirstH1(markdown) {
  return markdown.replace(/^#\s+.+\n+/, '').trimStart();
}

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function acquireGenerationLock() {
  const startedAt = Date.now();

  while (true) {
    try {
      await fs.mkdir(generationLockDir);
      await fs.writeFile(path.join(generationLockDir, 'pid'), `${process.pid}\n`, 'utf8');
      return;
    } catch (error) {
      if (error?.code !== 'EEXIST') throw error;

      const stat = await fs.stat(generationLockDir).catch(() => null);
      if (stat && Date.now() - stat.mtimeMs > 120_000) {
        await fs.rm(generationLockDir, { recursive: true, force: true });
        continue;
      }

      if (Date.now() - startedAt > 30_000) {
        throw new Error('Timed out waiting for FlintTrade site content generation lock.');
      }

      await sleep(100);
    }
  }
}

async function withGenerationLock(task) {
  await acquireGenerationLock();
  try {
    await task();
  } finally {
    await fs.rm(generationLockDir, { recursive: true, force: true });
  }
}

function splitLinkTarget(target) {
  const hashIndex = target.indexOf('#');
  if (hashIndex === -1) return [target, ''];
  return [target.slice(0, hashIndex), target.slice(hashIndex)];
}

function resolveRelativeTarget(targetPath, sourcePath) {
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

function rewriteRepositoryLink(target, sourcePath) {
  if (/^(?:https?:|mailto:|tel:|#|\/)/.test(target)) return null;

  const [targetPath, anchor] = splitLinkTarget(target);
  const candidates = resolveRelativeTarget(targetPath, sourcePath);

  for (const candidate of candidates) {
    const docRoute = docRouteBySourcePath.get(candidate);
    if (docRoute) return `${docRoute}${anchor}`;

    const repositoryUrl = repositoryFileUrls.get(candidate);
    if (repositoryUrl) return `${repositoryUrl}${anchor}`;
  }

  return null;
}

function normaliseMarkdown(markdown, sourcePath) {
  let value = markdown.replace(/\r\n/g, '\n');

  value = value.replace(/^(\s*)```env\b/gm, '$1```bash');
  value = value.replace(/<(\d)/g, '&lt;$1');
  value = value.replace(/\]\(screenshots\/([^)]+)\)/g, '](/flinttrade/screenshots/$1)');
  value = value.replace(/\]\(docs\/screenshots\/([^)]+)\)/g, '](/flinttrade/screenshots/$1)');
  value = value.replace(/\]\(assets\/logo\.svg\)/g, '](/flinttrade/logo.svg)');
  value = value.replace(/\]\(docs\/assets\/logo\.svg\)/g, '](/flinttrade/logo.svg)');
  value = value.replace(/\]\(([^)\s]+)\)/g, (match, target) => {
    const rewritten = rewriteRepositoryLink(target, sourcePath);
    return rewritten ? `](${rewritten})` : match;
  });

  return value;
}

function rawRepositoryUrl(relativePath) {
  return `https://raw.githubusercontent.com/${repositoryOwner}/${repositoryName}/${repositoryRef}/${relativePath}`;
}

function repositoryApiUrl(relativePath) {
  return `https://api.github.com/repos/${repositoryOwner}/${repositoryName}/contents/${relativePath}?ref=${encodeURIComponent(repositoryRef)}`;
}

async function fetchRepositoryText(relativePath) {
  const response = await fetch(rawRepositoryUrl(relativePath), {
    headers: { 'User-Agent': 'flinttrade-site-generator' },
  });

  if (!response.ok) {
    throw new Error(`Unable to fetch ${relativePath} from GitHub at ${repositoryRef}: ${response.status}`);
  }

  return response.text();
}

async function fetchRepositoryBinary(relativePath) {
  const response = await fetch(rawRepositoryUrl(relativePath), {
    headers: { 'User-Agent': 'flinttrade-site-generator' },
  });

  if (!response.ok) {
    throw new Error(`Unable to fetch ${relativePath} from GitHub at ${repositoryRef}: ${response.status}`);
  }

  return Buffer.from(await response.arrayBuffer());
}

async function fetchRepositoryDirectory(relativePath) {
  const response = await fetch(repositoryApiUrl(relativePath), {
    headers: { 'User-Agent': 'flinttrade-site-generator' },
  });

  if (!response.ok) {
    throw new Error(`Unable to list ${relativePath} from GitHub at ${repositoryRef}: ${response.status}`);
  }

  const entries = await response.json();
  if (!Array.isArray(entries)) {
    throw new Error(`Expected ${relativePath} to be a GitHub directory listing.`);
  }

  return entries;
}

async function readRepositoryText(relativePath) {
  try {
    return await fs.readFile(path.join(repoRoot, relativePath), 'utf8');
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
    return fetchRepositoryText(relativePath);
  }
}

async function readVersionInfo() {
  const raw = await readRepositoryText('VERSION').catch(() => process.env.npm_package_version || '0.0.0-dev');
  const version = normaliseVersion(raw);
  return {
    version,
    versionTag: tagVersion(version),
    sourcePath: 'VERSION',
  };
}

async function listRepositoryDirectories(relativePath, fallbackNames) {
  try {
    const directory = path.join(repoRoot, relativePath);
    return (await fs.readdir(directory, { withFileTypes: true }))
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort();
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }

  try {
    const entries = await fetchRepositoryDirectory(relativePath);
    return entries
      .filter((entry) => entry.type === 'dir')
      .map((entry) => entry.name)
      .sort();
  } catch {
    return fallbackNames;
  }
}

async function listPackageReadmeDirectories() {
  const packageRoot = path.join(repoRoot, 'packages');
  const directories = [];

  async function walk(relativePath, depth) {
    if (depth > 3) return;

    const absolutePath = path.join(packageRoot, relativePath);
    const entries = await fs.readdir(absolutePath, { withFileTypes: true });
    const names = entries.map((entry) => entry.name);

    if (names.includes('README.md') && !relativePath.includes('.pytest_cache')) {
      directories.push(relativePath);
    }

    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      if (entry.name.startsWith('.') || entry.name === 'node_modules' || entry.name === 'dist') continue;
      await walk(path.posix.join(relativePath, entry.name), depth + 1);
    }
  }

  try {
    await walk('', 0);
    return directories.filter(Boolean).sort();
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
    return fallbackPackagePaths;
  }
}

async function listRepositoryFiles(relativePath, extension, fallbackFiles) {
  try {
    const directory = path.join(repoRoot, relativePath);
    return (await fs.readdir(directory))
      .filter((file) => file.endsWith(extension))
      .sort();
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }

  try {
    const entries = await fetchRepositoryDirectory(relativePath);
    return entries
      .filter((entry) => entry.type === 'file' && entry.name.endsWith(extension))
      .map((entry) => entry.name)
      .sort();
  } catch {
    return fallbackFiles;
  }
}

async function copyRepositoryFile(relativePath, destination) {
  try {
    await fs.mkdir(path.dirname(destination), { recursive: true });
    await fs.copyFile(path.join(repoRoot, relativePath), destination);
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
    await writeBinaryFileAtomic(destination, await fetchRepositoryBinary(relativePath));
  }
}

async function writeDocPage({ slug, title, description, body }) {
  const destination = path.join(contentRoot, `${slug}.mdx`);
  await fs.mkdir(path.dirname(destination), { recursive: true });
  const frontmatter = [
    '---',
    `title: "${escapeFrontmatter(title)}"`,
    `description: "${escapeFrontmatter(description)}"`,
    '---',
    '',
  ].join('\n');
  await writeFileAtomic(destination, `${frontmatter}${body.trim()}\n`);
}

async function readMarkdown(relativePath) {
  return readRepositoryText(relativePath);
}

async function buildPackageEntries() {
  const names = await listPackageReadmeDirectories();

  const packages = [];
  for (const name of names) {
    const readmePath = `packages/${name}/README.md`;
    const markdown = await readMarkdown(readmePath);
    const title = titleFromMarkdown(markdown, name);
    const description = descriptionFromMarkdown(markdown, `${name} package`);
    const slug = `packages/${name}`;

    packages.push({
      name,
      slug,
      title,
      description,
      sourcePath: readmePath,
      url: `/docs/${slug}`,
      headings: headingsFromMarkdown(markdown),
      content: markdown,
    });

    await writeDocPage({
      slug,
      title,
      description,
      body: removeFirstH1(normaliseMarkdown(markdown, readmePath)),
    });
  }

  return packages;
}

async function writePackageMetaFiles(packages) {
  const rootPages = [];
  const groupPages = new Map();

  for (const pkg of packages) {
    const parts = pkg.name.split('/');
    if (parts.length === 1) {
      rootPages.push(parts[0]);
      continue;
    }

    const group = parts[0];
    const page = parts.slice(1).join('/');
    if (!rootPages.includes(group)) {
      rootPages.push(group);
    }
    if (!groupPages.has(group)) {
      groupPages.set(group, []);
    }
    groupPages.get(group).push(page);
  }

  await writeFileAtomic(
    path.join(contentRoot, 'packages', 'meta.json'),
    JSON.stringify({
      title: 'Packages',
      pages: rootPages.sort(),
    }, null, 2),
  );

  for (const [group, pages] of groupPages.entries()) {
    await writeFileAtomic(
      path.join(contentRoot, 'packages', group, 'meta.json'),
      JSON.stringify({
        title: group,
        pages: pages.sort(),
      }, null, 2),
    );
  }
}

async function copyPublicAssets() {
  await fs.mkdir(path.join(publicRoot, 'screenshots'), { recursive: true });
  await copyRepositoryFile('docs/assets/logo.svg', path.join(publicRoot, 'logo.svg'));

  const screenshots = await listRepositoryFiles('docs/screenshots', '.png', fallbackScreenshotFiles);

  for (const screenshot of screenshots) {
    await copyRepositoryFile(`docs/screenshots/${screenshot}`, path.join(publicRoot, 'screenshots', screenshot));
  }

  return screenshots.map((file) => ({
    file,
    path: `/flinttrade/screenshots/${file}`,
  }));
}

async function main() {
  await fs.rm(contentRoot, { recursive: true, force: true });
  await fs.rm(generatedRoot, { recursive: true, force: true });
  await fs.rm(publicRoot, { recursive: true, force: true });

  await fs.mkdir(contentRoot, { recursive: true });
  await fs.mkdir(generatedRoot, { recursive: true });

  const versionInfo = await readVersionInfo();
  const docs = [];

  for (const [sourcePath, slug, area, fallbackDescription] of docsToGenerate) {
    const markdown = await readMarkdown(sourcePath);
    const title = titleFromMarkdown(markdown, path.basename(slug));
    const description = descriptionFromMarkdown(markdown, fallbackDescription);
    const body = removeFirstH1(normaliseMarkdown(markdown, sourcePath));

    docs.push({
      slug,
      title,
      description,
      area,
      sourcePath,
      url: `/docs/${slug === 'index' ? '' : slug}`,
      headings: headingsFromMarkdown(markdown),
      content: markdown,
    });

    await writeDocPage({ slug, title, description, body });
  }

  for (const doc of manualDocs) {
    docs.push({
      ...doc,
      url: `/docs/${doc.slug}`,
      headings: [],
    });
    await writeDocPage({
      slug: doc.slug,
      title: doc.title,
      description: doc.description,
      body: doc.content,
    });
  }

  const packages = await buildPackageEntries();
  const screenshots = await copyPublicAssets();

  await writeFileAtomic(
    path.join(contentRoot, 'meta.json'),
    JSON.stringify({
      title: 'FlintTrade Docs',
      pages: [
        'index',
        'disclaimer',
        'user-guide',
        'developer-guide',
        'architecture',
        'api',
        'compatibility',
        'order-safety',
        'ci',
        'references',
        'setup',
        'releases',
        'packages',
        'mcp',
        'contributing',
      ],
    }, null, 2),
  );

  await writeFileAtomic(
    path.join(contentRoot, 'setup', 'meta.json'),
    JSON.stringify({
      title: 'Setup',
      pages: [
        'quickstart',
        'macos',
        'linux',
        'windows',
        'raspberry-pi',
        'static-ip-setup',
        'email',
        'backup',
        'multi-user',
      ],
    }, null, 2),
  );

  await writeFileAtomic(
    path.join(contentRoot, 'releases', 'meta.json'),
    JSON.stringify({
      title: 'Releases',
      pages: releasePages,
    }, null, 2),
  );

  await writePackageMetaFiles(packages);

  const commands = [
    { label: 'Install project dependencies', command: 'make setup' },
    { label: 'Start terminal and OpenAlgo', command: 'make dev' },
    { label: 'Run all Python tests', command: 'make test' },
    { label: 'Run focused terminal build', command: 'cd packages/apps/terminal && npm run build' },
    { label: 'Run terminal unit tests', command: 'cd packages/apps/terminal && npm run test' },
    { label: 'Run site checks', command: 'cd packages/apps/site && npm run typecheck && npm run test && npm run build' },
  ];

  const docsIndex = {
    version: versionInfo.version,
    versionTag: versionInfo.versionTag,
    generatedAt: new Date().toISOString(),
    docs,
    packages,
    commands,
  };

  await writeFileAtomic(path.join(generatedRoot, 'docs-index.json'), JSON.stringify(docsIndex, null, 2));
  await writeFileAtomic(path.join(generatedRoot, 'packages-index.json'), JSON.stringify(packages, null, 2));
  await writeFileAtomic(path.join(generatedRoot, 'version.json'), JSON.stringify(versionInfo, null, 2));
  await writeFileAtomic(
    path.join(generatedRoot, 'site-summary.json'),
    JSON.stringify({
      screenshots,
      heroScreenshots: [
        '/flinttrade/screenshots/01-welcome.png',
        '/flinttrade/screenshots/04-trade.png',
        '/flinttrade/screenshots/08-ai.png',
        '/flinttrade/screenshots/06-lab.png',
      ],
    }, null, 2),
  );

  const llms = [
    '# FlintTrade',
    '',
    `Version: ${versionInfo.versionTag}`,
    '',
    'Open-source self-hosted trading software built with Python, React, TypeScript, and Rust.',
    '',
    '## Core docs',
    ...docs.map((doc) => `- [${doc.title}](/docs/${doc.slug === 'index' ? '' : doc.slug}): ${doc.description}`),
    '',
    '## Packages',
    ...packages.map((pkg) => `- ${pkg.name}: ${pkg.description} (${pkg.sourcePath})`),
    '',
    '## MCP scope',
    'The public MCP surface is read-only and limited to documentation, package orientation, test recommendations, and contribution planning.',
  ].join('\n');

  const llmsFull = [
    llms,
    '',
    '## Full documentation extracts',
    ...docs.map((doc) => `\n### ${doc.title}\nSource: ${doc.sourcePath}\n\n${doc.content.trim()}\n`),
    '',
    '## Package extracts',
    ...packages.map((pkg) => `\n### ${pkg.title}\nSource: ${pkg.sourcePath}\n\n${pkg.content.trim()}\n`),
  ].join('\n');

  await writeFileAtomic(path.join(siteRoot, 'public', 'llms.txt'), `${llms}\n`);
  await writeFileAtomic(path.join(siteRoot, 'public', 'llms-full.txt'), `${llmsFull}\n`);
}

withGenerationLock(main).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
