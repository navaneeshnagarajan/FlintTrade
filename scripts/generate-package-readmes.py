"""Generate packages/<pkg>/README.md from templates/package-purposes.yml.

Run from repo root:
    python scripts/generate-package-readmes.py

Idempotent — overwrites existing READMEs.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:
    sys.stderr.write(
        "PyYAML missing. Install with `pip install pyyaml` (or `uv add pyyaml`).\n"
    )
    sys.exit(1)


REPO_ROOT = Path(__file__).resolve().parent.parent
PURPOSES_FILE = REPO_ROOT / "templates" / "package-purposes.yml"
PACKAGES_DIR = REPO_ROOT / "packages"


# Test commands per package language family.
TEST_COMMANDS = {
    "Python": "python -m pytest packages/{pkg}/tests/ -v",
    "Python + Numba": "python -m pytest packages/{pkg}/tests/ -v",
    "TypeScript": "cd packages/{pkg} && npm test",
    "TypeScript + React 19": "cd packages/{pkg} && npx vitest run",
    "TypeScript + Rust": "cd packages/{pkg} && npm test  # plus `cargo test` in src-tauri/",
    "Rust + PyO3": "cd packages/{pkg} && cargo test",
}


def render_readme(pkg_name: str, info: dict[str, object]) -> str:
    purpose = info["purpose"]
    language = info["language"]
    entry_points = info["entry_points"]

    assert isinstance(purpose, str)
    assert isinstance(language, str)
    assert isinstance(entry_points, list)

    # Human-friendly package title.
    title = pkg_name.replace("-", " ").title().replace("Ai", "AI")
    if pkg_name == "tick-engine":
        title = "Tick Engine"
    if pkg_name == "backtest-engine":
        title = "Backtest Engine"
    if pkg_name == "chrome-extension":
        title = "Chrome Extension"

    test_cmd = TEST_COMMANDS.get(language, f"# See packages/{pkg_name}/ for test instructions")
    test_cmd_rendered = test_cmd.format(pkg=pkg_name)

    entry_lines = "\n".join(f"- `{ep}`" for ep in entry_points)

    return f"""# {title}

> {purpose}

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source modular trading platform for Indian F&O, commodities, and crypto.

**Language:** {language}

## Public surface

{entry_lines}

(See the source for the full surface.)

## Install

This package is part of the FlintTrade monorepo. Install via the workspace from the repo root:

```bash
# Python packages
uv pip install -e packages/{pkg_name}
```

If you only want to use the package in isolation, the project's `pyproject.toml` (or `Cargo.toml` / `package.json`) lists its dependencies.

## Tests

```bash
{test_cmd_rendered}
```

For the full test matrix, see the contributor guide at [docs/DEVELOPER_GUIDE.md](../../docs/DEVELOPER_GUIDE.md).

## How this fits in

This package's role in the wider FlintTrade architecture is documented in [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md). For end-user features it powers, see [docs/USER_GUIDE.md](../../docs/USER_GUIDE.md).

## Contributing

Contributions welcome. Please read [`CONTRIBUTING.md`](../../CONTRIBUTING.md) at the repo root before opening a pull request.

## License

AGPL-3.0 — same as the parent repository. See [`LICENSE`](../../LICENSE) for the full text.
"""


def main() -> int:
    if not PURPOSES_FILE.exists():
        sys.stderr.write(f"Purposes file not found: {PURPOSES_FILE}\n")
        return 1

    with PURPOSES_FILE.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    written = 0
    skipped = 0
    for pkg_name, info in data.items():
        pkg_dir = PACKAGES_DIR / pkg_name
        if not pkg_dir.exists():
            sys.stderr.write(f"Package directory missing: {pkg_dir}\n")
            skipped += 1
            continue
        readme_path = pkg_dir / "README.md"
        readme_path.write_text(render_readme(pkg_name, info), encoding="utf-8")
        written += 1

    print(f"Generated {written} package READMEs.")
    if skipped:
        print(f"Skipped {skipped} (missing package directories).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
