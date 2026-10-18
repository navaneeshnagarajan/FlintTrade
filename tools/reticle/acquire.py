"""Acquire hash-pinned public Reticle inputs, separately from offline execution.

No npm lifecycle, compiler, application, shell or browser is executed. Existing
archives are reusable only after independent correspondence to the public pins.
Extracted compiler/type files must also match qualification.json in full.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import tarfile
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


class NoArchiveRedirect(urllib.request.HTTPRedirectHandler):
    """An archive's declared URL is its identity; never contact another URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Unexpected primary archive redirect")


def download(url: str, algorithm: str, digest: bytes, target: Path) -> None:
    parsed = urllib.parse.urlsplit(url)
    if ((parsed.scheme, parsed.netloc) != ("https", "registry.npmjs.org")
            or parsed.geturl() != url or parsed.query or parsed.fragment
            or any(ord(char) <= 32 or ord(char) == 127 for char in url)
            or not parsed.path.startswith("/") or "\\" in url):
        raise RuntimeError("Only the primary HTTPS npm registry is admitted")
    if target.is_symlink():
        raise RuntimeError("Archive symlinks refused")
    if target.exists():
        raw = target.read_bytes()
    else:
        # Explicit opener: no inherited process-global opener or proxy policy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoArchiveRedirect())
        with opener.open(url, timeout=60) as response:
            if response.geturl() != url:
                raise RuntimeError("Unexpected primary archive redirect")
            raw = response.read()
    if algorithm not in {"sha512", "sha256", "sha1"} or hashlib.new(algorithm, raw).digest() != digest:
        raise RuntimeError("Public archive digest mismatch: " + target.name)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("reticle_setup", HERE / "setup.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Owned setup module missing")
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    pristine = json.loads((HERE / "pristine-archives.json").read_text())
    upgrades = json.loads((HERE / "reconstruction.json").read_text())["packages"]
    builders = json.loads((HERE / "build-archives.json").read_text())
    expected = json.loads((HERE / "qualification.json").read_text())["build_inputs"]
    if set(builders) != set(expected):
        raise RuntimeError("Incomplete compiler/type archive selection")
    for row in pristine:
        algorithm, encoded = row["integrity"].split("-", 1)
        download(row["url"], algorithm, base64.b64decode(encoded, validate=True), args.output / "pristine" / row["archive"])
    for group, rows in [("upgrades", upgrades), ("build", builders.values())]:
        for row in rows:
            download(row["url"], "sha256", bytes.fromhex(row["sha256"]), args.output / group / row["file"])
    for name, row in builders.items():
        target = args.output / "types" / name
        if target.is_symlink():
            raise RuntimeError("Compiler/type symlink root refused")
        if not target.exists():
            with tarfile.open(args.output / "build" / row["file"]) as archive:
                seen = set()
                for member in archive:
                    parts = Path(member.name).parts
                    if not parts or parts[0] != row["prefix"] or ".." in parts or not (member.isfile() or member.isdir()):
                        raise RuntimeError("Unsafe compiler/type archive member")
                    dest = target.joinpath(*parts[1:])
                    if dest in seen:
                        raise RuntimeError("Duplicate compiler/type archive member")
                    seen.add(dest)
                    if member.isdir():
                        dest.mkdir(parents=True, exist_ok=True)
                    else:
                        stream = archive.extractfile(member)
                        if stream is None:
                            raise RuntimeError("Missing compiler/type archive bytes")
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with dest.open("xb") as output:
                            output.write(stream.read())
                        dest.chmod(0o755 if member.mode & 0o111 else 0o644)
        if setup.inventory(target) != expected[name]:
            raise RuntimeError("Compiler/type file inventory mismatch: " + name)
    print(json.dumps({"pristine_archives": len(pristine), "upgrade_archives": len(upgrades),
                      "build_archives": len(builders), "build_inputs_verified": True,
                      "application_executed": False}))


if __name__ == "__main__":
    main()
