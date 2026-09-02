# AI

> Local LLM client, RAG pipeline, multi-agent trading team, ML signal generation, and skill swarm.

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source self-hosted trading software monorepo built with Python, React, TypeScript, and Rust.

**Language:** Python

## Public surface

- `src/flinttrade_ai/llm_client.py - multi-provider LLM client (managed Ollama / NVIDIA / OpenAI / Anthropic / Groq)`
- `src/flinttrade_ai/rag_pipeline.py — optional local SQLite/NumPy retrieval-augmented generation`
- `src/flinttrade_ai/multi_agent.py — analyst chain + risk debate + ensemble selector`
- `src/flinttrade_ai/advisor.py — production advisor surface for the AI Centre route`

(See the source for the full surface.)

## Install

This package is part of the FlintTrade monorepo. Install via the workspace from the repo root:

```bash
uv pip install -e packages/services/ai
```

If you only want to use the package in isolation, the package's `pyproject.toml`,
`Cargo.toml`, or `package.json` lists its dependencies. The supported path is the
root workspace.

RAG storage, local sentence-transformer embeddings, and Crawl4AI scraping are
loaded only when those features are enabled and their libraries are installed in
the local environment. They are intentionally not locked into the default
workspace install, so the trading terminal and backend do not inherit unresolved
upstream advisories from optional AI tooling.

## Tests

```bash
python -m pytest packages/services/ai/tests/ -v --import-mode=importlib
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
