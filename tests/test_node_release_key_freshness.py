"""Tests for the pinned Node release key freshness gate.

``scripts/check-node-release-key-freshness.py`` is the only thing that notices
the pinned Node signing key going bad, and the failure it exists to catch is
invisible in the mirrored bytes. When a signer revokes their key the revocation
packet lands on the keyserver, never in the ``.asc`` this repository checked in,
so every check made against that file alone keeps reporting a valid key and a
GOODSIG forever. These tests build a throwaway signing key, revoke it the way a
real signer would, serve the revoked copy as the keyserver's answer, and require
the gate to go red.

The other half is just as load-bearing: an unreachable or unparseable keyserver
is an availability problem, not evidence about the key, and must never redden a
run. Reachability and trust are asserted separately here on purpose.

Every test is offline - the keyserver is always stubbed - but all of them need a
local ``gpg``, without which the whole module skips.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import os
import tempfile
import urllib.error
import urllib.request
from types import ModuleType, TracebackType
from typing import Any

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "check-node-release-key-freshness.py"

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(shutil.which("gpg") is None, reason="gpg is needed to build the fixture keys"),
]


def _load() -> ModuleType:
    """Import the check script as a module.

    Returns:
        The freshly imported module.
    """
    spec = importlib.util.spec_from_file_location("check_node_release_key_freshness", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclasses.dataclass(frozen=True)
class _Signer:
    """A throwaway release manager and the key states a real one can publish.

    Attributes:
        fingerprint: The generated key's fingerprint.
        mirrored: The key as this repository would have mirrored it.
        revoked: The same key after the signer published a revocation.
        renewed: The same key republished with a later expiry.
        shortened: The same key republished with a ten-day expiry.
        stranger: An unrelated key, as a keyserver mix-up would serve it.
        shasums: A stand-in ``SHASUMS256.txt``.
        signature: Its detached signature, made before any of the above.
    """

    fingerprint: str
    mirrored: bytes
    revoked: bytes
    renewed: bytes
    shortened: bytes
    stranger: bytes
    shasums: bytes
    signature: bytes


def _gpg(module: ModuleType, home: pathlib.Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run gpg against *home* with an empty passphrase.

    Args:
        module: The imported check module, for its homedir shim.
        home: A throwaway GNUPGHOME.
        *arguments: Arguments after the homedir.

    Returns:
        The completed process.
    """
    completed = subprocess.run(
        [
            "gpg",
            "--homedir",
            module._gpg_homedir_argument(home),
            "--batch",
            "--yes",
            "--pinentry-mode",
            "loopback",
            "--passphrase",
            "",
            *arguments,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, f"gpg {arguments} failed: {completed.stderr}"
    return completed


def _generate(module: ModuleType, home: pathlib.Path, uid: str) -> str:
    """Generate a signing key in *home* and return its fingerprint.

    Args:
        module: The imported check module.
        home: A throwaway GNUPGHOME.
        uid: The user id to put on the key.

    Returns:
        The new key's fingerprint.
    """
    home.mkdir(mode=0o700, exist_ok=True)
    _gpg(module, home, "--quick-generate-key", uid, "ed25519", "sign", "2y")
    listed = _gpg(module, home, "--list-keys", "--with-colons").stdout
    return next(line.split(":")[9] for line in listed.splitlines() if line.startswith("fpr:"))


def _export(module: ModuleType, home: pathlib.Path, fingerprint: str, into: pathlib.Path) -> bytes:
    """Export *fingerprint* from *home* as armoured bytes.

    gpg writes to a file rather than stdout so that Windows newline translation
    cannot corrupt the armour we are about to digest.

    Args:
        module: The imported check module.
        home: The keyring holding the key.
        fingerprint: The key to export.
        into: Where to write the export.

    Returns:
        The exported bytes.
    """
    _gpg(module, home, "--output", str(into), "--export", "--armor", fingerprint)
    return into.read_bytes()


@pytest.fixture(scope="module")
def module() -> ModuleType:
    """Return the imported check module."""
    return _load()


@pytest.fixture(scope="module")
def signer(module: ModuleType, tmp_path_factory: pytest.TempPathFactory) -> _Signer:
    """Build one throwaway signer and every published key state it can reach.

    Args:
        module: The imported check module.
        tmp_path_factory: pytest's session temp directory factory.

    Returns:
        The generated key material.
    """
    if os.name == "posix" and pathlib.Path("/tmp").exists():
        base_dir = "/tmp"
    else:
        base_dir = tempfile.gettempdir()
    with tempfile.TemporaryDirectory(prefix="node-release-key-", dir=base_dir) as tmp:
        workspace = pathlib.Path(tmp)
        home = workspace / "signer"
        fingerprint = _generate(module, home, "Test Release Manager <manager@example.invalid>")
        mirrored = _export(module, home, fingerprint, workspace / "mirrored.asc")

        shasums = workspace / "node-v22.23.2-SHASUMS256.txt"
        shasums.write_bytes(b"0" * 64 + b"  node-v22.23.2.tar.gz\n")
        signature = workspace / "node-v22.23.2-SHASUMS256.txt.sig"
        _gpg(module, home, "--output", str(signature), "--detach-sign", str(shasums))

        # A revocation certificate is written at generation time with a colon
        # inserted before the armour, precisely so it cannot be imported by
        # accident. Removing it is what a signer does to publish the revocation.
        certificate = (home / "openpgp-revocs.d" / f"{fingerprint}.rev").read_text(encoding="utf-8")
        published = workspace / "revocation.asc"
        published.write_text(
            "\n".join(line.removeprefix(":") for line in certificate.splitlines()),
            encoding="utf-8",
        )
        revoked_home = workspace / "revoked"
        revoked_home.mkdir(mode=0o700)
        _gpg(module, revoked_home, "--import", str(workspace / "mirrored.asc"))
        _gpg(module, revoked_home, "--import", str(published))
        revoked = _export(module, revoked_home, fingerprint, workspace / "revoked.asc")

        # Renewal and shortening both republish the primary key with a fresh
        # self-signature, which is how a release manager moves an expiry.
        _gpg(module, home, "--quick-set-expire", fingerprint, "4y")
        renewed = _export(module, home, fingerprint, workspace / "renewed.asc")
        _gpg(module, home, "--quick-set-expire", fingerprint, "10d")
        shortened = _export(module, home, fingerprint, workspace / "shortened.asc")

        other_home = workspace / "stranger"
        other_fingerprint = _generate(module, other_home, "Somebody Else <else@example.invalid>")
        stranger = _export(module, other_home, other_fingerprint, workspace / "stranger.asc")

        yield _Signer(
            fingerprint=fingerprint,
            mirrored=mirrored,
            revoked=revoked,
            renewed=renewed,
            shortened=shortened,
            stranger=stranger,
            shasums=shasums.read_bytes(),
            signature=signature.read_bytes(),
        )
    # Guaranteed cleanup after the yield (TemporaryDirectory context exits here)


def _pin(signer: _Signer, tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Lay out a bootstrap manifest and checksums directory pinning the mirror.

    Args:
        signer: The generated key material.
        tmp_path: The test's temp directory.

    Returns:
        The manifest path and the checksums directory.
    """
    checksums = tmp_path / "checksums"
    checksums.mkdir()
    (checksums / "node-release-test-manager.asc").write_bytes(signer.mirrored)
    (checksums / "node-v22.23.2-SHASUMS256.txt").write_bytes(signer.shasums)
    (checksums / "node-v22.23.2-SHASUMS256.txt.sig").write_bytes(signer.signature)

    manifest = tmp_path / "tool-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "generatedFrom": {
                    "node": {
                        "signature": {
                            "fingerprint": signer.fingerprint,
                            "keySha256": hashlib.sha256(signer.mirrored).hexdigest(),
                            "sha256": hashlib.sha256(signer.shasums).hexdigest(),
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return manifest, checksums


class _Response:
    """A minimal stand-in for the object ``urlopen`` returns."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _Response:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return False

    def read(self) -> bytes:
        """Return the stubbed body."""
        return self._body


def _run(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    signer: _Signer,
    tmp_path: pathlib.Path,
    *,
    answer: bytes | BaseException | None,
    days: int = 30,
    offline: bool = False,
) -> int | None:
    """Drive ``main()`` against the fixture pins and a stubbed keyserver.

    Args:
        module: The imported check module.
        monkeypatch: pytest's patcher.
        signer: The generated key material.
        tmp_path: The test's temp directory.
        answer: The keyserver's body, an exception to raise, or ``None`` to
            assert the keyserver is never contacted.
        days: The expiry warning window to pass through.
        offline: Whether to pass ``--offline``.

    Returns:
        The exit code, or ``None`` when the script completed successfully.
    """
    manifest, checksums = _pin(signer, tmp_path)
    monkeypatch.setattr(module, "_MANIFEST", manifest)
    monkeypatch.setattr(module, "_CHECKSUMS", checksums)

    def urlopen(*_args: Any, **_kwargs: Any) -> _Response:
        if answer is None:
            raise AssertionError("the keyserver must not be contacted")
        if isinstance(answer, BaseException):
            raise answer
        return _Response(answer)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    argv = ["check-node-release-key-freshness.py", "--days", str(days)]
    if offline:
        argv.append("--offline")
    monkeypatch.setattr(sys, "argv", argv)

    try:
        module.main()
    except SystemExit as exit_code:
        return int(exit_code.code or 0)
    return None


def test_an_upstream_revocation_fails(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    signer: _Signer,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The signer revoked the key after we mirrored it; the mirror cannot tell.

    This is the regression this gate exists for. The checked-in bytes are
    untouched, so the import, the validity flag and the detached signature all
    still look perfect - only the keyserver's copy carries the revocation.
    """
    code = _run(module, monkeypatch, signer, tmp_path, answer=signer.revoked)
    captured = capsys.readouterr()
    assert code == 1, captured.out
    assert "REVOCATION" in captured.err
    assert "GOODSIG over node-v22.23.2-SHASUMS256.txt" in captured.out


def test_an_upstream_expiry_inside_the_window_fails(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    signer: _Signer,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A signer who shortened the expiry upstream must not be masked by the mirror."""
    code = _run(module, monkeypatch, signer, tmp_path, answer=signer.shortened, days=30)
    captured = capsys.readouterr()
    assert code == 1, captured.out
    assert "keyserver copy expires the pinned key in" in captured.err
    assert "30-day window" in captured.err


def test_a_renewed_upstream_key_only_notes_the_drift(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    signer: _Signer,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Republishing with a later expiry is the good case: a note, never a failure."""
    code = _run(module, monkeypatch, signer, tmp_path, answer=signer.renewed)
    captured = capsys.readouterr()
    assert code is None, captured.err
    assert "differs from the mirrored key" in captured.out
    assert "refresh the mirror" in captured.out
    assert "OK:" in captured.out


def test_a_matching_upstream_key_passes(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    signer: _Signer,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The steady state: the keyserver serves exactly what we mirrored."""
    code = _run(module, monkeypatch, signer, tmp_path, answer=signer.mirrored)
    captured = capsys.readouterr()
    assert code is None, captured.err
    assert "Upstream     : matches the mirrored key" in captured.out


def test_an_unreachable_keyserver_is_reported_not_fatal(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    signer: _Signer,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Availability is not trust: a network blip must never redden the run."""
    code = _run(module, monkeypatch, signer, tmp_path, answer=urllib.error.URLError("no route to host"))
    captured = capsys.readouterr()
    assert code is None, captured.err
    assert "Upstream     : NOT CHECKED" in captured.out
    assert "could not reach the keyserver" in captured.out


def test_an_unparseable_keyserver_response_is_reported_not_fatal(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    signer: _Signer,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A captive portal or error page says nothing about the key."""
    code = _run(module, monkeypatch, signer, tmp_path, answer=b"<html><body>502 Bad Gateway</body></html>")
    captured = capsys.readouterr()
    assert code is None, captured.err
    assert "Upstream     : NOT CHECKED" in captured.out
    assert "not an importable copy" in captured.out


def test_a_keyserver_copy_of_another_key_is_reported_not_fatal(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    signer: _Signer,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A response for somebody else's key must not be read as a clean bill of health."""
    code = _run(module, monkeypatch, signer, tmp_path, answer=signer.stranger)
    captured = capsys.readouterr()
    assert code is None, captured.err
    assert "Upstream     : NOT CHECKED" in captured.out
    assert "not an importable copy" in captured.out


def test_offline_never_contacts_the_keyserver(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    signer: _Signer,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The per-PR lane runs ``--offline``; it must stay network-free and say so."""
    code = _run(module, monkeypatch, signer, tmp_path, answer=None, days=0, offline=True)
    captured = capsys.readouterr()
    assert code is None, captured.err
    assert "--offline was requested" in captured.out


def test_a_revoked_mirrored_key_fails(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    signer: _Signer,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Once the revocation reaches the mirror, the offline half must catch it too."""
    revoked = dataclasses.replace(signer, mirrored=signer.revoked)
    code = _run(module, monkeypatch, revoked, tmp_path, answer=None, days=0, offline=True)
    captured = capsys.readouterr()
    assert code == 1, captured.out
    assert "REVOKED" in captured.err
