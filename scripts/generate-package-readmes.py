"""Generate packages/<pkg>/README.md from templates/package-purposes.yml.

Run from repo root:
    python scripts/generate-package-readmes.py

Idempotent — overwrites existing READMEs.
"""

from __future__ import annotations

import posixpath
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


def link_from_package(pkg_path: str, target: str) -> str:
    """Return a repository-relative link target from a package README."""
    return posixpath.relpath(target, posixpath.join("packages", pkg_path))


def test_command(pkg_path: str, language: str) -> str:
    if pkg_path == "apps/site":
        return "cd packages/apps/site && npm run typecheck && npm run test && npm run build"
    if pkg_path == "apps/terminal":
        return "cd packages/apps/terminal && npm run test:base && npm run build"
    if pkg_path == "core/design-system":
        return "cd packages/core/design-system && npx tsc --noEmit"
    if language in {"Python", "Python + Numba"}:
        return f"python -m pytest packages/{pkg_path}/tests/ -v --import-mode=importlib"
    if language == "Rust + PyO3":
        return f"cd packages/{pkg_path} && cargo test"
    return f"# See packages/{pkg_path}/ for test instructions"


def install_command(pkg_path: str, language: str) -> str:
    if language.startswith("TypeScript"):
        return "pnpm install"
    if language == "Rust + PyO3":
        return f"uv pip install -e packages/{pkg_path}\ncd packages/{pkg_path} && cargo test"
    return f"uv pip install -e packages/{pkg_path}"


def render_readme(pkg_name: str, info: dict[str, object]) -> str:
    purpose = info["purpose"]
    language = info["language"]
    entry_points = info["entry_points"]

    assert isinstance(purpose, str)
    assert isinstance(language, str)
    assert isinstance(entry_points, list)

    # Human-friendly package title.
    package_leaf = pkg_name.split("/")[-1]
    title = package_leaf.replace("-", " ").title().replace("Ai", "AI")
    if package_leaf == "ticks":
        title = "Tick Engine"
    if pkg_name == "services/backtest":
        title = "Backtest Engine"
    if pkg_name == "apps/site":
        title = "@flinttrade/site"
    if pkg_name == "apps/terminal":
        title = "Terminal"
    if pkg_name == "core/design-system":
        title = "@flinttrade/design-system"

    test_cmd_rendered = test_command(pkg_name, language)
    install_cmd_rendered = install_command(pkg_name, language)
    developer_guide = link_from_package(pkg_name, "docs/DEVELOPER_GUIDE.md")
    architecture = link_from_package(pkg_name, "docs/ARCHITECTURE.md")
    user_guide = link_from_package(pkg_name, "docs/USER_GUIDE.md")
    contributing = link_from_package(pkg_name, "contributing.md")
    license_path = link_from_package(pkg_name, "LICENSE")

    entry_lines = "\n".join(f"- `{ep}`" for ep in entry_points)

    return f"""# {title}

> {purpose}

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source financial-market software monorepo built with Python, React, TypeScript, and Rust.

**Language:** {language}

## Public surface

{entry_lines}

(See the source for the full surface.)

## Install

This package is part of the FlintTrade monorepo. Install via the workspace from the repo root:

```bash
{install_cmd_rendered}
```

If you only want to use the package in isolation, the package's `pyproject.toml`,
`Cargo.toml`, or `package.json` lists its dependencies. The supported path is the
root workspace.

## Tests

```bash
{test_cmd_rendered}
```

For the full test matrix, see the contributor guide at [docs/DEVELOPER_GUIDE.md]({developer_guide}).

## How this fits in

This package's role in the wider FlintTrade architecture is documented in
[docs/ARCHITECTURE.md]({architecture}). For end-user features it powers, see
[docs/USER_GUIDE.md]({user_guide}).

## Contributing

Contributions welcome. Please read [`contributing.md`]({contributing}) at the repo root before opening a pull request.

## License

AGPL-3.0 — same as the parent repository. See [`LICENSE`]({license_path}) for the full text.
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
        pkg_dir = PACKAGES_DIR / Path(pkg_name)
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
