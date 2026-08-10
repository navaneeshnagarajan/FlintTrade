# Hostinger non-production public-site preparation

## Purpose

This guide defines local preparation for the FlintTrade public website. It is limited to the `@flinttrade/site` package and does not authorise remote publication, account access, credential use, domain changes, payment actions, production changes, broker access, or trading activity.

## Toolchain

Use the versions declared by the repository:

- Node.js `>=22.22.0`
- pnpm `10.34.5`
- lockfile format `9.0`

From the repository top level, execute one command at a time:

```bash
npx --yes pnpm@10.34.5 install --frozen-lockfile
npx --yes pnpm@10.34.5 --filter @flinttrade/site test
npx --yes pnpm@10.34.5 --filter @flinttrade/site typecheck
npx --yes pnpm@10.34.5 --filter @flinttrade/site build
```

## Application artifact

The supported output is a Node-served Next.js application. The complete `.next` directory, the `public` directory, and the package runtime dependencies belong to one artifact and must stay together.

The build also generates the browser demo in `packages/apps/site/public/demo-app`. Demo generation invokes Vite through the active Node executable and Vite's JavaScript entry point. It disables Vite dotenv loading through the supported `envDir` configuration and excludes inherited `VITE_*` values so terminal dotenv files cannot configure the public demo.

A static export requires separate reviewed code before it can become a supported artifact. The repository configuration does not produce one.

## Readiness checks

Set these values for the locally served candidate:

```bash
export SITE_ORIGIN="https://staging.example.invalid"
export SITE_SERVICE_UNIT="flinttrade-site.service"
```

Check the rendered root page, the generated demo, and the service manager independently:

```bash
curl --fail --head "$SITE_ORIGIN/"
curl --fail --head "$SITE_ORIGIN/demo-app/"
systemctl --user is-active "$SITE_SERVICE_UNIT"
```

The two HTTP checks are application smoke probes. The service-manager check is a separate process-state check. A dedicated readiness endpoint is not part of this preparation; adding one requires its own reviewed implementation.

## Fail-closed conditions

Stop preparation if any of these conditions applies:

- frozen dependency installation fails;
- tests or type checking fail;
- the Next.js build fails;
- the demo index is absent;
- either smoke probe fails;
- the service manager does not report the expected state;
- a required value is unknown or unreviewed.

See `docs/staging/hostinger-env-health-contract.md` for environment details, `docs/staging/hostinger-local-build-manifest.md` for artifact details, and `docs/staging/hostinger-rollback-teardown-runbook.md` for reversible local cleanup.
