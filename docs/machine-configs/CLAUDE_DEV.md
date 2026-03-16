# Machine: dev-machine — PRIMARY BUILD

Specs: Configure your own dev machine (GPU recommended for AI package)

Tools: VS Code + Claude Code (builds), GitHub Desktop (commits)

```bash
git checkout dev && git pull && git checkout -b feature/{pkg}-{name}
claude   # in VS Code terminal — builds features
make test && make lint
# commit via GitHub Desktop → PR to dev
```

DEVLOG: `## YYYY-MM-DD HH:MM IST | your-dev-hostname | @yourusername | VS Code | Claude Code (claude-opus-4-6) | branch | summary`
