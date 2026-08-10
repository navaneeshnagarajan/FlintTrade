# Public-site reproducible verification contract

## Purpose

This contract defines commands and observable success criteria for the public-site preparation. It intentionally avoids machine-specific metadata and mutable historical counts.

All commands start from the repository top level and use the repository's exact package-manager version.

## Dependency integrity

```bash
npx --yes pnpm@10.34.5 install --frozen-lockfile
```

Success means the lockfile is accepted without modification and installation exits zero.

## Documentation policy

```bash
npx --yes pnpm@10.34.5 --filter @flinttrade/site exec vitest run src/lib/hostinger-public-docs.test.ts
```

Success means all five public Hostinger documents satisfy the evergreen-content, command-format, artifact, and readiness-probe assertions.

## Portable demo launcher and dotenv isolation

```bash
npx --yes pnpm@10.34.5 --filter @flinttrade/site exec vitest run src/lib/build-script.test.ts
```

Success means the production launcher executes through Node and Vite's JavaScript entry point, a synthetic value in terminal `.env.production` is absent from every emitted JavaScript file, and temporary files are restored or deleted after the test.

## Complete site gates

Execute one command per line:

```bash
npx --yes pnpm@10.34.5 --filter @flinttrade/site test
npx --yes pnpm@10.34.5 --filter @flinttrade/site typecheck
npx --yes pnpm@10.34.5 --filter @flinttrade/site build
```

Acceptance requires:

- the complete Vitest suite exits zero with no failed files or cases;
- TypeScript exits zero with no diagnostics;
- Next.js reports a successful production compilation;
- content and demo generation complete;
- all expected application routes are generated;
- the browser demo index exists.

## Repository checks

```bash
git diff --check
git status --short
```

The first command must produce no output. The second is used only to confirm the intended file set before committing. Repository hooks remain enabled for the commit.
