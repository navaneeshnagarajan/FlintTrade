# Incident regression probes

These tests exercise the real normal Flask factory, durable incident/delivery
owners, System diagnostics component and browser transport, and the shipped
Guardian parser/native relay. Only external provider/OS transports are inert.
Submission is deliberately **not** treated as observed user delivery.

## Run

Use the project's installed Python and Node dependencies in a disposable,
no-egress environment with an empty HOME. Do not run against a saved workspace,
operator browser, existing server or real notification/provider configuration.
No network installation is part of these commands.

From the repository root:

```sh
uv run --offline --no-sync pytest packages/core/core/tests/test_system_incidents.py
```

From `packages/apps/terminal`:

```sh
pnpm exec vitest run src/services/__tests__/IncidentTransport.test.ts src/chrome/__tests__/SystemIncidents.test.tsx
pnpm exec playwright test --config playwright.incidents.config.ts
```

From `packages/apps/desktop`:

```sh
pnpm exec vitest run --config vitest.electron.config.ts electron/incident-delivery.integration.test.ts
```

The native and browser probes require the repository's populated `.venv`.
`FLINTTRADE_TEST_PYTHON` can select an already-installed equivalent interpreter.
Install the project's pinned Chromium ahead of time; the probe does not download
it. The browser test owns loopback ports 5100 and 5173 and refuses to reuse a
server. It creates its API key and workspace at runtime, runs one worker with no
retries and blocks service workers. Its Notification constructor only records
calls in memory. The native probe generates a fresh normal-factory stdout record
on every invocation and sends it to inert relay callbacks, never an OS API.

The browser fixture uses Vite plus the real factory API, not the full desktop
shell or a production static build. It proves this synthetic integration only;
it is not funded-provider, native OS paint or production-CSP acceptance.

## Outputs and maintenance

Browser JSON, JUnit, traces and child logs go to `test-results/incidents`.
`INCIDENT_PROBE_OUTPUT` and `INCIDENT_PROBE_CACHE` can relocate generated outputs
and the Vite cache when source is read-only. Native wire fixtures use a fresh
temporary directory and are deleted after the case. Never commit captured wire,
workspaces, generated reports or traces as fixtures.

The Python tests retain the complete 21-case normal-factory suite. The two UI
files retain eight cases, including the three permission/constructor parameter
instances. Keep their exact count, session-retirement/no-replay, permission,
request-drain, backpressure, retained failed-close and unknown-delivery oracles.
Do not replace the tested stores, request decoders or owners with doubles.
Normal-factory fixtures must close every acquired owner in teardown; a leaked
owner is not a reason to remove the exclusive incident-ownership fence.

Test source is licensed under the repository's GNU AGPL v3 (`LICENSE`). All
identities, recipients, log strings and API tokens in these fixtures are inert
synthetic test values, not operator records or stored credentials.
