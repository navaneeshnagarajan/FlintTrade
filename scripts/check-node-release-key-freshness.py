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

Expiry is only half of it. **Revocation is upstream-only state**: when a signer
revokes their key, the revocation packet lands on the keyserver, never in the
copy we mirrored. Every check made against the mirrored bytes alone - the
import, the validity flag, the GOODSIG - keeps passing forever, because the
packet that would deny them simply is not in the file being read. So the
keyserver copy is fetched and *merged into the same keyring* before the
verdict, which is what ``gpg --refresh-keys`` does: gpg keeps the newest
self-signature, so a republished key with a later expiry stays valid, while a
revocation - which can never be withdrawn - turns the pin red.

Reachability is not trust. A keyserver that times out, 404s or serves an error
page tells us nothing about the key, so those cases print a note and leave the
mirrored copy's verdict standing; only a copy we could actually read and parse
is allowed to fail the run.

Run it in CI on a schedule so the warning arrives before the pin goes stale::

    python scripts/check-node-release-key-freshness.py            # 30-day warning
    python scripts/check-node-release-key-freshness.py --days 60
    python scripts/check-node-release-key-freshness.py --offline  # skip the upstream fetch
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import http.client
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
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


class KeyserverUnavailable(RuntimeError):
    """The keyserver's copy of the pinned key could not be obtained.

    Deliberately distinct from :class:`KeyFreshnessError`: this one says "we
    could not ask", not "the answer was bad". A timeout, a 404 or an unparseable
    body is an availability problem and must never redden the run, whereas a
    copy we read successfully that carries a revocation must.
    """


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


def _as_date(expiry: int | None) -> str:
    """Render a Unix expiry timestamp as an ISO date.

    Args:
        expiry: The expiry as a Unix timestamp, if set.

    Returns:
        The date in ``YYYY-MM-DD`` form.
    """
    return f"{dt.datetime.fromtimestamp(expiry or 0, tz=dt.UTC):%Y-%m-%d}"


def _days_remaining(expiry: int) -> int:
    """Return the whole days left before *expiry*.

    Args:
        expiry: The expiry as a Unix timestamp.

    Returns:
        The remaining days, negative once the moment has passed.
    """
    return (dt.datetime.fromtimestamp(expiry, tz=dt.UTC) - dt.datetime.now(tz=dt.UTC)).days


def _verify_detached(
    home: pathlib.Path,
    fingerprint: str,
    checksums: pathlib.Path,
    detached: pathlib.Path,
    source: str,
) -> None:
    """Deny anything other than a currently valid signature over *checksums*.

    Args:
        home: The keyring to verify against.
        fingerprint: The fingerprint the manifest pins.
        checksums: The signed checksum file.
        detached: Its detached signature.
        source: Operator-facing description of the keyring's provenance.
    """
    verified = _gpg(home, "--verify", str(detached), str(checksums))
    fatal = [code for code in _FATAL_STATUS if f"[GNUPG:] {code}" in verified.stdout]
    if fatal:
        _fail(f"gpg reports {', '.join(fatal)} for {checksums.name} against {source}")
    if "[GNUPG:] GOODSIG " not in verified.stdout:
        _fail(f"gpg produced no GOODSIG for {checksums.name} against {source}; the key is not currently valid")
    if f"[GNUPG:] VALIDSIG {fingerprint} " not in verified.stdout:
        _fail(f"{checksums.name} does not validate against the pinned fingerprint {fingerprint}")


def _fetch_upstream_key(fingerprint: str) -> bytes:
    """Fetch the keyserver's current copy of *fingerprint*.

    Args:
        fingerprint: The pinned fingerprint.

    Returns:
        The raw keyserver response.

    Raises:
        KeyserverUnavailable: When the keyserver could not be asked, or answered
            with nothing usable.
    """
    try:
        with urllib.request.urlopen(f"{_KEYSERVER}{fingerprint}", timeout=_FETCH_TIMEOUT_SECONDS) as response:
            fetched: bytes = response.read()
    # urllib raises URLError and HTTPError (both OSError subclasses) for DNS,
    # TLS, timeout and HTTP-status failures; http.client raises protocol errors
    # that are not OSError at all. Every one of them means "we could not ask".
    except (OSError, http.client.HTTPException) as error:
        raise KeyserverUnavailable(f"could not reach the keyserver ({error})") from error
    if not fetched.strip():
        raise KeyserverUnavailable("the keyserver returned an empty body")
    return fetched


def _merge_upstream_key(home: pathlib.Path, fingerprint: str, fetched: bytes) -> None:
    """Merge the keyserver's copy of the pinned key into the mirrored keyring.

    Args:
        home: The keyring already holding the mirrored key.
        fingerprint: The fingerprint the manifest pins.
        fetched: The raw keyserver response.

    Raises:
        KeyserverUnavailable: When the response is not an importable copy of the
            pinned key - a captive portal, an error page, or somebody else's
            key. None of those are evidence about the pin.
    """
    with tempfile.NamedTemporaryFile(prefix="flinttrade-upstream-key-", suffix=".asc", delete=False) as handle:
        handle.write(fetched)
        staged = pathlib.Path(handle.name)
    try:
        imported = _gpg(home, "--import", str(staged))
    finally:
        staged.unlink(missing_ok=True)

    # gpg emits IMPORT_OK for every key it processed, including one it merged no
    # new packets into, so its absence means the response was not the pinned key.
    wanted = fingerprint.replace(" ", "").upper()
    for line in imported.stdout.splitlines():
        if line.startswith("[GNUPG:] IMPORT_OK ") and line.split()[-1].upper() == wanted:
            return
    raise KeyserverUnavailable(
        f"the keyserver response was not an importable copy of {fingerprint} "
        f"({imported.stderr.strip() or 'gpg reported no IMPORT_OK for the pinned key'})"
    )


def _check_upstream_state(
    home: pathlib.Path,
    fingerprint: str,
    mirrored: pathlib.Path,
    checksums: pathlib.Path,
    detached: pathlib.Path,
    warning_days: int,
) -> None:
    """Re-run the verdict against the mirrored key merged with the upstream one.

    The mirrored bytes are a snapshot, and a revocation published after that
    snapshot was taken is not in them. Merging the keyserver's copy in is the
    only way to see it: gpg keeps the newest self-signature, so a republish with
    a later expiry stays valid, while a revocation packet flips the key to ``r``
    and every check below denies it.

    Args:
        home: The keyring already holding the mirrored key.
        fingerprint: The fingerprint the manifest pins.
        mirrored: The mirrored key file, for the drift comparison.
        checksums: The signed checksum file.
        detached: Its detached signature.
        warning_days: Fail when the merged key expires inside this many days.
    """
    try:
        fetched = _fetch_upstream_key(fingerprint)
        _merge_upstream_key(home, fingerprint, fetched)
    except KeyserverUnavailable as error:
        # Availability, not trust: say so loudly and keep the mirrored verdict.
        print(f"Upstream     : NOT CHECKED - {error}")
        return

    try:
        validity, expiry = _key_record(home, fingerprint)
    except KeyFreshnessError as error:
        _fail(str(error))
        return

    if validity == "r":
        _fail(
            "the keyserver copy of this fingerprint carries a REVOCATION the mirrored key does not. "
            "The signer has revoked this key, and a revocation is never withdrawn: do not ship "
            "against it, move to the current signer."
        )
    if validity == "e":
        _fail(
            f"the keyserver copy expires the pinned key on {_as_date(expiry)}, so the mirrored copy's "
            "expiry is stale. Refresh the mirrored key - and note a newer release may be signed by a "
            "different manager entirely."
        )
    if expiry and (remaining := _days_remaining(expiry)) < warning_days:
        _fail(f"the keyserver copy expires the pinned key in {remaining} days, inside the {warning_days}-day window.")

    _verify_detached(home, fingerprint, checksums, detached, "the keyserver copy of the key")

    if hashlib.sha256(fetched).hexdigest() != _sha256(mirrored):
        print(
            "Upstream     : differs from the mirrored key but is neither revoked nor expired. "
            "That usually means the manager republished it with a later expiry - refresh the mirror."
        )
    else:
        print("Upstream     : matches the mirrored key")


def main() -> None:
    """Check the pinned key and the signature it is meant to validate."""
    parser = argparse.ArgumentParser(description="Check the pinned Node release key's freshness")
    parser.add_argument(
        "--days",
        type=int,
        default=_DEFAULT_WARNING_DAYS,
        help="Fail when the key expires within this many days (default: 30).",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip the keyserver fetch. An upstream revocation cannot be seen without it.",
    )
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
                f"the pinned key expired on {_as_date(expiry)}. "
                "Node releases are signed by whichever manager cut them, so refresh the mirrored key - "
                "and note a newer release may be signed by a different manager entirely."
            )
        if validity == "r":
            _fail("the pinned key has been REVOKED. Do not ship against it; move to the current signer.")

        if expiry:
            remaining = _days_remaining(expiry)
            print(f"Expires      : {_as_date(expiry)} ({remaining} days)")
            if remaining < args.days:
                _fail(f"the pinned key expires in {remaining} days, inside the {args.days}-day window.")
        else:
            print("Expires      : never")

        checksums = sorted(_CHECKSUMS.glob("node-v*-SHASUMS256.txt"))
        if len(checksums) != 1:
            _fail(f"expected exactly one pinned Node checksum file, found {[path.name for path in checksums]}")
        detached = checksums[0].with_suffix(".txt.sig")
        if not detached.is_file():
            _fail(f"{detached.name} is missing, so the pinned checksums cannot be verified")

        _verify_detached(home, fingerprint, checksums[0], detached, "the mirrored key")
        print(f"Signature    : GOODSIG over {checksums[0].name}")

        # Everything above this line was computed from the checked-in bytes, in
        # which an upstream revocation cannot appear. This is the step that goes
        # and looks.
        if args.offline:
            print("Upstream     : NOT CHECKED - --offline was requested, so a later revocation is unseen")
        else:
            _check_upstream_state(home, fingerprint, mirrored, checksums[0], detached, args.days)
    finally:
        shutil.rmtree(home, ignore_errors=True)

    print("OK: the pinned Node release key is currently valid.")


if __name__ == "__main__":
    main()
