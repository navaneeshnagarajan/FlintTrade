# About version inventory

Settings → About displays a small, provenance-labelled inventory of the primary
stack. It is an observation aid, not a dependency audit, broker attestation or
model qualification.

- **Frontend libraries:** React and ReactDOM expose their actual bundled runtime
  versions. Other primary libraries show the installed version resolved when the
  terminal was built. Declared package ranges appear separately.
- **Build tools and configured pins:** build-time Node.js, Vite, TypeScript and
  Tailwind versions are distinct from the configured Node.js/uv bootstrap,
  pnpm and Electron-shell pins. A deployment-supplied full commit hash is shown
  only when available. These describe the frontend build, not a remote backend.
- **Desktop:** new Electron shells expose immutable copies of Electron,
  Chromium, Node.js and V8 version strings. Browser sessions show not applicable;
  older shells show unavailable metadata. No process or environment object is
  exposed to the renderer.
- **Backend:** Python and SQLite are running versions. Primary Python packages,
  including the compiled Rust/Python tick extension, report distribution
  metadata without importing package code. Configured versions come from the
  backend checkout's lockfile and may differ from the frontend build.
- **Broker SDKs:** Dhan, Upstox, Kotak Neo and Groww show installed distribution
  versions separately from the backend's broker pins. Kotak's configured Git
  revision is distinct from any installed Git revision reported by distribution
  metadata. An optional release compatibility baseline remains separate from
  the configured runtime pin. A matching version does not establish source integrity or broker
  readiness. REST-only adapters have no third-party SDK distribution to report.
- **Ollama:** configured managed pin and reported loopback server version are
  separate. The bounded version-only read does not start or install Ollama,
  reconcile operation receipts, change ownership, download a model or run
  inference. A reply does not prove runtime ownership or model readiness.

Backend metadata endpoints remain authenticated and return `Cache-Control:
no-store`. About makes at most one request to each endpoint per mount/session,
with cancellation and a five-second client limit. The Ollama transport has a
shorter absolute deadline and never follows redirects. Demo sessions make no
backend/Ollama requests. Unavailable, unreported and non-responding observations
are labelled rather than replaced with configured values.

A packaged backend without a validated source checkout still reports installed
versions. Missing lockfiles leave configured pins unavailable; no arbitrary
filesystem location is searched for a replacement. Installed metadata may be
missing or unreadable, and is not proof that a package was loaded by the process.

Synthetic browser coverage lives in `e2e/about-versions.spec.ts`; its isolated
About-component fixture is not a production entry point. It uses the fail-closed
fixture registry and exercises populated, Demo and unavailable observations.
