# Public-site local build manifest

## Scope

This manifest describes the reproducible local build for `@flinttrade/site`. It does not authorise remote publication, account access, credential use, domain changes, payment actions, production changes, broker access, or trading activity.

## Repository pins

| Item | Value | Source |
| --- | --- | --- |
| Package manager | `pnpm@10.34.5` | Root `package.json` |
| Node.js | `>=22.22.0` | Root `package.json` |
| Lockfile format | `9.0` | `pnpm-lock.yaml` |
| Site framework | Next.js `16.2.12` resolved | `pnpm-lock.yaml` |
| Site package | `@flinttrade/site` | Site `package.json` |

Install dependencies from the repository top level:

```bash
npx --yes pnpm@10.34.5 install --frozen-lockfile
```

## Build sequence

Execute one command per line:

```bash
npx --yes pnpm@10.34.5 --filter @flinttrade/site test
npx --yes pnpm@10.34.5 --filter @flinttrade/site typecheck
npx --yes pnpm@10.34.5 --filter @flinttrade/site build
```

The package lifecycle generates documentation content before each gate. The production build also generates the browser demo before invoking `next build --webpack`.

## Artifact layout

The supported result is a Node-served Next.js application:

```text
packages/apps/site/
├── .next/
│   ├── BUILD_ID
│   ├── server/
│   └── generated framework assets
├── public/
│   ├── demo-app/
│   │   ├── index.html
│   │   └── assets/
│   └── generated public content
└── package.json
```

The complete framework output, public files, and runtime dependencies form one deployable unit. Client-only fragments are not a site artifact.

A static export requires separate reviewed code before it can become a supported artifact. The existing Next.js configuration does not produce an export directory.

## Artifact assertions

Execute each assertion separately after a successful build:

```bash
test -f packages/apps/site/.next/BUILD_ID
test -d packages/apps/site/.next/server
test -f packages/apps/site/public/demo-app/index.html
test -f packages/apps/site/public/llms.txt
```

## Acceptance contract

The artifact is acceptable only when frozen installation, the complete site test suite, type checking, the Next.js build, demo environment isolation, documentation policy checks, and the assertions above all exit successfully.
