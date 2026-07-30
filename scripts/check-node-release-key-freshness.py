#!/usr/bin/env python3
"""Fail while the pinned Node release key is expired, revoked or expiring soon.

Node's ``SHASUMS256.txt`` is signed by whichever release manager cut that
release, using their own personal GPG key with their own expiry. FlintTrade
mirrors one such key and pins its fingerprint, so the key is upstream state we
consume - it can be tracked and refreshed, never regenerated.

The failure this guards against is silent. ``gpg`` exits **0** for a signature
made by a key that has since expired, reporting the condition out of band as
``EXPKEYSIG`` rather than ``GOODSIG``. A verification that only checks the exit
status, or greps for "Good signature", therefore passes indefinitely against a
dead key. The pinned key expired on 2026-07-08 and nothing noticed.

Run it in CI on a schedule so the warning arrives before the pin goes stale::

    python scripts/check-node-release-key-freshness.py            # 30-day warning
    python scripts/check-node-release-key-freshness.py --days 60
    python scripts/check-node-release-key-freshness.py --offline  # skip the upstream fetch
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_MANIFEST = _REPO_ROOT / "packages/apps/desktop/resources/bootstrap/tool-manifest.json"
_CHECKSUMS = _REPO_ROOT / "packages/apps/desktop/resources/bootstrap/checksums"
_KEYSERVER = "https://keys.openpgp.org/vks/v1/by-fingerprint/"
_DEFAULT_WARNING_DAYS = 30
_FETCH_TIMEOUT_SECONDS = 30

# Status codes that mean the signature or its key is anything other than
# currently valid. gpg exits 0 for most of these, so they must be denied
# explicitly rather than inferred from the exit status.
_FATAL_STATUS = (
    "EXPKEYSIG",
    "REVKEYSIG",
    "EXPSIG",
    "ERRSIG",
    "BADSIG",
    "NO_PUBKEY",
    "KEYEXPIRED",
    "KEYREVOKED",
)


class KeyFreshnessError(RuntimeError):
    """The pinned Node release key is not currently trustworthy."""


def _fail(message: str) -> None:
    """Print a failure and exit non-zero.

    Args:
        message: The operator-facing explanation.
    """
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def _pinned_signature() -> dict[str, str]:
    """Return the signature block the bootstrap manifest pins.

    Returns:
        The ``fingerprint``, ``keySha256`` and ``sha256`` values.
    """
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    return manifest["generatedFrom"]["node"]["signature"]


def _mirrored_key() -> pathlib.Path:
    """Locate the single mirrored release key.

    Returns:
        The path to the ``.asc`` key.

    Raises:
        KeyFreshnessError: When there is not exactly one mirrored key.
    """
    keys = sorted(_CHECKSUMS.glob("node-release-*.asc"))
    if len(keys) != 1:
        raise KeyFreshnessError(
            f"expected exactly one mirrored Node release key, found {[key.name for key in keys]}"
        )
    return keys[0]


def _sha256(path: pathlib.Path) -> str:
    """Return the hex SHA-256 of *path*.

    Args:
        path: The file to digest.

    Returns:
        The lowercase hex digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _gpg_homedir_argument(home: pathlib.Path) -> str:
    """Render *home* in a form the local gpg build will accept.

    Git for Windows ships an MSYS gpg that cannot parse a ``C:\\...`` argument:
    it treats the drive letter as a relative segment and prepends the working
    directory, producing paths like ``/c/repo/C:\\Users\\...`` and failing with
    "no writable keyring found". ``cygpath`` performs the conversion that build
    expects, and its absence means gpg is a native build that wants the Windows
    path unchanged.

    Args:
        home: The throwaway GNUPGHOME.

    Returns:
        The homedir path as this gpg build expects it.
    """
    if sys.platform != "win32" or shutil.which("cygpath") is None:
        return str(home)
    converted = subprocess.run(
        ["cygpath", "-u", str(home)],
        capture_output=True,
        text=True,
        check=False,
    )
    if converted.returncode != 0 or not converted.stdout.strip():
        return str(home)
    return converted.stdout.strip()


def _gpg(home: pathlib.Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run gpg against an isolated keyring.

    Args:
        home: A throwaway GNUPGHOME.
        *arguments: Arguments after the homedir.

    Returns:
        The completed process.
    """
    return subprocess.run(
        ["gpg", "--homedir", _gpg_homedir_argument(home), "--batch", "--status-fd", "1", *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def _key_record(home: pathlib.Path, fingerprint: str) -> tuple[str, int | None]:
    """Return the validity flag and expiry for the imported key.

    Args:
        home: The keyring holding the imported key.
        fingerprint: The fingerprint the manifest pins.

    Returns:
        The ``pub`` validity field and its expiry as a Unix timestamp, if set.

    Raises:
        KeyFreshnessError: When the pinned fingerprint is not in the keyring.
    """
    listed = _gpg(home, "--list-keys", "--with-colons", fingerprint)
    if listed.returncode != 0:
        raise KeyFreshnessError(f"the pinned fingerprint {fingerprint} is not in the mirrored key")
    for line in listed.stdout.splitlines():
        if not line.startswith("pub:"):
            continue
        fields = line.split(":")
        expiry = int(fields[6]) if len(fields) > 6 and fields[6] else None
        return fields[1], expiry
    raise KeyFreshnessError("the mirrored key contains no primary public key")


def _upstream_key_differs(fingerprint: str, mirrored: pathlib.Path) -> bool:
    """Report whether the keyserver copy differs from the mirrored one.

    A difference is informational, not fatal: release managers extend expiry by
    republishing the same key, so drift here is exactly the signal that a
    refresh is available.

    Args:
        fingerprint: The pinned fingerprint.
        mirrored: The mirrored key file.

    Returns:
        ``True`` when the upstream copy differs, ``False`` when it matches or
        could not be fetched.
    """
    try:
        with urllib.request.urlopen(f"{_KEYSERVER}{fingerprint}", timeout=_FETCH_TIMEOUT_SECONDS) as response:
            upstream = response.read()
    except (urllib.error.URLError, TimeoutError) as error:
        print(f"note: could not reach the keyserver ({error}); skipping the drift check")
        return False
    return hashlib.sha256(upstream).hexdigest() != _sha256(mirrored)


def main() -> None:
    """Check the pinned key and the signature it is meant to validate."""
    parser = argparse.ArgumentParser(description="Check the pinned Node release key's freshness")
    parser.add_argument(
        "--days",
        type=int,
        default=_DEFAULT_WARNING_DAYS,
        help="Fail when the key expires within this many days (default: 30).",
    )
    parser.add_argument("--offline", action="store_true", help="Skip the upstream keyserver comparison.")
    args = parser.parse_args()

    if shutil.which("gpg") is None:
        _fail("gpg is not on PATH, so the pinned release key cannot be checked. Install gnupg.")

    try:
        signature = _pinned_signature()
        mirrored = _mirrored_key()
    except (KeyFreshnessError, KeyError, OSError) as error:
        _fail(str(error))
        return

    fingerprint = signature["fingerprint"]
    print(f"Pinned key   : {fingerprint} ({mirrored.name})")

    if _sha256(mirrored) != signature["keySha256"]:
        _fail(
            f"{mirrored.name} does not match the keySha256 pinned in the manifest. "
            "Regenerate the manifest rather than editing either by hand."
        )

    home = pathlib.Path(tempfile.mkdtemp(prefix="flinttrade-key-freshness-"))
    try:
        imported = _gpg(home, "--import", str(mirrored))
        if imported.returncode != 0:
            _fail(f"could not import {mirrored.name}: {imported.stderr.strip()}")

        try:
            validity, expiry = _key_record(home, fingerprint)
        except KeyFreshnessError as error:
            _fail(str(error))
            return

        if validity == "e":
            _fail(
                f"the pinned key expired on {dt.datetime.fromtimestamp(expiry or 0, tz=dt.UTC):%Y-%m-%d}. "
                "Node releases are signed by whichever manager cut them, so refresh the mirrored key - "
                "and note a newer release may be signed by a different manager entirely."
            )
        if validity == "r":
            _fail("the pinned key has been REVOKED. Do not ship against it; move to the current signer.")

        if expiry:
            remaining = dt.datetime.fromtimestamp(expiry, tz=dt.UTC) - dt.datetime.now(tz=dt.UTC)
            print(f"Expires      : {dt.datetime.fromtimestamp(expiry, tz=dt.UTC):%Y-%m-%d} ({remaining.days} days)")
            if remaining.days < args.days:
                _fail(f"the pinned key expires in {remaining.days} days, inside the {args.days}-day window.")
        else:
            print("Expires      : never")

        checksums = sorted(_CHECKSUMS.glob("node-v*-SHASUMS256.txt"))
        if len(checksums) != 1:
            _fail(f"expected exactly one pinned Node checksum file, found {[path.name for path in checksums]}")
        detached = checksums[0].with_suffix(".txt.sig")
        if not detached.is_file():
            _fail(f"{detached.name} is missing, so the pinned checksums cannot be verified")

        verified = _gpg(home, "--verify", str(detached), str(checksums[0]))
        fatal = [code for code in _FATAL_STATUS if f"[GNUPG:] {code}" in verified.stdout]
        if fatal:
            _fail(f"gpg reports {', '.join(fatal)} for {checksums[0].name}")
        if "[GNUPG:] GOODSIG " not in verified.stdout:
            _fail(f"gpg produced no GOODSIG for {checksums[0].name}; the key is not currently valid")
        if f"[GNUPG:] VALIDSIG {fingerprint} " not in verified.stdout:
            _fail(f"{checksums[0].name} does not validate against the pinned fingerprint {fingerprint}")
        print(f"Signature    : GOODSIG over {checksums[0].name}")
    finally:
        shutil.rmtree(home, ignore_errors=True)

    if not args.offline and _upstream_key_differs(fingerprint, mirrored):
        print(
            "note: the keyserver copy of this fingerprint differs from the mirrored one. "
            "That usually means the manager republished it with a later expiry - refresh the mirror."
        )

    print("OK: the pinned Node release key is currently valid.")


if __name__ == "__main__":
    main()
