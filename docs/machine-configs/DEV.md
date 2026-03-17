# Development Machine (Nitro / Mac)

## Role

Write code, run tests, push to GitHub.
This machine does NOT start OpenAlgo or run trading services.

## Setup

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
cp .env.example .env
make setup
```

## Daily Workflow

```bash
git pull origin main
cat PLAN.md                    # Find next unchecked task
# ... implement the task ...
make test                      # 670+ tests must pass
npm run dev --prefix packages/terminal  # Preview UI on port 5173
# Update PLAN.md (check off task)
# Append to DEVLOG.md
git add -A && git commit -m "feat(pkg): description"
git push origin main
```

## Commands

| Command | What |
|---|---|
| `make test` | Run all 670+ Python tests |
| `make test-fast` | Stop on first failure |
| `make lint` | Run ruff linter |
| `npm run dev` (in packages/terminal/) | Start terminal dev server on port 5173 |
| `npm run build` (in packages/terminal/) | Production build |

## Does NOT

- Start OpenAlgo (that's the server's job)
- Execute live trades
- Modify `infra/openalgo/` submodule
- Deploy to production
