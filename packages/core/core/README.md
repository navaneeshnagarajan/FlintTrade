# Core

> Flask application, OpenAlgo client (45+ endpoints), config and workspace management, authentication service, and the WSGI prefix-stripper.

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source modular trading platform for Indian F&O, commodities, and crypto.

**Language:** Python

## Public surface

- `src/flinttrade_core/app.py — Flask app factory + blueprint registration`
- `src/flinttrade_core/openalgo_client.py — typed wrapper over OpenAlgo's REST API`
- `src/flinttrade_core/auth_service.py — argon2id passwords + Fernet TOTP + JWT issuance`
- `src/flinttrade_core/config.py / src/flinttrade_core/workspace.py — env + workspace.json loaders`

(See the source for the full surface.)

## Install

This package is part of the FlintTrade monorepo. Install via the workspace from the repo root:

```bash
uv pip install -e packages/core/core
```

If you only want to use the package in isolation, the package's `pyproject.toml`,
`Cargo.toml`, or `package.json` lists its dependencies. The supported path is the
root workspace.

## Tests

```bash
python -m pytest packages/core/core/tests/ -v --import-mode=importlib
```

For the full test matrix, see the contributor guide at [docs/DEVELOPER_GUIDE.md](../../../docs/DEVELOPER_GUIDE.md).

## How this fits in

This package's role in the wider FlintTrade architecture is documented in
[docs/ARCHITECTURE.md](../../../docs/ARCHITECTURE.md). For end-user features it powers, see
[docs/USER_GUIDE.md](../../../docs/USER_GUIDE.md).

## Contributing

Contributions welcome. Please read [`contributing.md`](../../../contributing.md) at the repo root before opening a pull request.

## License

AGPL-3.0 — same as the parent repository. See [`LICENSE`](../../../LICENSE) for the full text.
