# Hostinger local test and build proof

**Task:** `t_87e751a0` — Run and document local tests and build proof
**Worktree:** `C:/Users/USER/Desktop/Trading/FlintTrade-wt-hostinger-local-staging-prep-e039`
**Host:** `WINDOWS_HOST` (Windows)
**Run window:** 2026-08-09T19:08:29+05:30 → 2026-08-09T19:14:48+05:30 (approx.)
**Git HEAD at env snapshot (before steps):** `141766eb33b066fa78f28425a39ff8f4f741ab88`
**Git HEAD at proof write:** `96253f0509d322d7e3e53605887b7c1d086f8207`
  (`96253f05 docs(staging): Hostinger local rollback and future teardown runbook (non-production)` — concurrent sibling staging-docs commit landed on this worktree while the suite ran; JS/Python trees exercised below were already present at `141766eb`.)

**Toolchain (env snapshot):**
- Node `v26.5.0` (engines pin `>=22.22.0`)
- pnpm `10.34.5` (`packageManager` pin)
- System Python on PATH: `C:\Program Files\Python314\python.exe` (3.14)
- Worktree `.venv` **absent** at session start; created via `uv sync --frozen` before step 5 (see §5a)

**Raw logs (verbatim machine capture):**
`(internal kanban evidence directory)`

| Log file | Step |
|---|---|
| `00-env.txt` | Environment snapshot |
| `01-pnpm-install-frozen.txt` | Frozen pnpm install |
| `02-pnpm-site-test.txt` | `@flinttrade/site` test |
| `03-pnpm-site-typecheck.txt` | `@flinttrade/site` typecheck |
| `04-pnpm-site-build.txt` | `@flinttrade/site` build (full, including demo asset list) |
| `05a-uv-sync-frozen.txt` | Prerequisite: create worktree `.venv` |
| `05b-gateway-preflight.txt` | Cleared-env Python import preflight |
| `05-gateway-test-no-legacy-order-path.txt` | Gateway legacy-order-path pytest |

**Scope note:** This proof is local non-production evidence only. No Hostinger account, DNS, domain, secret, broker, or trading mutation was performed.

---

## Summary table (evidence-backed only)

| # | Command | Exit code | Result counts / markers |
|---|---|---|---|
| 1 | `pnpm install --frozen-lockfile` | **0** | Lockfile up to date; Done in 2s using pnpm v10.34.5 |
| 2 | `pnpm --filter @flinttrade/site test` | **0** | pretest `generate:content` ran; Test Files **13 passed (13)**; Tests **124 passed (124)** |
| 3 | `pnpm --filter @flinttrade/site typecheck` | **0** | pretypecheck `generate:content` ran; `tsc --noEmit` completed with no reported errors |
| 4 | `pnpm --filter @flinttrade/site build` | **0** | prebuild content+demo; Next.js 16.2.12 webpack; Compiled successfully; 60/60 static pages; route table emitted |
| 5a | `uv sync --frozen` (prerequisite; `.venv` missing) | **0** | Created `.venv`; Installed 135 packages |
| 5 | pytest `test_no_legacy_order_path.py` (cleared env + worktree `.venv`) | **0** | collected **53** items; **53 passed** in 175.99s |

No step was skipped. Claims below rest on the quoted exit codes and pass counts only.

---

## 0) Environment snapshot (before steps)

**Command:** shell env dump to `00-env.txt`

```text
=== host ===
WINDOWS_HOST
=== date ===
2026-08-09T19:08:29+05:30
=== cwd ===
/c/Users/navan/Desktop/Trading/FlintTrade-wt-hostinger-local-staging-prep-e039
=== git HEAD ===
141766eb33b066fa78f28425a39ff8f4f741ab88
=== node ===
v26.5.0
=== pnpm ===
10.34.5
/c/Users/navan/AppData/Roaming/npm/pnpm
=== python ===
/c/Program Files/Python314/python
/c/Users/navan/AppData/Local/Microsoft/WindowsApps/python3
no .venv python
=== PYTHONPATH/VIRTUAL_ENV ===
PYTHONPATH=C:\Users\USER\AppData\Local\hermes\hermes-agent;C:\Users\USER\AppData\Local\hermes\hermes-agent\venv\Lib\site-packages
VIRTUAL_ENV=
```

Leaked `PYTHONPATH` from the Hermes agent session is intentional context for step 5 (must be cleared before pytest).

---

## 1) Frozen pnpm install

**Working directory:** worktree root
**Command (exact):**

```text
pnpm install --frozen-lockfile
```

**Stdout/stderr (verbatim):**

```text
Scope: all 5 workspace projects
Lockfile is up to date, resolution step is skipped
Progress: resolved 1, reused 0, downloaded 0, added 0
Packages: +1
+
Progress: resolved 1, reused 1, downloaded 0, added 1, done

Done in 2s using pnpm v10.34.5
EXIT_CODE=0
```

**Exit code:** `0`

---

## 2) `@flinttrade/site` test (`pnpm test`, not bare vitest)

**Working directory:** worktree root
**Command (exact):**

```text
pnpm --filter @flinttrade/site test
```

**Notes:**
- Package script is `"test": "vitest run"` with `"pretest": "npm run generate:content"`.
- Invoked via `pnpm --filter` so lifecycle hooks run. Bare `vitest` was **not** used.

**Stdout/stderr (verbatim, including pretest hook):**

```text
> @flinttrade/site@0.0.1 pretest C:\Users\USER\Desktop\Trading\FlintTrade-wt-hostinger-local-staging-prep-e039\packages\apps\site
> npm run generate:content

npm warn config ignoring workspace config at C:\Users\USER\Desktop\Trading\FlintTrade-wt-hostinger-local-staging-prep-e039\packages\apps\site/.npmrc
npm warn Unknown env config "npm-globalconfig". This will error in a future major version of npm. See `npm help npmrc` for supported config options.
npm warn Unknown env config "overrides". This will error in a future major version of npm. See `npm help npmrc` for supported config options.
npm warn Unknown env config "package-manager-strict-version". This will error in a future major version of npm. See `npm help npmrc` for supported config options.
npm warn Unknown env config "peer-dependency-rules". This will error in a future major version of npm. See `npm help npmrc` for supported config options.
npm warn Unknown env config "recursive". This will error in a future major version of npm. See `npm help npmrc` for supported config options.
npm warn Unknown env config "strict-peer-dependencies". This will error in a future major version of npm. See `npm help npmrc` for supported config options.
npm warn Unknown env config "verify-deps-before-run". This will error in a future major version of npm. See `npm help npmrc` for supported config options.
npm warn Unknown env config "verify-store-integrity". This will error in a future major version of npm. See `npm help npmrc` for supported config options.
npm warn Unknown env config "_jsr-registry". This will error in a future major version of npm. See `npm help npmrc` for supported config options.
npm notice run @flinttrade/site@0.0.1 generate:content
npm notice run node scripts/generate-content.mjs && fumadocs-mdx
[MDX] generated files in 16.868999999999915ms

> @flinttrade/site@0.0.1 test C:\Users\USER\Desktop\Trading\FlintTrade-wt-hostinger-local-staging-prep-e039\packages\apps\site
> vitest run


 RUN  v4.1.10 C:/Users/USER/Desktop/Trading/FlintTrade-wt-hostinger-local-staging-prep-e039/packages/apps/site


 Test Files  13 passed (13)
      Tests  124 passed (124)
   Start at  19:08:48
   Duration  4.91s (transform 616ms, setup 0ms, import 1.56s, tests 4.34s, environment 1ms)

EXIT_CODE=0
```

**Exit code:** `0`
**Pass counts:** 13/13 test files; 124/124 tests
**Hook evidence:** `pretest` → `npm run generate:content` executed before `vitest run`.

The `npm warn Unknown env config …` lines are ambient npm noise from the monorepo/pnpm environment; they did not change the exit code.

---

## 3) `@flinttrade/site` typecheck (`tsc --noEmit` via package script)

**Working directory:** worktree root
**Command (exact):**

```text
pnpm --filter @flinttrade/site typecheck
```

**Notes:**
- Package script is `"typecheck": "tsc --noEmit"` with `"pretypecheck": "npm run generate:content"`.

**Stdout/stderr (verbatim):**

```text
> @flinttrade/site@0.0.1 pretypecheck C:\Users\USER\Desktop\Trading\FlintTrade-wt-hostinger-local-staging-prep-e039\packages\apps\site
> npm run generate:content

npm warn config ignoring workspace config at C:\Users\USER\Desktop\Trading\FlintTrade-wt-hostinger-local-staging-prep-e039\packages\apps\site/.npmrc
npm warn Unknown env config "npm-globalconfig". This will error in a future major version of npm. See `npm help npmrc` for supported config options.
npm warn Unknown env config "overrides". This will error in a future major version of npm. See `npm help npmrc` for supported config options.
npm warn Unknown env config "package-manager-strict-version". This will error in a future major version of npm. See `npm help npmrc` for supported config options.
npm warn Unknown env config "peer-dependency-rules". This will error in a future major version of npm. See `npm help npmrc` for supported config options.
npm warn Unknown env config "recursive". This will error in a future major version of npm. See `npm help npmrc` for supported config options.
npm warn Unknown env config "strict-peer-dependencies". This will error in a future major version of npm. See `npm help npmrc` for supported config options.
npm warn Unknown env config "verify-deps-before-run". This will error in a future major version of npm. See `npm help npmrc` for supported config options.
npm warn Unknown env config "verify-store-integrity". This will error in a future major version of npm. See `npm help npmrc` for supported config options.
npm warn Unknown env config "_jsr-registry". This will error in a future major version of npm. See `npm help npmrc` for supported config options.
npm notice run @flinttrade/site@0.0.1 generate:content
npm notice run node scripts/generate-content.mjs && fumadocs-mdx
[MDX] generated files in 16.93229999999994ms

> @flinttrade/site@0.0.1 typecheck C:\Users\USER\Desktop\Trading\FlintTrade-wt-hostinger-local-staging-prep-e039\packages\apps\site
> tsc --noEmit

EXIT_CODE=0
```

**Exit code:** `0`
**Errors reported by `tsc`:** none (empty compiler output after `tsc --noEmit`).

---

## 4) `@flinttrade/site` build

**Working directory:** worktree root
**Command (exact):**

```text
pnpm --filter @flinttrade/site build
```

**Notes:**
- Package scripts: `"prebuild": "npm run generate:content && npm run generate:demo"`, `"build": "next build --webpack"`.
- Full console (including every Vite demo asset line) is preserved at
  `(internal kanban evidence directory)` (309 lines).
  Below: hooks, key success markers, route table, and exit code — not a truncated “pass” claim without exit evidence.

**Hook + demo build markers (verbatim excerpts):**

```text
> @flinttrade/site@0.0.1 prebuild C:\Users\USER\Desktop\Trading\FlintTrade-wt-hostinger-local-staging-prep-e039\packages\apps\site
> npm run generate:content && npm run generate:demo
…
npm notice run @flinttrade/site@0.0.1 generate:content
npm notice run node scripts/generate-content.mjs && fumadocs-mdx
[MDX] generated files in 17.22950000000003ms
…
npm notice run @flinttrade/site@0.0.1 generate:demo
npm notice run node scripts/generate-demo.mjs
[generate-demo] building terminal (vite build --base=/demo-app/)…
…
✓ built in 4.95s
[generate-demo] demo copied to C:\Users\USER\Desktop\Trading\FlintTrade-wt-hostinger-local-staging-prep-e039\packages\apps\site\public\demo-app

> @flinttrade/site@0.0.1 build C:\Users\USER\Desktop\Trading\FlintTrade-wt-hostinger-local-staging-prep-e039\packages\apps\site
> next build --webpack

▲ Next.js 16.2.12 (webpack)

[MDX] generated files in 20.148799999999937ms
  Creating an optimized production build ...
✓ Compiled successfully in 8.8s
  Running TypeScript ...
  Finished TypeScript in 5.3s ...
  Collecting page data using 3 workers ...
  Generating static pages using 3 workers (0/60) ...
…
✓ Generating static pages using 3 workers (60/60) in 947ms
  Finalizing page optimization ...
  Collecting build traces ...

Route (app)
┌ ƒ /
├ ƒ /_not-found
├ ƒ /api-reference
├ ƒ /api/csp-report
├ ƒ /api/desktop-release
├ ƒ /api/mcp
├ ƒ /api/search
├ ƒ /contribute
├ ƒ /demo
├ ƒ /docs/[[...slug]]
├ ƒ /download
├ ƒ /install.ps1
├ ƒ /install.sh
├ ƒ /mcp
├ ƒ /uninstall.ps1
├ ƒ /uninstall.sh
├ ƒ /web-install.ps1
└ ƒ /web-install.sh


ƒ Proxy (Middleware)

ƒ  (Dynamic)  server-rendered on demand

EXIT_CODE=0
```

**Exit code:** `0`

---

## 5) Gateway `test_no_legacy_order_path.py` (cleared env + worktree `.venv`)

### 5a) Prerequisite — worktree `.venv` was missing

Task text: *“using the worktree `.venv` if present”*.
At start, `ls` showed **no** `.venv` Python. A project venv was created from the frozen lock before pytest:

**Command (exact):**

```text
uv sync --frozen
```

**Result markers (verbatim tail / summary):**

```text
Using CPython 3.14.7 interpreter at: C:\Program Files\Python314\python.exe
Creating virtual environment at: .venv
…
Prepared 14 packages in 50.80s
Installed 135 packages in 12.43s
…
 + pytest==9.1.1
…
 + flinttrade-gateway==0.0.1 (from file:///C:/Users/USER/Desktop/Trading/FlintTrade-wt-hostinger-local-staging-prep-e039/packages/integrations/gateway)
…
EXIT_CODE=0
```

**Exit code:** `0`
**Interpreter after create:**
`.venv/Scripts/python.exe` present.

Full package list: `05a-uv-sync-frozen.txt`.

### 5b) Preflight — cleared leaked agent Python env

Session had:

```text
PYTHONPATH=C:\Users\USER\AppData\Local\hermes\hermes-agent;C:\Users\USER\AppData\Local\hermes\hermes-agent\venv\Lib\site-packages
```

**Command pattern (exact):**

```bash
WT="C:/Users/USER/Desktop/Trading/FlintTrade-wt-hostinger-local-staging-prep-e039"
env -u PYTHONPATH -u VIRTUAL_ENV -u PYTHONHOME -u UV_PROJECT_ENVIRONMENT \
  PATH="$WT/.venv/Scripts:/usr/bin:/c/Windows/System32:$PATH" \
  "$WT/.venv/Scripts/python.exe" -c "import sys; print('executable', sys.executable); import pydantic; print('pydantic', pydantic.__file__); import flinttrade_gateway; print('gateway', flinttrade_gateway.__file__)"
```

**Preflight output (verbatim):**

```text
=== preflight (cleared env) ===
executable C:\Users\USER\Desktop\Trading\FlintTrade-wt-hostinger-local-staging-prep-e039\.venv\Scripts\python.exe
pydantic C:\Users\USER\Desktop\Trading\FlintTrade-wt-hostinger-local-staging-prep-e039\.venv\Lib\site-packages\pydantic\__init__.py
gateway C:\Users\USER\Desktop\Trading\FlintTrade-wt-hostinger-local-staging-prep-e039\packages\integrations\gateway\src\flinttrade_gateway\__init__.py
```

Imports resolve inside the **worktree** `.venv` / packages, not the Hermes agent venv.

### 5c) Pytest run

**Working directory:** worktree root
**Command (exact):**

```bash
WT="C:/Users/USER/Desktop/Trading/FlintTrade-wt-hostinger-local-staging-prep-e039"
env -u PYTHONPATH -u VIRTUAL_ENV -u PYTHONHOME -u UV_PROJECT_ENVIRONMENT \
  PATH="$WT/.venv/Scripts:/usr/bin:/c/Windows/System32:$PATH" \
  "$WT/.venv/Scripts/python.exe" -m pytest \
  packages/integrations/gateway/tests/test_no_legacy_order_path.py \
  -v --import-mode=importlib
```

**Session header + collection (verbatim):**

```text
============================= test session starts =============================
platform win32 -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0 -- C:\Users\USER\Desktop\Trading\FlintTrade-wt-hostinger-local-staging-prep-e039\.venv\Scripts\python.exe
cachedir: .pytest_cache
Using --randomly-seed=2777304857
rootdir: C:\Users\USER\Desktop\Trading\FlintTrade-wt-hostinger-local-staging-prep-e039\packages\integrations\gateway
configfile: pyproject.toml
plugins: anyio-4.14.2, pyfakefs-6.2.0, asyncio-1.4.0, randomly-4.1.0, timeout-2.4.0, xdist-3.8.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 53 items
```

**Final summary line (verbatim):**

```text
======================= 53 passed in 175.99s (0:02:55) ========================
EXIT_CODE=0
```

**Exit code:** `0`
**Pass/fail counts:** **53 passed**, 0 failed, 0 skipped (none reported)
**Full per-test PASSED list:** `05-gateway-test-no-legacy-order-path.txt` (all 53 lines end in `PASSED`).

---

## Acceptance checklist

| Requirement | Met? | Evidence |
|---|---|---|
| Frozen pnpm install executed | Yes | §1, exit 0 |
| `pnpm test` for `@flinttrade/site` (not bare vitest) | Yes | §2; pretest hook ran |
| pretest `generate:content` ran | Yes | §2 `> pretest` / `[MDX] generated` |
| `pnpm typecheck` for `@flinttrade/site` (`tsc --noEmit`) | Yes | §3, exit 0 |
| `pnpm build` for `@flinttrade/site` | Yes | §4, exit 0 |
| Gateway `test_no_legacy_order_path.py` | Yes | §5c, 53 passed, exit 0 |
| Worktree `.venv` used when available | Yes after 5a | Created with `uv sync --frozen` then used |
| Cleared leaked `PYTHONPATH` / `VIRTUAL_ENV` | Yes | `env -u PYTHONPATH -u VIRTUAL_ENV …` |
| Results quoted with exit codes / pass counts | Yes | Every section |
| No success claim without exit/pass evidence | Yes | Summary table only cites measured codes |

---

## Artefacts

- This file: `docs/staging/hostinger-local-test-proof.md`
- Machine logs: `(internal kanban evidence directory)`
- Parent context: `(internal kanban evidence directory)`

**Non-claims:** This document does **not** assert Hostinger deploy readiness, production DNS health, broker connectivity, or remote staging smoke. It records the five local command steps requested by `t_87e751a0` only.
