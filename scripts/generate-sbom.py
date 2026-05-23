#!/usr/bin/env python3
"""Emit a minimal CycloneDX-compatible SBOM placeholder for release artefacts."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {"component": {"type": "application", "name": "flinttrade"}},
        "components": [],
    }
    Path("sbom.json").write_text(json.dumps(sbom, indent=2) + "\n", encoding="utf-8")
    print("sbom.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
