export type DocHeading = {
  level: number;
  title: string;
};

export type DocEntry = {
  slug: string;
  title: string;
  description: string;
  area: string;
  sourcePath: string;
  url: string;
  headings: DocHeading[];
  content: string;
};

export type PackageEntry = {
  name: string;
  slug: string;
  title: string;
  description: string;
  sourcePath: string;
  url: string;
  headings: DocHeading[];
  content: string;
};

export type CommandEntry = {
  label: string;
  command: string;
};

export type DocsIndex = {
  version: string;
  versionTag: string;
  generatedAt: string;
  docs: DocEntry[];
  packages: PackageEntry[];
  commands: CommandEntry[];
};

export type SearchResult = {
  slug: string;
  title: string;
  description: string;
  area: string;
  sourcePath: string;
  url: string;
  score: number;
  highlights: string[];
};

export type TestRecommendation = {
  reason: string;
  commands: string[];
};
