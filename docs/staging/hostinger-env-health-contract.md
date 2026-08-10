# Public-site environment and readiness contract

## Scope

This contract applies only to `packages/apps/site`. It covers repository-local installation, generation, testing, building, serving, and smoke verification. It does not define backend, broker, gateway, order-path, credential, account, domain, payment, or production configuration.

## Required environment

The basic documentation and marketing build requires no operator-supplied environment variables. Frozen installation and a successful site build are sufficient for the base application artifact.

Install-script redirect features are a separate readiness class. They require one valid source revision value:

| Variable | Precedence | Validation | Failure behaviour |
| --- | --- | --- | --- |
| `FLINTTRADE_SITE_SOURCE_SHA` | Preferred | Exactly 40 hexadecimal characters | Install-script responses fail closed with HTTP 503 |
| `VERCEL_GIT_COMMIT_SHA` | Fallback | Exactly 40 hexadecimal characters | Used only when the preferred value is absent or invalid |

The base application may be ready while install-script redirects remain unavailable.

## Optional environment

| Variable | Default | Effect |
| --- | --- | --- |
| `FLINTTRADE_REPO_ROOT` | Repository top level derived from the site package | Overrides content-generation source location |
| `VERCEL_GIT_COMMIT_REF` | `main` | Labels generated content when no source revision is supplied |
| `npm_package_version` | `0.0.0-dev` | Supplies a version fallback during content generation |
| `FLINTTRADE_SKIP_DEMO` | Unset | Value `1` skips browser-demo generation |
| `FLINTTRADE_SITE_ORIGIN` | Development origin selected by the application | Controls the accepted browser origin for CSP reports |
| `FLINTTRADE_GLITCHTIP_URL` | Unset | Adds an error-reporting destination to `connect-src` |
| `NODE_ENV` | Selected by Next.js | Controls framework development or production behaviour |

No `NEXT_PUBLIC_*` value is required by the supported public-site surface.

## Demo environment isolation

The public browser demo must not inherit terminal configuration. The demo generator:

1. excludes every inherited variable whose name starts with `VITE_`;
2. disables Vite dotenv loading through the supported `envDir` configuration;
3. uses the active Node executable with Vite's JavaScript entry point;
4. fails if Vite does not produce `dist/index.html`.

The integration test writes a synthetic terminal `.env.production`, builds the demo through the real generator, scans emitted JavaScript for the sentinel, and restores the filesystem in a `finally` block.

## Readiness probes

Provide an origin and service unit appropriate to the candidate environment:

```bash
export SITE_ORIGIN="https://staging.example.invalid"
export SITE_SERVICE_UNIT="flinttrade-site.service"
```

Execute each probe separately:

```bash
curl --fail --head "$SITE_ORIGIN/"
curl --fail --head "$SITE_ORIGIN/demo-app/"
systemctl --user is-active "$SITE_SERVICE_UNIT"
```

The root and demo requests are the supported HTTP smoke probes. Service-manager status is evaluated separately. A future dedicated readiness endpoint is a prerequisite that needs separate reviewed implementation before any operator may depend on it.

## Fail-closed rules

Readiness is false when any required source revision is malformed for the feature that uses it, a build gate fails, a smoke probe fails, the service state is unexpected, or demo isolation detects the sentinel in emitted JavaScript.

Real secrets belong outside the repository. Do not commit dotenv files containing credentials or production values.
