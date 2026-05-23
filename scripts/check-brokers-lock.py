#!/usr/bin/env python3
"""Check broker SDK pins against requirements.lock when broker waves activate."""

from __future__ import annotations

import pathlib
import re
import sys
import tomllib

REPO = pathlib.Path(__file__).resolve().parents[1]
BROKERS_LOCK = REPO / "brokers.lock"
REQUIREMENTS_LOCK = REPO / "requirements.lock"
ACTIVATED_WAVES = {"dhanhq"}
YANKED_VERSIONS = {"dhanhq": {"2.1.0"}}

PIN_RE = re.compile(r"^([a-zA-Z0-9_.-]+)==([^\s;]+)")
HASH_RE = re.compile(r"--hash=sha256:([a-f0-9]{64})")


def _parse_requirements(text: str) -> dict[str, tuple[str, set[str]]]:
    pins: dict[str, tuple[str, set[str]]] = {}
    current: list[str] = []
    blocks: list[str] = []

    for line in text.splitlines():
        if PIN_RE.match(line):
            if current:
                blocks.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append("\n".join(current))

    for block in blocks:
        match = PIN_RE.match(block)
        if match:
            pins[match.group(1).lower()] = (match.group(2), set(HASH_RE.findall(block)))
    return pins


def main() -> int:
    data = tomllib.loads(BROKERS_LOCK.read_text(encoding="utf-8"))
    pins = _parse_requirements(REQUIREMENTS_LOCK.read_text(encoding="utf-8")) if REQUIREMENTS_LOCK.exists() else {}
    failures: list[str] = []
    for entry in data.get("broker", []):
        name = entry["name"].lower()
        if entry.get("version") in YANKED_VERSIONS.get(name, set()):
            failures.append(f"{name}: version {entry['version']} is yanked")
        activated = name in ACTIVATED_WAVES
        if activated:
            for field in ("version", "sha256", "licence", "licence_source", "sandbox_tested", "approved_by"):
                value = str(entry.get(field, ""))
                if not value or "PLACEHOLDER" in value:
                    failures.append(f"{name}: activated wave has placeholder {field}")
        if name in pins:
            version, hashes = pins[name]
            if entry["version"] != version:
                failures.append(f"{name}: brokers.lock {entry['version']} != requirements.lock {version}")
            sha = entry.get("sha256", "")
            if "PLACEHOLDER" not in sha and sha not in hashes:
                failures.append(f"{name}: sha256 not present in requirements.lock")
        elif activated:
            failures.append(f"{name}: missing from requirements.lock")
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
