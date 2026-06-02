#!/usr/bin/env python3
"""Emit a minimal CycloneDX-compatible SBOM placeholder for release artefacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def render_sbom() -> str:
    """Return the current minimal CycloneDX SBOM document."""
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {"component": {"type": "application", "name": "flinttrade"}},
        "components": [],
    }
    return json.dumps(sbom, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="sbom.json",
        help="path to write; use '-' to print to stdout",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the output file is missing or stale",
    )
    args = parser.parse_args()

    rendered = render_sbom()
    if args.output == "-":
        print(rendered, end="")
        return 0

    output = Path(args.output)
    if args.check:
        if output.exists() and output.read_text(encoding="utf-8") == rendered:
            print(f"{output} up to date")
            return 0
        print(f"{output} is missing or stale")
        return 1

    output.write_text(rendered, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
