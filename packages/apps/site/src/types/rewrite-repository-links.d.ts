declare module '../../scripts/rewrite-repository-links.mjs' {
  export function splitLinkTarget(target: string): [string, string];

  export function resolveRelativeTarget(targetPath: string, sourcePath: string): string[];

  export function repositoryBrowseUrl(options: {
    owner: string;
    name: string;
    ref: string;
    repoPath: string;
    isDirectory: boolean;
  }): string;

  export function statRepositoryPath(
    repoRoot: string,
    relativePath: string,
  ): { isDirectory: boolean } | null;

  export function rewriteRepositoryLink(
    target: string,
    sourcePath: string,
    options: {
      repoRoot: string;
      owner: string;
      name: string;
      ref: string;
      docRouteBySourcePath: Map<string, string>;
      repositoryFileUrls?: Map<string, string>;
      onRepoPath?: (repoPath: string, url: string, isDirectory: boolean) => void;
    },
  ): string | null;

  export function rewriteMarkdownRepositoryLinks(
    markdown: string,
    sourcePath: string,
    options: {
      repoRoot: string;
      owner: string;
      name: string;
      ref: string;
      docRouteBySourcePath: Map<string, string>;
      repositoryFileUrls?: Map<string, string>;
      onRepoPath?: (repoPath: string, url: string, isDirectory: boolean) => void;
    },
  ): string;
}
