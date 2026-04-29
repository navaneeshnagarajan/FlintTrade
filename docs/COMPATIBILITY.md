# FlintTrade — External Dependency Compatibility

> Tracks the upstream versions of independent projects that FlintTrade
> integrates with at runtime (broker gateway, multi-account mirror, AI
> agent gateway). These are NOT bundled with FlintTrade. End users
> install / run them as separate services; FlintTrade speaks to them
> over their public APIs.

## Tested-against versions

The matrix below records the upstream commit FlintTrade was last
end-to-end-tested against. New FlintTrade releases must be re-verified
when an upstream pin is bumped.

| External project | Role in FlintTrade | Upstream | Last-tested commit | Last-tested date | FlintTrade version |
|---|---|---|---|---|---|
| **OpenAlgo** | Broker gateway (33 brokers, REST + WebSocket) | [marketcalls/openalgo](https://github.com/marketcalls/openalgo) | `08c2a553` (`openalgo-strategy-builder` + 3 commits) | 2026-04-23 | v0.5.0-dev |
| **AlgoMirror** | Multi-account mirroring patterns (reference only — patterns absorbed into `packages/ditto/`) | [marketcalls/algomirror](https://github.com/marketcalls/algomirror) | `fa063e2` (`algomirror-postgres` + 10 commits) | 2026-04-19 | v0.5.0-dev |
| **OpenClaw** | Optional AI agent gateway (Telegram / WhatsApp transport, exec approval) | [openclaw/openclaw](https://github.com/openclaw/openclaw) | `8c4ecf42df` (`v2026.4.19-beta.2` + 6 commits) | 2026-04-19 | v0.5.0-dev |

## How FlintTrade talks to each

| External | Wire format | Default endpoint | Required? |
|---|---|---|---|
| OpenAlgo | REST (`/api/v1/...`) + WebSocket | `127.0.0.1:5000` REST, `127.0.0.1:8765` WS | **Yes** for live trading; explore + practice modes work without it |
| AlgoMirror | (no live integration — patterns absorbed) | n/a | **No** — historical reference only |
| OpenClaw | REST + Telegram/WhatsApp transports | `127.0.0.1:18789` (default) | **No** — only used when AI agent features are enabled |

## Minimum supported

FlintTrade does NOT enforce a hard minimum at runtime today. The matrix
above documents the pinned commits that have been verified
end-to-end. Older versions may work but are unsupported; newer
versions are expected to work but require re-test.

If you hit an integration mismatch, file the issue with both versions
listed (FlintTrade `git rev-parse HEAD` + the upstream `git rev-parse HEAD`).

## Where the test deps live

Cloned to `.local/external/` (gitignored). They are NOT shipped with
FlintTrade and are NOT required to use FlintTrade — they exist only
so FlintTrade contributors can run the integration test paths
locally.

```
.local/external/openalgo/      # marketcalls/openalgo
.local/external/algomirror/    # marketcalls/algomirror
.local/external/openclaw/      # openclaw/openclaw
```

To install them, run:

```bash
bash scripts/setup-test-deps.sh
```

The script clones each repo at the commit pinned in the matrix above.
Pass `--latest` to clone HEAD of each (useful when bumping the pin).

## Process for bumping a pin

1. `cd .local/external/<project>` and `git pull`.
2. Note the new commit hash + tag (`git rev-parse --short HEAD`,
   `git describe --tags --always`).
3. Run the FlintTrade integration tests against the new pin:
   ```bash
   make test
   ```
4. If anything regresses, either patch FlintTrade or roll back:
   ```bash
   git checkout <old-commit>
   ```
5. When green, update the matrix in this file (commit hash, date,
   tested-with FlintTrade version), and update `scripts/setup-test-deps.sh`
   so fresh clones land on the new pin by default.
6. Commit the matrix change as part of the FlintTrade change that
   relies on the upstream bump.

## Why these are NOT FlintTrade submodules anymore

Pre-2026-04-30 these were git submodules of FlintTrade under
`infra/openalgo`, `infra/algomirror`, `infra/openclaw`. That meant
every `git clone --recursive` of FlintTrade pulled ~312 MB of
unrelated upstream code. They were also load-bearing for `infra/`
scripts in ways that confused the boundary between "FlintTrade ships
this" and "FlintTrade depends on this".

The refactor:
- Removed the three submodule entries from `.gitmodules` (file deleted).
- Moved the working trees to `.local/external/` so existing local
  contributors keep them without re-cloning.
- Replaced bundled-install assumptions in `infra/install/`, `infra/systemd/`,
  `infra/nginx/`, etc. with prerequisite-style guidance.

End result: a fresh `git clone` of FlintTrade is ~312 MB lighter, and
the boundary between "ours" and "we integrate with this" is
unambiguous.
