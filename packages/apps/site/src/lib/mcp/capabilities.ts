import { docsAndPackages, docsIndex, packageIndex } from './data';
import type { DocEntry, PackageEntry, SearchResult, TestRecommendation } from './types';

const TRADING_TOOL_BLOCKLIST = [
  'place_order',
  'order',
  'trade',
  'positionbook',
  'fund',
  'broker',
  'credential',
  'api_key',
];

export const DOCS_MCP_TOOL_NAMES = [
  'search_docs',
  'get_doc',
  'list_packages',
  'explain_repo_path',
  'recommend_tests',
  'make_contribution_plan',
] as const;

export const DOCS_MCP_PROMPT_NAMES = [
  'plan_contribution',
  'add_terminal_widget',
  'add_python_feature',
  'update_docs_for_change',
] as const;

export function assertDocsMcpSafety(): void {
  const names = [...DOCS_MCP_TOOL_NAMES, ...DOCS_MCP_PROMPT_NAMES].map((name) => name.toLowerCase());
  const unsafe = names.filter((name) => TRADING_TOOL_BLOCKLIST.some((blocked) => name.includes(blocked)));

  if (unsafe.length > 0) {
    throw new Error(`Docs MCP contains trading-oriented names: ${unsafe.join(', ')}`);
  }
}

function normalise(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9./_-]+/g, ' ').trim();
}

function tokens(value: string): string[] {
  return normalise(value).split(/\s+/).filter(Boolean);
}

function entryArea(entry: DocEntry | PackageEntry): string {
  return 'area' in entry ? entry.area : 'Packages';
}

function packageRoot(entry: PackageEntry): string {
  return entry.sourcePath.replace(/\/README\.md$/, '');
}

function findPackageForPath(cleanPath: string): PackageEntry | undefined {
  return packageIndex
    .filter((entry) => cleanPath === packageRoot(entry) || cleanPath.startsWith(`${packageRoot(entry)}/`))
    .sort((a, b) => packageRoot(b).length - packageRoot(a).length)[0];
}

function snippet(content: string, queryTokens: string[]): string[] {
  const lines = content.split('\n').map((line) => line.trim()).filter(Boolean);
  const matches = lines.filter((line) => {
    const lower = normalise(line);
    return queryTokens.some((token) => lower.includes(token));
  });

  return matches.slice(0, 3).map((line) => line.slice(0, 220));
}

export function searchDocs(query: string, area?: string): SearchResult[] {
  const queryTokens = tokens(query);
  const areaFilter = area ? normalise(area) : '';

  if (queryTokens.length === 0) return [];

  return docsAndPackages
    .filter((entry) => !areaFilter || normalise(entryArea(entry)).includes(areaFilter))
    .map((entry) => {
      const title = normalise(entry.title);
      const description = normalise(entry.description);
      const headings = normalise(entry.headings.map((heading) => heading.title).join(' '));
      const source = normalise(entry.sourcePath);
      const content = normalise(entry.content);

      const score = queryTokens.reduce((total, token) => {
        let next = total;
        if (title.includes(token)) next += 12;
        if (description.includes(token)) next += 7;
        if (headings.includes(token)) next += 5;
        if (source.includes(token)) next += 4;
        if (content.includes(token)) next += 1;
        return next;
      }, 0);

      return {
        slug: entry.slug,
        title: entry.title,
        description: entry.description,
        area: entryArea(entry),
        sourcePath: entry.sourcePath,
        url: entry.url,
        score,
        highlights: snippet(entry.content, queryTokens),
      };
    })
    .filter((result) => result.score > 0)
    .sort((a, b) => b.score - a.score || a.title.localeCompare(b.title))
    .slice(0, 8);
}

export function getDoc(slug: string): DocEntry | PackageEntry | undefined {
  const normalised = slug.replace(/^\/?docs\//, '').replace(/^\/+/, '').replace(/\/+$/, '') || 'index';
  return docsAndPackages.find((entry) => entry.slug === normalised);
}

export function listPackages(): PackageEntry[] {
  return packageIndex;
}

export function explainRepoPath(repoPath: string): string {
  const cleanPath = repoPath.replace(/^\.?\//, '');
  const pkg = findPackageForPath(cleanPath);

  if (pkg) {
    return `${cleanPath} belongs to the ${pkg.title} package. ${pkg.description} Source overview: ${pkg.sourcePath}.`;
  }

  if (cleanPath.startsWith('packages/apps/site')) {
    return 'packages/apps/site is the public Next.js + Fumadocs website and docs/contribution MCP app. Run its checks with cd packages/apps/site && npm run typecheck && npm run test && npm run build.';
  }

  if (cleanPath.startsWith('docs/')) {
    return 'docs/ is the canonical documentation source for the public site, llms files, and docs MCP index. Update it alongside behaviour changes.';
  }

  if (cleanPath.startsWith('.github/')) {
    return '.github/ contains public repository governance, issue templates, PR templates, and workflow definitions.';
  }

  if (cleanPath === 'Makefile' || cleanPath.startsWith('infra/') || cleanPath.startsWith('scripts/')) {
    return `${cleanPath} is operational repo infrastructure. Prefer existing Makefile targets and scripts over one-off commands.`;
  }

  return `${cleanPath} is not in a known FlintTrade package boundary. Start with docs/DEVELOPER_GUIDE.md and readme.md for orientation.`;
}

export function recommendTests(changedPaths: string[]): TestRecommendation {
  const paths = changedPaths.map((value) => value.replace(/^\.?\//, ''));
  const commands = new Set<string>();
  const reasons = new Set<string>();

  for (const changedPath of paths) {
    if (changedPath.startsWith('packages/apps/site/')) {
      reasons.add('Public website, generated docs, or docs MCP changed.');
      commands.add('cd packages/apps/site && npm run typecheck');
      commands.add('cd packages/apps/site && npm run test');
      commands.add('cd packages/apps/site && npm run build');
    } else if (changedPath.startsWith('packages/apps/terminal/')) {
      reasons.add('React terminal code or tests changed.');
      commands.add('cd packages/apps/terminal && npm run typecheck');
      commands.add('cd packages/apps/terminal && npm run test');
      commands.add('cd packages/apps/terminal && npm run build');
    } else if (changedPath.startsWith('packages/core/design-system/')) {
      reasons.add('Shared design-system package changed.');
      commands.add('cd packages/apps/terminal && npm run typecheck');
      commands.add('cd packages/apps/site && npm run typecheck');
    } else if (changedPath.startsWith('packages/core/ticks/')) {
      reasons.add('Rust/PyO3 tick processing changed.');
      commands.add('cd packages/core/ticks && cargo test');
    } else if (changedPath.startsWith('packages/')) {
      const changedPackage = findPackageForPath(changedPath);
      const packagePath = changedPackage ? packageRoot(changedPackage) : changedPath.split('/').slice(0, 3).join('/');
      reasons.add(`Python package ${packagePath.replace(/^packages\//, '')} changed.`);
      commands.add(`python -m pytest ${packagePath}/tests/ -v --import-mode=importlib`);
      commands.add('make lint');
    } else if (changedPath.startsWith('docs/') || changedPath.endsWith('.md')) {
      reasons.add('Documentation changed and should be reflected in the public site.');
      commands.add('cd packages/apps/site && npm run build');
    } else if (changedPath.startsWith('.github/')) {
      reasons.add('GitHub workflow or repository template changed.');
      commands.add('git diff --check');
    }
  }

  if (commands.size === 0) {
    reasons.add('General repository change.');
    commands.add('make full-check');
  }

  return {
    reason: [...reasons].join(' '),
    commands: [...commands],
  };
}

export function makeContributionPlan(goal: string): string {
  const results = searchDocs(goal);
  const recommended = recommendTests(results.map((result) => result.sourcePath));
  const docs = results.slice(0, 4).map((result) => `- ${result.title}: ${result.sourcePath}`).join('\n');
  const tests = recommended.commands.map((command) => `- ${command}`).join('\n');

  return [
    `Goal: ${goal}`,
    '',
    '1. Read the closest docs and package notes:',
    docs || '- docs/DEVELOPER_GUIDE.md',
    '',
    '2. Make the smallest code or documentation change that satisfies the goal.',
    '3. Update docs in the same change when public behaviour, setup, API, or contribution flow changes.',
    '4. Run focused checks before broad checks:',
    tests,
    '',
    '5. Open a conventional-commit PR with screenshots for UI changes and a short test list.',
  ].join('\n');
}
