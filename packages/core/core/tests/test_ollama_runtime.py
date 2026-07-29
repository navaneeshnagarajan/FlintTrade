from __future__ import annotations

import hashlib
import http.server
import io
import json
import os
import signal
import subprocess
import sys
import tarfile
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import zstandard
from filelock import Timeout as FileLockTimeout

import flinttrade_core.ollama_runtime as ollama_runtime
from flinttrade_core.ollama_runtime import (
    OllamaAsset,
    OllamaRuntime,
    OllamaRuntimeError,
    _asset_for_platform,
    _assets_for_platform,
    _download_asset,
    _extract_archive,
)

_PRODUCTION_LISTENER_OWNER = OllamaRuntime._listener_owned_by_process
_PRODUCTION_PORT_DISCOVERER = OllamaRuntime._discover_owned_loopback_port

_READINESS_CEILING_SECONDS = 30.0
"""Deadlock ceiling for a helper subprocess reaching its readiness signal.

Separate from :data:`_HANDOFF_CEILING_SECONDS` because it covers a different
failure mode: a real interpreter starting and importing a large module, which on
a contended host is genuinely slow. Measured here at roughly 1-3s typically, but
observed exceeding 10s while the machine was loaded — so this ceiling is
deliberately generous. It is not a budget; nothing asserts how much is used.
"""

_HANDOFF_CEILING_SECONDS = 5.0
"""Deadlock ceiling for every inter-thread and inter-process handshake below.

This is deliberately *not* a budget: nothing is asserted about how much of it is
consumed, and consuming more of it never changes an outcome. Each handshake is
signalled by an explicit ``threading.Event`` or marker file, so the ceiling only
exists to turn a genuine deadlock into a legible failure instead of a hung suite.
Tightening it *as a way to make an assertion pass* would reintroduce exactly the
wager on runner load that this module removed.

These handshakes are all signalled — an ``Event`` set by a thread already
running, or a helper polling a marker file every 10ms — so once the signal
happens they complete immediately. They need no allowance for interpreter
startup, which is why they are bounded far more tightly than
:data:`_READINESS_CEILING_SECONDS`.

The split exists because CI bounds the total. ``test.yml`` runs pytest with
``--timeout=60 --timeout-method=thread``, and the longest path here chains one
readiness wait with three handoffs — lease contention, thread join, then the
holder reap in ``finally``. A single shared 30s ceiling makes that worst case
120s, so pytest-timeout fires first and destroys the legible AssertionError
these constants exist to produce. 30 + 5 + 5 + 5 leaves a clear margin.
"""


class _DrivenClock:
    """A monotonic clock advanced explicitly by the test rather than by the host.

    The deadline-bounded paths in :mod:`flinttrade_core.ollama_runtime` read
    ``time.monotonic`` dozens of times per public call and bound several
    independent operations on one budget. ``OllamaRuntime.shutdown`` bounds an
    operation-control acquisition, a state-lock acquisition, a process teardown, a
    status snapshot and a worker wait on the single deadline derived from its
    ``timeout``, so asserting ``shutdown(timeout=0.05) is True`` against real time
    is a wager that a loaded runner finishes all of that inside 50 ms. It does not
    on a busy Windows agent, which is why the assertion failed in CI on commits
    that touched no file in this package.

    Freezing the clock and advancing it only where the production code genuinely
    waits pins the *logic*: the deadline crosses at the step under test and nowhere
    else, and neither the outcome nor the runtime of the test depends on wall time.

    The ``clock = iter((0.0, 2.0))`` idiom used by the integrity-hashing test is not
    usable on these paths — ``shutdown`` alone makes 25 ``time.monotonic`` calls and
    would exhaust a two-element iterator on the third.
    """

    def __init__(self, start: float = 0.0, *, max_driven_waits: int = 64) -> None:
        """Freeze a new clock.

        Args:
            start: Initial reading. ``time.monotonic``'s epoch is undefined, so any
                value is a legal stand-in; ``0.0`` keeps float noise smallest.
            max_driven_waits: Guard on :meth:`expire_wait`. A production wait loop
                that never converges fails loudly here instead of spinning.
        """
        self._start = float(start)
        self._now = float(start)
        self._max_driven_waits = max_driven_waits
        self.waits: list[float] = []

    @property
    def elapsed(self) -> float:
        """Return how much clock time the test has allowed to pass since ``start``."""
        return self._now - self._start

    def monotonic(self) -> float:
        """Return the current frozen reading, standing in for ``time.monotonic``."""
        return self._now

    def advance(self, seconds: float) -> None:
        """Move the clock forward.

        Args:
            seconds: Non-negative number of seconds to add to the reading.

        Raises:
            ValueError: If ``seconds`` is negative.
        """
        if seconds < 0:
            raise ValueError("a monotonic clock cannot move backwards")
        self._now += float(seconds)

    def expire_wait(self, timeout: float | None = None) -> bool:
        """Stand in for ``threading.Condition.wait``, reporting the wait as expired.

        The clock advances by exactly the requested timeout, so the caller's next
        ``deadline - time.monotonic()`` is non-positive and its loop takes the
        expiry branch — the behaviour a real wait would produce, minus the waiting.

        Args:
            timeout: Bounded wait requested by the production code.

        Returns:
            ``False``, matching ``Condition.wait`` on timeout expiry.

        Raises:
            AssertionError: If the wait is unbounded, or if the calling loop has not
                converged within ``max_driven_waits`` iterations.
        """
        if timeout is None:
            raise AssertionError("an unbounded condition wait cannot be driven by _DrivenClock")
        self.waits.append(float(timeout))
        if len(self.waits) > self._max_driven_waits:
            raise AssertionError(f"a driven wait loop did not converge within {self._max_driven_waits} waits")
        self.advance(timeout)
        return False

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Route the runtime module's ``time.monotonic`` through this clock."""
        monkeypatch.setattr(ollama_runtime.time, "monotonic", self.monotonic)

    def drive_condition(self, monkeypatch: pytest.MonkeyPatch, condition: threading.Condition) -> None:
        """Make every *bounded* wait on ``condition`` expire in clock time, not wall time.

        ``threading.Condition`` binds ``acquire``/``release`` as instance attributes
        and ``with condition:`` goes through the underlying lock, so patching ``wait``
        leaves ownership semantics untouched.

        Args:
            monkeypatch: Fixture used so the patch is undone at test teardown.
            condition: The runtime condition whose bounded waits should be driven.
        """
        monkeypatch.setattr(condition, "wait", self.expire_wait)


def _record_bounded_acquisitions(
    monkeypatch: pytest.MonkeyPatch,
    condition: threading.Condition,
) -> list[float]:
    """Record the timeout every deadline-bounded acquisition of ``condition`` asks for.

    ``OllamaRuntime._deadline_lock`` translates a remaining budget into
    ``lock.acquire(timeout=max(0.0, deadline - now))``. Capturing those arguments lets
    a test assert that an expired deadline became a non-blocking attempt, which is what
    "deadline bounded" actually means — a far stronger and more stable claim than
    measuring how many milliseconds the call took on the host.

    Args:
        monkeypatch: Fixture used so the patch is undone at test teardown.
        condition: The runtime condition to observe.

    Returns:
        A list that grows with each requested acquisition timeout, in call order.
    """
    requested: list[float] = []
    inner_acquire = condition.acquire

    def recording_acquire(blocking: bool = True, timeout: float = -1) -> bool:
        requested.append(timeout)
        return bool(inner_acquire(blocking, timeout))

    monkeypatch.setattr(condition, "acquire", recording_acquire)
    return requested


def _await_holder_readiness(holder: subprocess.Popen[str], ready_path: Path) -> None:
    """Block until a helper subprocess signals readiness, failing fast if it dies.

    The original form of this wait gave the helper a 2.0 second budget for
    interpreter startup plus importing ``filelock``, then asserted the marker file
    existed. A loaded runner exceeds that, and the resulting failure — a bare
    ``assert ready_path.exists()`` — said nothing about why. This is genuine
    cross-process scheduling nondeterminism that no injected clock can remove: a real
    interpreter has to really start. So the wait is made explicit instead of timed —
    it ends the moment the helper signals, ends immediately with the helper's exit
    code and stderr if the helper dies, and only falls back on a deadlock ceiling.

    The helper's stderr is drained on a daemon thread rather than read here. A
    pipe that nothing reads fills its OS buffer, and a child blocked writing to it
    never reaches the line that creates the marker — so the readiness wait would
    burn its whole ceiling and report "never signalled" for what is really a
    deadlock on the pipe. Draining concurrently keeps the diagnostic honest.

    Args:
        holder: The live helper process that will create ``ready_path``.
        ready_path: Marker file the helper writes once it holds its resource.

    Raises:
        AssertionError: If the helper exits before signalling, or never signals.
    """
    captured: list[str] = []
    if holder.stderr is not None:
        drain = threading.Thread(
            target=lambda stream: captured.append(stream.read()),
            args=(holder.stderr,),
            daemon=True,
        )
        drain.start()

    def _stderr() -> str:
        """Return whatever the helper wrote to stderr, without blocking."""
        return "".join(captured).strip() or "<no output>"

    deadline = time.monotonic() + _READINESS_CEILING_SECONDS
    while not ready_path.exists():
        exit_code = holder.poll()
        if exit_code is not None:
            raise AssertionError(
                f"lease holder exited with code {exit_code} before signalling readiness: {_stderr()}"
            )
        if time.monotonic() >= deadline:
            raise AssertionError(f"lease holder never signalled readiness within {_READINESS_CEILING_SECONDS}s")
        time.sleep(0.01)


def test_asset_manifest_selects_the_pinned_official_release() -> None:
    mac = _asset_for_platform(system="Darwin", machine="arm64")
    linux = _asset_for_platform(system="Linux", machine="x86_64")
    windows = _asset_for_platform(system="Windows", machine="AMD64")

    assert mac.name == "ollama-darwin.tgz"
    assert mac.sha256 == "3b12a49c6c4cbafd7ffba5ccba60cbf80274cdc22eea3ead79c646aba888174c"
    assert linux.name == "ollama-linux-amd64.tar.zst"
    assert linux.sha256 == "56362d7609dfa9e35aaebb7c9cab25605d8f0528ec3d5d585dc83d6642002bab"
    assert windows.name == "ollama-windows-amd64.zip"
    assert windows.sha256 == "56561a8f0a904483303c610e61af61c5a7b6f5496ce3707e207d25d4ff67b89e"
    assert mac.url.endswith(f"/v0.32.0/{mac.name}")
    assert mac.size_bytes == 145_356_966
    assert linux.size_bytes == 1_436_128_693
    assert windows.size_bytes == 1_503_047_573
    assert mac.max_extracted_bytes == 512 * 1024 * 1024
    assert linux.max_extracted_bytes == 6 * 1024 * 1024 * 1024
    assert windows.max_extracted_bytes == 6 * 1024 * 1024 * 1024

    rollback = _asset_for_platform(system="Darwin", machine="arm64", version="v0.31.2")
    assert rollback.sha256 == "d72381baa260f6ce014c8e942e605eac76cac5313fcb3401eaf5495f659cfd6d"
    assert rollback.url.endswith(f"/v0.31.2/{rollback.name}")


def test_asset_manifest_refuses_an_unsupported_architecture() -> None:
    with pytest.raises(OllamaRuntimeError, match="unsupported platform"):
        _asset_for_platform(system="Linux", machine="i686")


def test_linux_accelerator_overlays_are_pinned_to_the_same_release(tmp_path: Path) -> None:
    rocm = _assets_for_platform(system="Linux", machine="x86_64", accelerator="rocm")
    jetpack = _assets_for_platform(system="Linux", machine="arm64", accelerator="jetpack6")

    assert [asset.name for asset in rocm] == [
        "ollama-linux-amd64.tar.zst",
        "ollama-linux-amd64-rocm.tar.zst",
    ]
    assert rocm[1].sha256 == "f0fad39e184daab11d172a855580abd7338b2f049afa462435fee15d76b4e437"
    assert rocm[1].size_bytes == 1_047_646_096
    assert rocm[1].max_extracted_bytes == 5 * 1024 * 1024 * 1024
    assert [asset.name for asset in jetpack] == [
        "ollama-linux-arm64.tar.zst",
        "ollama-linux-arm64-jetpack6.tar.zst",
    ]
    assert jetpack[1].sha256 == "89244534ec56a68093334d3957dd968a53328a02a8f155cbabc1f977c7c4537b"

    runtime = OllamaRuntime(tmp_path, asset=rocm[0], overlay_assets=(rocm[1],))
    status = runtime._status_snapshot()
    assert status["package_variant"] == "rocm"
    assert "accelerator" not in status
    assert status["inference_processor"] is None


def test_platform_assets_refuse_an_incompatible_accelerator() -> None:
    with pytest.raises(OllamaRuntimeError, match="unsupported Ollama accelerator"):
        _assets_for_platform(system="Darwin", machine="arm64", accelerator="rocm")


def test_zip_extraction_rejects_parent_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "ollama.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escaped", b"not allowed")

    destination = tmp_path / "runtime"
    with pytest.raises(OllamaRuntimeError, match="unsafe archive path"):
        _extract_archive(archive, destination)

    assert not (tmp_path / "escaped").exists()


def test_zip_extraction_rejects_windows_drive_qualified_paths(tmp_path: Path) -> None:
    archive = tmp_path / "ollama.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("D:/escaped.exe", b"not allowed")

    with pytest.raises(OllamaRuntimeError, match="unsafe archive path"):
        _extract_archive(archive, tmp_path / "runtime")


def test_zip_extraction_publishes_only_inside_destination(tmp_path: Path) -> None:
    archive = tmp_path / "ollama.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")

    destination = tmp_path / "runtime"
    _extract_archive(archive, destination)

    assert (destination / "bin" / "ollama.exe").read_bytes() == b"binary"


def test_zip_extraction_enforces_a_hard_output_byte_cap(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "ollama.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    with pytest.raises(OllamaRuntimeError, match="extracted size limit"):
        _extract_archive(archive, tmp_path / "runtime", max_extracted_bytes=5)


def test_extraction_checks_live_capacity_before_writing_each_chunk(tmp_path: Path) -> None:
    archive = tmp_path / "ollama.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    checks: list[int] = []

    def ensure_capacity(next_bytes: int) -> None:
        checks.append(next_bytes)
        raise OllamaRuntimeError("insufficient free disk space during extraction")

    with pytest.raises(OllamaRuntimeError, match="free disk space during extraction"):
        _extract_archive(
            archive,
            tmp_path / "runtime",
            max_extracted_bytes=1024,
            ensure_capacity=ensure_capacity,
        )

    assert checks == [len(b"binary")]


def test_zip_extraction_enforces_a_hard_member_count(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "ollama.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
        bundle.writestr("lib/runtime.dll", b"library")
    monkeypatch.setattr(ollama_runtime, "_MAX_EXTRACTED_MEMBERS", 1, raising=False)

    with pytest.raises(OllamaRuntimeError, match="member limit"):
        _extract_archive(archive, tmp_path / "runtime")


def test_tgz_extraction_supports_the_official_macos_archive(tmp_path: Path) -> None:
    archive = tmp_path / "ollama-darwin.tgz"
    payload = b"binary"
    with tarfile.open(archive, "w:gz") as bundle:
        member = tarfile.TarInfo("ollama")
        member.size = len(payload)
        member.mode = 0o755
        bundle.addfile(member, io.BytesIO(payload))

    destination = tmp_path / "runtime"
    _extract_archive(archive, destination)

    assert (destination / "ollama").read_bytes() == payload


def test_tgz_extraction_rejects_parent_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "ollama-darwin.tgz"
    with tarfile.open(archive, "w:gz") as bundle:
        member = tarfile.TarInfo("../escaped")
        member.size = 1
        bundle.addfile(member, io.BytesIO(b"x"))

    with pytest.raises(OllamaRuntimeError, match="unsafe archive path"):
        _extract_archive(archive, tmp_path / "runtime")

    assert not (tmp_path / "escaped").exists()


def test_tgz_extraction_materialises_safe_internal_link_chain(tmp_path: Path) -> None:
    archive = tmp_path / "ollama-darwin.tgz"
    payload = b"dylib"
    with tarfile.open(archive, "w:gz") as bundle:
        binary = tarfile.TarInfo("libggml-base.0.15.3.dylib")
        binary.size = len(payload)
        binary.mode = 0o755
        bundle.addfile(binary, io.BytesIO(payload))
        version_link = tarfile.TarInfo("libggml-base.0.dylib")
        version_link.type = tarfile.SYMTYPE
        version_link.linkname = "libggml-base.0.15.3.dylib"
        bundle.addfile(version_link)
        link = tarfile.TarInfo("libggml-base.dylib")
        link.type = tarfile.SYMTYPE
        link.linkname = "libggml-base.0.dylib"
        bundle.addfile(link)

    destination = tmp_path / "runtime"
    _extract_archive(archive, destination)

    for name in ("libggml-base.0.dylib", "libggml-base.dylib"):
        materialised = destination / name
        assert materialised.read_bytes() == payload
        assert materialised.is_file()
        assert not materialised.is_symlink()


def test_tgz_extraction_rejects_an_internal_link_that_escapes_the_archive(tmp_path: Path) -> None:
    archive = tmp_path / "ollama-darwin.tgz"
    with tarfile.open(archive, "w:gz") as bundle:
        link = tarfile.TarInfo("lib/libollama.dylib")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        bundle.addfile(link)

    with pytest.raises(OllamaRuntimeError, match="unsafe archive link"):
        _extract_archive(archive, tmp_path / "runtime")


def test_tgz_extraction_rejects_an_internal_link_cycle(tmp_path: Path) -> None:
    archive = tmp_path / "ollama-darwin.tgz"
    with tarfile.open(archive, "w:gz") as bundle:
        first = tarfile.TarInfo("lib-a.dylib")
        first.type = tarfile.SYMTYPE
        first.linkname = "lib-b.dylib"
        bundle.addfile(first)
        second = tarfile.TarInfo("lib-b.dylib")
        second.type = tarfile.SYMTYPE
        second.linkname = "lib-a.dylib"
        bundle.addfile(second)

    with pytest.raises(OllamaRuntimeError, match="unsafe archive link"):
        _extract_archive(archive, tmp_path / "runtime")


def test_tgz_extraction_counts_materialised_links_towards_the_output_cap(tmp_path: Path) -> None:
    archive = tmp_path / "ollama-darwin.tgz"
    payload = b"dylib"
    with tarfile.open(archive, "w:gz") as bundle:
        binary = tarfile.TarInfo("libollama.1.dylib")
        binary.size = len(payload)
        bundle.addfile(binary, io.BytesIO(payload))
        link = tarfile.TarInfo("libollama.dylib")
        link.type = tarfile.SYMTYPE
        link.linkname = "libollama.1.dylib"
        bundle.addfile(link)

    with pytest.raises(OllamaRuntimeError, match="extracted size limit"):
        _extract_archive(archive, tmp_path / "runtime", max_extracted_bytes=(len(payload) * 2) - 1)


def test_tar_zst_extraction_supports_the_official_linux_archive(tmp_path: Path) -> None:
    tar_path = tmp_path / "ollama.tar"
    payload = b"linux-binary"
    with tarfile.open(tar_path, "w") as bundle:
        member = tarfile.TarInfo("bin/ollama")
        member.size = len(payload)
        member.mode = 0o755
        bundle.addfile(member, io.BytesIO(payload))
    archive = tmp_path / "ollama-linux-amd64.tar.zst"
    archive.write_bytes(zstandard.ZstdCompressor().compress(tar_path.read_bytes()))

    destination = tmp_path / "runtime"
    _extract_archive(archive, destination)

    assert (destination / "bin" / "ollama").read_bytes() == payload


def test_tar_zst_extraction_materialises_safe_internal_links(tmp_path: Path) -> None:
    tar_path = tmp_path / "ollama.tar"
    payload = b"linux-library"
    with tarfile.open(tar_path, "w") as bundle:
        library = tarfile.TarInfo("lib/ollama/libggml.so.1")
        library.size = len(payload)
        library.mode = 0o755
        bundle.addfile(library, io.BytesIO(payload))
        link = tarfile.TarInfo("lib/ollama/libggml.so")
        link.type = tarfile.SYMTYPE
        link.linkname = "libggml.so.1"
        bundle.addfile(link)
    archive = tmp_path / "ollama-linux-amd64.tar.zst"
    archive.write_bytes(zstandard.ZstdCompressor().compress(tar_path.read_bytes()))

    destination = tmp_path / "runtime"
    _extract_archive(archive, destination)

    materialised = destination / "lib" / "ollama" / "libggml.so"
    assert materialised.read_bytes() == payload
    assert not materialised.is_symlink()


def _fake_asset(archive: Path, *, sha256: str | None = None) -> OllamaAsset:
    return OllamaAsset(
        name=archive.name,
        sha256=sha256 or hashlib.sha256(archive.read_bytes()).hexdigest(),
        url="https://downloads.example.invalid/ollama.zip",
        size_bytes=archive.stat().st_size,
        max_extracted_bytes=64 * 1024 * 1024,
        executable_candidates=("bin/ollama.exe",),
    )


def _copy_download(source: Path):
    def download(_asset: OllamaAsset, destination: Path, progress: Any) -> None:
        payload = source.read_bytes()
        destination.write_bytes(payload)
        progress(len(payload), len(payload))

    return download


def _versioned_runtime(
    workspace: Path,
    archives: dict[str, Path],
    *,
    target_version: str,
    bad_version: str | None = None,
    probe: Any = None,
    request_json: Any = None,
) -> OllamaRuntime:
    releases = {
        version: (
            _fake_asset(
                archive,
                sha256="0" * 64 if version == bad_version else None,
            ),
        )
        for version, archive in archives.items()
    }

    def download(asset: OllamaAsset, destination: Path, progress: Any) -> None:
        source = next(archive for archive in archives.values() if archive.name == asset.name)
        payload = source.read_bytes()
        destination.write_bytes(payload)
        progress(len(payload), len(payload))

    return OllamaRuntime(
        workspace,
        releases=releases,
        target_version=target_version,
        downloader=download,
        probe=probe or (lambda: None),
        request_json=request_json,
    )


class _StreamingResponse:
    def __init__(self, chunks: list[bytes], *, content_length: str | None) -> None:
        self._chunks = iter(chunks)
        self.headers = {} if content_length is None else {"Content-Length": content_length}

    def __enter__(self) -> _StreamingResponse:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def read(self, _size: int) -> bytes:
        return next(self._chunks, b"")


def test_download_requires_the_exact_advertised_content_length(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    asset = OllamaAsset(
        name="runtime.zip",
        sha256="0" * 64,
        url="https://downloads.example.invalid/runtime.zip",
        max_extracted_bytes=1,
        size_bytes=5,
    )
    monkeypatch.setattr(
        ollama_runtime.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _StreamingResponse([b"four"], content_length="5"),
    )

    with pytest.raises(OllamaRuntimeError, match="Content-Length"):
        _download_asset(asset, tmp_path / "runtime.zip", lambda *_args: None)


def test_download_enforces_the_pinned_hard_byte_cap_without_a_length_header(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    asset = OllamaAsset(
        name="runtime.zip",
        sha256="0" * 64,
        url="https://downloads.example.invalid/runtime.zip",
        max_extracted_bytes=1,
        size_bytes=4,
    )
    monkeypatch.setattr(
        ollama_runtime.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _StreamingResponse([b"abc", b"de"], content_length=None),
    )
    destination = tmp_path / "runtime.zip"

    with pytest.raises(OllamaRuntimeError, match="size limit"):
        _download_asset(asset, destination, lambda *_args: None)

    assert destination.stat().st_size <= asset.size_bytes


def test_download_enforces_an_absolute_wall_clock_deadline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    asset = OllamaAsset(
        name="runtime.zip",
        sha256="0" * 64,
        url="https://downloads.example.invalid/runtime.zip",
        max_extracted_bytes=1,
        size_bytes=2,
    )
    clock = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(ollama_runtime, "_RUNTIME_DOWNLOAD_DEADLINE_SECONDS", 1.0)
    monkeypatch.setattr(ollama_runtime.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(
        ollama_runtime.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _StreamingResponse([b"a", b"b"], content_length="2"),
    )

    with pytest.raises(OllamaRuntimeError, match="download deadline"):
        _download_asset(asset, tmp_path / "runtime.zip", lambda *_args: None)


def test_install_rejects_hash_mismatch_without_publishing(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    asset = _fake_asset(archive, sha256="0" * 64)
    runtime = OllamaRuntime(tmp_path / "workspace", asset=asset, downloader=_copy_download(archive))

    with pytest.raises(OllamaRuntimeError, match="hash verification failed"):
        runtime.install()

    assert runtime.status()["installed"] is False
    assert not runtime.install_dir.exists()


def test_install_verifies_extracts_and_marks_executable(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    asset = _fake_asset(archive)
    runtime = OllamaRuntime(tmp_path / "workspace", asset=asset, downloader=_copy_download(archive))

    result = runtime.install()

    executable = runtime.install_dir / "bin" / "ollama.exe"
    assert result["installed"] is True
    assert executable.read_bytes() == b"binary"
    if os.name != "nt":
        assert executable.stat().st_mode & 0o100


def test_repeated_install_preserves_a_ready_managed_runtime(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    process = _FakeProcess()
    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        probe=lambda: "0.32.0" if process.poll() is None else None,
        listener_owner=lambda owned_process: owned_process is process,
    )
    runtime.install()
    runtime._process = process
    runtime._port = 43127
    runtime._phase = "ready"

    result = runtime.install()

    assert result["state"] == "ready"
    assert result["ready"] is True
    assert result["managed_process"] is True
    assert result["server_version"] == "0.32.0"
    assert runtime._phase == "ready"


def test_install_cancellation_during_manifest_hashing_does_not_publish(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
        bundle.writestr("lib/runtime.bin", b"runtime")
    asset = _fake_asset(archive)
    runtime = OllamaRuntime(tmp_path / "workspace", asset=asset, downloader=_copy_download(archive))
    hashing = threading.Event()
    release_hash = threading.Event()
    original_sha256_file = ollama_runtime._sha256_file

    def blocked_sha256(path: Path, **kwargs: Any) -> str:
        if "extracted" in path.parts and path.name == "ollama.exe":
            hashing.set()
            assert release_hash.wait(timeout=2.0)
            kwargs.pop("check_cancelled", None)
        return original_sha256_file(path, **kwargs)

    monkeypatch.setattr(ollama_runtime, "_sha256_file", blocked_sha256)
    queued = runtime.install_async(admission_id=f"adm_{'8' * 32}")
    operation_id = queued["operation"]["id"]
    assert hashing.wait(timeout=2.0)
    stop_result: list[dict[str, Any]] = []
    stop_failures: list[BaseException] = []

    def stop_runtime() -> None:
        try:
            stop_result.append(runtime.stop(timeout_seconds=2.0, expected_operation_id=operation_id))
        except BaseException as exc:  # pragma: no cover - asserted below
            stop_failures.append(exc)

    stopper = threading.Thread(target=stop_runtime)
    stopper.start()
    deadline = time.monotonic() + 2.0
    while not runtime._cancel_event.is_set() and time.monotonic() < deadline:
        time.sleep(0.01)
    release_hash.set()
    stopper.join(timeout=3.0)

    assert stopper.is_alive() is False
    assert stop_failures == []
    assert stop_result
    assert runtime.status()["operation"]["state"] == "cancelled"
    assert runtime.status()["installed"] is False
    assert runtime.install_dir.exists() is False


def test_install_hash_verifies_and_merges_a_pinned_accelerator_overlay(tmp_path: Path) -> None:
    base_archive = tmp_path / "base.zip"
    overlay_archive = tmp_path / "rocm.zip"
    with zipfile.ZipFile(base_archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    with zipfile.ZipFile(overlay_archive, "w") as bundle:
        bundle.writestr("lib/ollama/rocm/runtime.dll", b"rocm")
    base_asset = _fake_asset(base_archive)
    overlay_asset = OllamaAsset(
        name=overlay_archive.name,
        sha256=hashlib.sha256(overlay_archive.read_bytes()).hexdigest(),
        url="https://downloads.example.invalid/rocm.zip",
        max_extracted_bytes=64 * 1024 * 1024,
        size_bytes=overlay_archive.stat().st_size,
        executable_candidates=(),
    )

    def download(asset: OllamaAsset, destination: Path, progress: Any) -> None:
        source = base_archive if asset.name == base_asset.name else overlay_archive
        payload = source.read_bytes()
        destination.write_bytes(payload)
        progress(len(payload), len(payload))

    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=base_asset,
        overlay_assets=(overlay_asset,),
        downloader=download,
    )

    runtime.install()

    assert (runtime.install_dir / "bin" / "ollama.exe").read_bytes() == b"binary"
    assert (runtime.install_dir / "lib" / "ollama" / "rocm" / "runtime.dll").read_bytes() == b"rocm"
    assert runtime.status()["installed"] is True


def test_incomplete_install_without_completion_metadata_is_not_installed(tmp_path: Path) -> None:
    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=OllamaAsset(
            name="runtime.zip",
            sha256="0" * 64,
            url="https://downloads.example.invalid/runtime.zip",
            max_extracted_bytes=1,
            executable_candidates=("bin/ollama.exe",),
        ),
        probe=lambda: None,
    )
    executable = runtime.install_dir / "bin" / "ollama.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"unverified")

    status = runtime.status()

    assert status["installed"] is False
    assert status["state"] == "not_installed"


def test_start_rehashes_the_installed_executable_before_spawning(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    spawn_calls = 0

    def process_factory(*_args: Any, **_kwargs: Any) -> _ExitedProcess:
        nonlocal spawn_calls
        spawn_calls += 1
        return _ExitedProcess()

    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        process_factory=process_factory,
        probe=lambda: None,
    )
    runtime.install()
    (runtime.install_dir / "bin" / "ollama.exe").write_bytes(b"evil!!")

    with pytest.raises(OllamaRuntimeError, match="integrity verification failed"):
        runtime.start(timeout_seconds=0.1)

    assert spawn_calls == 0
    status = runtime.status()
    assert status["integrity_error"] == "managed Ollama runtime integrity verification failed"
    assert status["repair_allowed"] is True
    assert status["repair_blocked_reason"] is None


def test_start_rehashes_every_installed_runtime_file(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
        bundle.writestr("lib/runtime.dll", b"library")
    spawn_calls = 0

    def process_factory(*_args: Any, **_kwargs: Any) -> _ExitedProcess:
        nonlocal spawn_calls
        spawn_calls += 1
        return _ExitedProcess()

    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        process_factory=process_factory,
        probe=lambda: None,
    )
    runtime.install()
    (runtime.install_dir / "lib" / "runtime.dll").write_bytes(b"changed")

    with pytest.raises(OllamaRuntimeError, match="integrity verification failed"):
        runtime.start(timeout_seconds=0.1)

    assert spawn_calls == 0


@pytest.mark.parametrize("relative", (Path("."), Path("bin")))
def test_install_verification_rejects_reparse_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    relative: Path,
) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        probe=lambda: None,
    )
    runtime.install()
    reparse_inode = (runtime.install_dir / relative).lstat().st_ino
    production_check = runtime._path_is_reparse

    monkeypatch.setattr(
        runtime,
        "_path_is_reparse",
        lambda path_stat: path_stat.st_ino == reparse_inode or production_check(path_stat),
    )

    with pytest.raises(OllamaRuntimeError, match="managed Ollama path is unsafe"):
        runtime._verified_executable(rehash=True)


@pytest.mark.skipif(os.name != "nt", reason="Windows directory-junction assertion")
def test_install_verification_rejects_a_real_windows_junction(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    asset = _fake_asset(archive)
    donor = OllamaRuntime(
        tmp_path / "donor-workspace",
        asset=asset,
        downloader=_copy_download(archive),
        probe=lambda: None,
    )
    donor.install()
    runtime = OllamaRuntime(tmp_path / "workspace", asset=asset, probe=lambda: None)
    runtime.install_dir.parent.mkdir(parents=True)
    created = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(runtime.install_dir), str(donor.install_dir)],
        check=False,
        capture_output=True,
        text=True,
    )
    if created.returncode != 0:
        pytest.skip("Windows directory junctions are unavailable")

    assert runtime.install_dir.is_junction()
    with pytest.raises(OllamaRuntimeError, match="managed Ollama path is unsafe"):
        runtime._verified_executable(rehash=True)


def test_repair_quarantines_and_replaces_a_corrupt_install(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"replacement")
        bundle.writestr("lib/runtime.dll", b"library")
    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        probe=lambda: None,
    )
    corrupt_file = runtime.install_dir / "bin" / "ollama.exe"
    corrupt_file.parent.mkdir(parents=True)
    corrupt_file.write_bytes(b"corrupt")

    result = runtime.repair()

    assert result["installed"] is True
    assert corrupt_file.read_bytes() == b"replacement"
    assert not list(runtime.install_dir.parent.glob(".repair-*"))


def test_repair_restores_the_original_corrupt_install_when_reinstall_fails(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"replacement")
    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=_fake_asset(archive, sha256="0" * 64),
        downloader=_copy_download(archive),
        probe=lambda: None,
    )
    corrupt_file = runtime.install_dir / "bin" / "ollama.exe"
    corrupt_file.parent.mkdir(parents=True)
    corrupt_file.write_bytes(b"original-corrupt-tree")

    with pytest.raises(OllamaRuntimeError, match="original install was restored"):
        runtime.repair()

    assert corrupt_file.read_bytes() == b"original-corrupt-tree"
    assert not list(runtime.install_dir.parent.glob(".repair-*"))
    assert runtime.status()["unresolved_operation"] is None
    assert runtime.status()["operation"]["state"] == "failed"


def test_unproved_repair_recovery_is_indeterminate_and_blocks_fresh_work(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"replacement")
    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        probe=lambda: None,
    )
    corrupt_file = runtime.install_dir / "bin" / "ollama.exe"
    corrupt_file.parent.mkdir(parents=True)
    corrupt_file.write_bytes(b"original-corrupt-tree")
    monkeypatch.setattr(
        runtime,
        "_install_locked",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OllamaRuntimeError("reinstall failed")),
    )
    monkeypatch.setattr(
        runtime,
        "_recover_repair_transaction",
        lambda: (_ for _ in ()).throw(OllamaRuntimeError("rollback is unproved")),
    )

    with pytest.raises(OllamaRuntimeError, match="could not be restored"):
        runtime.run_synchronous_operation(
            "repair",
            f"adm_{'7' * 32}",
            runtime.repair,
        )

    blocker = runtime.status()["unresolved_operation"]
    assert blocker is not None
    assert blocker["kind"] == "repair"
    assert blocker["state"] == "indeterminate"
    assert not runtime.install_dir.exists()
    assert list(runtime.runtime_root.glob(".repair-*"))
    with pytest.raises(OllamaRuntimeError, match="outcome is unknown"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'8' * 32}",
            lambda: pytest.fail("fresh mutation must remain blocked"),
        )


def test_interrupted_repair_restores_the_original_tree_on_restart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"replacement")
    workspace = tmp_path / "workspace"
    asset = _fake_asset(archive)
    runtime = OllamaRuntime(
        workspace,
        asset=asset,
        downloader=_copy_download(archive),
        probe=lambda: None,
    )
    corrupt_file = runtime.install_dir / "bin" / "ollama.exe"
    corrupt_file.parent.mkdir(parents=True)
    corrupt_file.write_bytes(b"original-corrupt-tree")
    monkeypatch.setattr(
        runtime,
        "_install_locked",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SystemExit("simulated repair interruption")),
    )

    with pytest.raises(SystemExit, match="simulated repair interruption"):
        runtime.repair()

    restarted = OllamaRuntime(
        workspace,
        asset=asset,
        downloader=_copy_download(archive),
        probe=lambda: None,
    )

    assert corrupt_file.read_bytes() == b"original-corrupt-tree"
    assert not list(restarted.runtime_root.glob(".repair-*"))
    assert not (restarted.runtime_root / ".flinttrade-repair-state.json").exists()


def test_interrupted_committed_repair_keeps_the_replacement_on_restart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"replacement")
    workspace = tmp_path / "workspace"
    asset = _fake_asset(archive)
    runtime = OllamaRuntime(
        workspace,
        asset=asset,
        downloader=_copy_download(archive),
        probe=lambda: None,
    )
    executable = runtime.install_dir / "bin" / "ollama.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"original-corrupt-tree")
    original_remove = ollama_runtime._remove_path_without_following_root

    def interrupt_quarantine_cleanup(path: Path) -> None:
        if path.name.startswith(".repair-"):
            raise SystemExit("simulated committed repair interruption")
        original_remove(path)

    monkeypatch.setattr(
        ollama_runtime,
        "_remove_path_without_following_root",
        interrupt_quarantine_cleanup,
    )

    with pytest.raises(SystemExit, match="simulated committed repair interruption"):
        runtime.repair()

    assert executable.read_bytes() == b"replacement"
    repair_state = runtime._read_repair_state()
    assert repair_state is not None
    assert repair_state["phase"] == "committed"
    assert list(runtime.runtime_root.glob(".repair-*"))

    monkeypatch.setattr(
        ollama_runtime,
        "_remove_path_without_following_root",
        original_remove,
    )
    restarted = OllamaRuntime(
        workspace,
        asset=asset,
        downloader=_copy_download(archive),
        probe=lambda: None,
    )

    assert executable.read_bytes() == b"replacement"
    assert not list(restarted.runtime_root.glob(".repair-*"))
    assert not (restarted.runtime_root / ".flinttrade-repair-state.json").exists()


def test_repair_refuses_to_touch_files_while_any_ollama_listener_is_present(tmp_path: Path) -> None:
    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=OllamaAsset(
            name="runtime.zip",
            sha256="0" * 64,
            url="https://downloads.example.invalid/runtime.zip",
            max_extracted_bytes=1,
            executable_candidates=("bin/ollama.exe",),
        ),
        probe=lambda: "0.32.0",
    )
    corrupt_file = runtime.install_dir / "bin" / "ollama.exe"
    corrupt_file.parent.mkdir(parents=True)
    corrupt_file.write_bytes(b"do-not-touch")

    with pytest.raises(OllamaRuntimeError, match="listener is still present"):
        runtime.repair()

    assert corrupt_file.read_bytes() == b"do-not-touch"


def test_repair_never_follows_a_corrupt_install_symlink(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"replacement")
    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        probe=lambda: None,
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("untouched", encoding="utf-8")
    runtime.install_dir.parent.mkdir(parents=True)
    try:
        runtime.install_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this platform")

    result = runtime.repair()

    assert result["installed"] is True
    assert runtime.install_dir.is_dir()
    assert not runtime.install_dir.is_symlink()
    assert sentinel.read_text(encoding="utf-8") == "untouched"


def test_runtime_refuses_a_symlinked_managed_runtime_ancestor_before_repair(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"replacement")
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside-runtime"
    corrupt_file = outside / "v0.32.0" / "bin" / "ollama.exe"
    corrupt_file.parent.mkdir(parents=True)
    corrupt_file.write_bytes(b"outside-corrupt")
    (workspace / "runtime").mkdir(parents=True)
    try:
        (workspace / "runtime" / "ollama").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this platform")
    with pytest.raises(OllamaRuntimeError, match="operation state is invalid"):
        OllamaRuntime(
            workspace,
            asset=_fake_asset(archive),
            downloader=_copy_download(archive),
            probe=lambda: None,
        )

    assert corrupt_file.read_bytes() == b"outside-corrupt"


def test_install_refuses_to_download_without_enough_free_space(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    asset = _fake_asset(archive)
    downloaded = False

    def downloader(_asset: OllamaAsset, _destination: Path, _progress: Any) -> None:
        nonlocal downloaded
        downloaded = True

    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=asset,
        downloader=downloader,
        disk_usage=lambda _path: SimpleNamespace(free=0),
        probe=lambda: None,
    )

    with pytest.raises(OllamaRuntimeError, match="free disk space"):
        runtime.install()

    assert downloaded is False
    assert runtime.status()["install_required_bytes"] > 0


def test_install_checks_remaining_space_again_before_extraction(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    free_space = iter([10**12, 0])
    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        disk_usage=lambda _path: SimpleNamespace(free=next(free_space)),
        probe=lambda: None,
    )

    with pytest.raises(OllamaRuntimeError, match="extraction"):
        runtime.install()

    assert runtime.status()["installed"] is False


def test_install_checks_free_space_for_each_extraction_write(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    free_space = iter([10**12, 10**12, 0])
    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        disk_usage=lambda _path: SimpleNamespace(free=next(free_space)),
        probe=lambda: None,
    )

    with pytest.raises(OllamaRuntimeError, match="free disk space during extraction"):
        runtime.install()

    assert runtime.status()["installed"] is False


def test_managed_storage_counts_runtime_residue_models_trust_and_rotated_logs(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path / "workspace", probe=lambda: None)
    files = {
        runtime.install_dir.parent / ".staging" / "install-current" / "archive": b"a" * 3,
        runtime.install_dir.parent / ".repair-current" / "binary": b"b" * 5,
        runtime.models_dir / "blobs" / "sha256-model": b"c" * 7,
        runtime.trust_dir / "trust.json": b"d" * 11,
        runtime.log_path: b"e" * 13,
        runtime.log_path.with_name("ollama.log.1"): b"f" * 17,
        runtime.log_path.with_name("ollama.log.9"): b"g" * 19,
        runtime.log_path.with_name(".ollama.log.123.456.tmp"): b"h" * 23,
    }
    for path, payload in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    assert runtime._managed_storage_bytes() == sum(len(payload) for payload in files.values())


def test_scavenger_removes_only_stale_residue_with_a_verified_owner_marker(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path / "workspace", probe=lambda: None)
    staging = runtime.install_dir.parent / ".staging"
    owned = staging / f"install-{'a' * 32}"
    unmarked = staging / f"install-{'b' * 32}"
    owned.mkdir(parents=True)
    unmarked.mkdir()
    (owned / "archive").write_bytes(b"owned")
    (unmarked / "archive").write_bytes(b"unmarked")
    runtime._write_residue_marker(
        owned,
        kind="install",
        created_at=1.0,
        owner_pid=2**22,
        owner_create_time=1.0,
    )

    runtime._scavenge_stale_residue(now=ollama_runtime._STALE_RESIDUE_SECONDS + 2.0)

    assert not owned.exists()
    assert unmarked.exists()


def test_log_writer_rotates_at_the_hard_per_file_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(ollama_runtime, "_MAX_LOG_FILE_BYTES", 8)
    monkeypatch.setattr(ollama_runtime, "_LOG_BACKUP_COUNT", 2)
    runtime = OllamaRuntime(tmp_path / "workspace", probe=lambda: None)

    runtime._append_log_chunk(b"12345678")
    runtime._append_log_chunk(b"90")

    assert runtime.log_path.read_bytes() == b"90"
    assert runtime.log_path.with_name("ollama.log.1").read_bytes() == b"12345678"
    assert runtime._log_storage_bytes() <= 24


def test_async_operations_are_serialised_and_report_completion(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    asset = _fake_asset(archive)
    download_started = threading.Event()
    release_download = threading.Event()

    def downloader(_asset: OllamaAsset, destination: Path, progress: Any) -> None:
        download_started.set()
        assert release_download.wait(timeout=2.0)
        payload = archive.read_bytes()
        destination.write_bytes(payload)
        progress(len(payload), len(payload))

    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=asset,
        downloader=downloader,
        probe=lambda: None,
    )

    accepted = runtime.install_async()

    assert download_started.wait(timeout=2.0)
    assert accepted["operation"]["kind"] == "install"
    assert runtime.status()["operation"]["state"] == "running"
    with pytest.raises(OllamaRuntimeError, match="already running"):
        runtime.start_async()

    release_download.set()
    assert runtime.wait_for_operation(timeout=2.0) is True
    status = runtime.status()
    assert status["installed"] is True
    assert status["operation"]["state"] == "succeeded"


def test_install_activation_failure_after_publication_is_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        probe=lambda: None,
    )
    monkeypatch.setattr(
        runtime,
        "_write_runtime_state",
        lambda *_args: (_ for _ in ()).throw(OllamaRuntimeError("injected activation failure")),
    )

    runtime.install_async(admission_id=f"adm_{'e' * 32}")

    assert runtime.wait_for_operation(timeout=2.0) is True
    status = runtime.status()
    assert runtime.install_dir.is_dir()
    assert status["operation"]["kind"] == "install"
    assert status["operation"]["state"] == "indeterminate"
    assert status["unresolved_operation"]["id"] == status["operation"]["id"]
    with pytest.raises(OllamaRuntimeError, match="outcome is unknown"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'f' * 32}",
            lambda: pytest.fail("fresh mutation must remain blocked"),
        )


def test_pull_failure_after_transport_handoff_is_indeterminate(tmp_path: Path) -> None:
    def puller(_model: str, _progress: Any) -> None:
        raise OllamaRuntimeError("model registry unavailable")

    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        puller=puller,
    )
    runtime._process = _FakeProcess()

    runtime.pull_model_async("qwen3:8b")

    assert runtime.wait_for_operation(timeout=2.0) is True
    status = runtime.status()
    assert status["operation"]["state"] == "indeterminate"
    assert "outcome is unknown" in status["operation"]["error"]
    assert status["unresolved_operation"]["id"] == status["operation"]["id"]
    assert status["model_pull"]["status"] == "failed"
    with pytest.raises(OllamaRuntimeError, match="outcome is unknown"):
        runtime.pull_model_async("qwen3:8b", admission_id=f"adm_{'1' * 32}")


def test_pull_failure_after_remote_progress_is_indeterminate(tmp_path: Path) -> None:
    def puller(_model: str, progress: Any) -> None:
        progress(1, 1, "success", f"sha256:{'a' * 64}")

    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        puller=puller,
        request_json=lambda *_args: (_ for _ in ()).throw(OllamaRuntimeError("model inventory unavailable")),
    )
    runtime._process = _FakeProcess()

    queued = runtime.pull_model_async("qwen3:8b")

    assert runtime.wait_for_operation(timeout=2.0) is True
    status = runtime.status()
    assert status["operation"]["id"] == queued["operation"]["id"]
    assert status["operation"]["state"] == "indeterminate"
    assert status["operation"]["error"] == ollama_runtime._INDETERMINATE_OPERATION_ERROR
    assert status["unresolved_operation"]["id"] == queued["operation"]["id"]


def test_failed_async_start_is_not_misreported_as_operator_cancellation(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    runtime = OllamaRuntime(
        tmp_path,
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        probe=lambda: None,
        process_factory=lambda *_args, **_kwargs: _ExitedProcess(),
        sleep=lambda _seconds: None,
    )
    runtime.install()

    runtime.start_async(timeout_seconds=0.1)

    assert runtime.wait_for_operation(timeout=2.0) is True
    assert runtime.status()["operation"]["state"] == "failed"


def test_failed_async_start_does_not_expose_local_process_paths(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    runtime = OllamaRuntime(
        tmp_path,
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        probe=lambda: None,
        process_factory=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError(f"cannot execute {tmp_path / 'private-runtime' / 'ollama'}")
        ),
    )
    runtime.install()

    runtime.start_async(timeout_seconds=0.1)

    assert runtime.wait_for_operation(timeout=2.0) is True
    operation = runtime.status()["operation"]
    assert operation["state"] == "failed"
    assert operation["error"] == "managed Ollama server could not start"
    assert str(tmp_path) not in operation["error"]


def test_failed_async_start_with_unproved_teardown_is_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    process = _FakeProcess()
    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        probe=lambda: None,
        process_factory=lambda *_args, **_kwargs: process,
        sleep=lambda _seconds: None,
    )
    runtime.install()
    monkeypatch.setattr(
        runtime,
        "_stop_owned_process",
        lambda **_kwargs: (_ for _ in ()).throw(OllamaRuntimeError("could not prove managed Ollama teardown")),
    )

    runtime.start_async(timeout_seconds=0.0, admission_id=f"adm_{'1' * 32}")

    assert runtime.wait_for_operation(timeout=2.0) is True
    status = runtime.status()
    assert runtime._process is process
    assert process.poll() is None
    assert status["operation"]["kind"] == "start"
    assert status["operation"]["state"] == "indeterminate"
    assert status["unresolved_operation"]["id"] == status["operation"]["id"]
    with pytest.raises(OllamaRuntimeError, match="outcome is unknown"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'2' * 32}",
            lambda: pytest.fail("fresh mutation must remain blocked"),
        )


def test_provider_transition_start_with_unproved_teardown_is_durably_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    process = _FakeProcess()
    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        probe=lambda: None,
        process_factory=lambda *_args, **_kwargs: process,
        sleep=lambda _seconds: None,
    )
    runtime.install()
    monkeypatch.setattr(
        runtime,
        "_stop_owned_process",
        lambda **_kwargs: (_ for _ in ()).throw(OllamaRuntimeError("could not prove managed Ollama teardown")),
    )

    with pytest.raises(OllamaRuntimeError, match="could not prove managed Ollama teardown"):
        with runtime.provider_transition_guard():
            runtime.start(timeout_seconds=0.0)

    status = runtime.status()
    assert runtime._process is process
    assert process.poll() is None
    assert status["operation"]["kind"] == "provider_transition"
    assert status["operation"]["state"] == "indeterminate"
    assert status["unresolved_operation"]["id"] == status["operation"]["id"]
    with pytest.raises(OllamaRuntimeError, match="outcome is unknown"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'3' * 32}",
            lambda: pytest.fail("fresh mutation must remain blocked"),
        )


class _FakeProcess:
    def __init__(self) -> None:
        self.pid = 4242
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.returncode = 0

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return self.returncode or 0


class _ExitedProcess(_FakeProcess):
    def __init__(self) -> None:
        super().__init__()
        self.returncode = 1


def test_concurrent_runtime_instances_cannot_split_process_ownership(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"runtime")
    workspace = tmp_path / "workspace"
    asset = _fake_asset(archive)
    installed = OllamaRuntime(workspace, asset=asset, downloader=_copy_download(archive), probe=lambda: None)
    installed.install()

    runtimes: list[OllamaRuntime] = []
    for index in range(2):
        process = _FakeProcess()
        process.pid = 5001 + index
        runtime = OllamaRuntime(
            workspace,
            asset=asset,
            downloader=_copy_download(archive),
            process_factory=lambda *_args, _process=process, **_kwargs: _process,
            probe=lambda: None,
            listener_owner=lambda _process: True,
            port_allocator=lambda _port=43127 + index: _port,
            sleep=lambda _seconds: None,
        )
        monkeypatch.setattr(runtime, "_start_log_pump", lambda _process: None)
        monkeypatch.setattr(runtime, "_process_create_time", lambda pid, *, strict: float(pid))
        monkeypatch.setattr(
            runtime,
            "_process_identity_is_alive",
            lambda pid, created_at: pid > 0 and created_at == float(pid),
        )
        monkeypatch.setattr(
            runtime,
            "_probe",
            lambda _runtime=runtime: "0.32.0"
            if _runtime._process is not None and _runtime._process.poll() is None
            else None,
        )
        runtimes.append(runtime)

    results: list[dict[str, Any]] = []
    errors: list[BaseException] = []

    def start(runtime: OllamaRuntime) -> None:
        try:
            results.append(runtime.start(timeout_seconds=0.5))
        except BaseException as exc:  # noqa: BLE001 - asserted by the parent
            errors.append(exc)

    threads = [threading.Thread(target=start, args=(runtime,)) for runtime in runtimes]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2.0)

    assert all(not thread.is_alive() for thread in threads)
    assert len(results) == 1
    assert results[0]["ready"] is True
    assert len(errors) == 1
    assert isinstance(errors[0], OllamaRuntimeError)
    assert "owns the managed Ollama runtime" in str(errors[0]) or "already claimed" in str(errors[0])
    owner = runtimes[0]._read_process_owner_record()
    assert owner is not None
    assert owner["child_pid"] in {5001, 5002}


@pytest.mark.integration
def test_destructive_mutations_hold_a_cross_process_workspace_lease(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A lease held by another OS process blocks destructive mutations until it is released.

    Two behaviours are pinned. A bounded destructive mutation (``uninstall``) fails with
    ``lifecycle transition timed out`` while a *different process* holds the workspace
    lifecycle lease -- and specifically because of that lease, not because some earlier
    in-process lock ran out of budget. A patient mutation (``repair``) instead blocks on
    the same lease and only proceeds once the holder releases it, at which point it fails
    for its own reason, that nothing is installed.

    This test is honestly ``integration``: it spawns a real interpreter and takes a real
    OS-level file lock across a process boundary. That is scheduling nondeterminism no
    injected clock can remove, so every handshake here is explicit rather than timed --
    readiness is a marker file polled alongside ``holder.poll()`` so a dead helper fails
    at once, and "``repair`` is blocked" is observed from the lease contention itself
    rather than inferred from surviving a 50 ms sleep. The previous form additionally
    required the helper to notice its release file, drop the lock, and ``repair`` to
    reacquire it, all inside the 100 ms budget left over from the ``uninstall`` phase --
    a cross-process race in roughly a tenth of a second.
    """
    workspace = tmp_path / "workspace"
    runtime = OllamaRuntime(workspace, probe=lambda: None)
    lock_path = workspace / ollama_runtime._LIFECYCLE_LOCK_NAME
    ready_path = tmp_path / "lease-ready"
    release_path = tmp_path / "lease-release"

    contended_leases: list[str] = []
    lease_contended = threading.Event()
    production_lock = ollama_runtime._RuntimeFileLock

    class _ObservedRuntimeFileLock(production_lock):  # type: ignore[misc, valid-type]
        """Report every lease acquisition that loses to a competing holder."""

        def acquire(self, *args: Any, **kwargs: Any) -> Any:
            try:
                return super().acquire(*args, **kwargs)
            except FileLockTimeout:
                contended_leases.append(str(self.lock_file))
                lease_contended.set()
                raise

    monkeypatch.setattr(ollama_runtime, "_RuntimeFileLock", _ObservedRuntimeFileLock)

    # filelock's Windows backend unlinks the lock file as the last step of
    # releasing it. OwnerSafeFileLock, acquiring concurrently from this process,
    # correctly refuses a path that vanishes underneath it and reports "lease
    # path is unsafe" — so a handover landing inside that unlink window fails the
    # test on an error unrelated to its subject. That race is scaffolding, not
    # product behaviour: a real lease holder is a FlintTrade process using
    # OwnerSafeFileLock, which does not unlink. Suppressing the unlink in the
    # holder keeps the handover the test is actually about.
    holder_code = "\n".join(
        (
            "import sys, time",
            "from pathlib import Path",
            "from filelock import FileLock",
            "import filelock._windows, filelock._unix",
            "for _module in (filelock._windows, filelock._unix):",
            "    for _name in ('WindowsFileLock', 'UnixFileLock'):",
            "        _cls = getattr(_module, _name, None)",
            "        if _cls is None:",
            "            continue",
            "        _inner = _cls._release",
            "        def _keep_lock_file(self, _inner=_inner):",
            "            _unlink = Path.unlink",
            "            Path.unlink = lambda *a, **k: None",
            "            try:",
            "                _inner(self)",
            "            finally:",
            "                Path.unlink = _unlink",
            "        _cls._release = _keep_lock_file",
            "lock_path, ready_path, release_path = map(Path, sys.argv[1:4])",
            f"with FileLock(lock_path, timeout={_READINESS_CEILING_SECONDS}, mode=0o600):",
            "    ready_path.write_text('ready', encoding='ascii')",
            "    while not release_path.exists():",
            "        time.sleep(0.01)",
        )
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code, str(lock_path), str(ready_path), str(release_path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _await_holder_readiness(holder, ready_path)

        # A bounded mutation must give up rather than block behind the foreign lease.
        monkeypatch.setattr(ollama_runtime, "_SYNC_LIFECYCLE_WAIT_SECONDS", 0.1)
        with pytest.raises(OllamaRuntimeError, match="lifecycle transition timed out"):
            runtime.uninstall()
        # It timed out on the cross-process lease, not on some earlier in-process lock.
        assert contended_leases == [str(lock_path)]

        # A patient mutation blocks on the same lease instead of giving up. Restoring the
        # production wait keeps the release handshake below from being a race.
        monkeypatch.setattr(ollama_runtime, "_SYNC_LIFECYCLE_WAIT_SECONDS", _HANDOFF_CEILING_SECONDS)
        lease_contended.clear()
        repair_errors: list[BaseException] = []

        def repair() -> None:
            try:
                runtime.repair()
            except BaseException as exc:  # noqa: BLE001 - asserted below
                repair_errors.append(exc)

        repair_thread = threading.Thread(target=repair)
        repair_thread.start()

        assert lease_contended.wait(timeout=_HANDOFF_CEILING_SECONDS)
        assert contended_leases[-1] == str(lock_path)
        assert repair_thread.is_alive()

        release_path.write_text("release", encoding="ascii")
        repair_thread.join(timeout=_HANDOFF_CEILING_SECONDS)

        assert repair_thread.is_alive() is False
        assert len(repair_errors) == 1
        assert isinstance(repair_errors[0], OllamaRuntimeError)
        assert "not installed" in str(repair_errors[0])
    finally:
        release_path.touch()
        try:
            holder.wait(timeout=_HANDOFF_CEILING_SECONDS)
        except subprocess.TimeoutExpired:
            holder.kill()
            holder.wait(timeout=_HANDOFF_CEILING_SECONDS)
        if holder.stderr is not None:
            holder.stderr.close()


def test_runtime_tree_cleanup_fails_before_crossing_its_entry_bound(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tree = tmp_path / "runtime-tree"
    tree.mkdir()
    (tree / "one").write_bytes(b"1")
    (tree / "two").write_bytes(b"2")
    monkeypatch.setattr(ollama_runtime, "_MAX_RUNTIME_TREE_ENTRIES", 2)

    with pytest.raises(OllamaRuntimeError, match="entry limit"):
        ollama_runtime._remove_path_without_following_root(tree)

    assert tree.is_dir()
    assert {path.name for path in tree.iterdir()} == {"one", "two"}


def _trust_locked_model(runtime: OllamaRuntime, source: str, digest: str) -> str:
    alias = ollama_runtime._locked_model_alias(digest)
    runtime._write_model_trust_state({alias: digest}, {source: alias})
    return alias


def test_listener_ownership_proof_includes_a_spawned_child_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listener = SimpleNamespace(
        status=ollama_runtime.psutil.CONN_LISTEN,
        laddr=SimpleNamespace(ip="127.0.0.1", port=11434),
    )
    child = SimpleNamespace(net_connections=lambda **_kwargs: [listener])
    root = SimpleNamespace(
        children=lambda **_kwargs: [child],
        net_connections=lambda **_kwargs: [],
    )
    monkeypatch.setattr(ollama_runtime.psutil, "Process", lambda _pid: root)

    assert _PRODUCTION_LISTENER_OWNER(_FakeProcess(), 11434) is True
    assert _PRODUCTION_PORT_DISCOVERER(_FakeProcess()) == 11434


def test_listener_enumeration_keeps_results_when_one_descendant_is_inaccessible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listener = SimpleNamespace(
        status=ollama_runtime.psutil.CONN_LISTEN,
        laddr=SimpleNamespace(ip="127.0.0.1", port=11434),
    )
    inaccessible = SimpleNamespace(
        net_connections=lambda **_kwargs: (_ for _ in ()).throw(ollama_runtime.psutil.AccessDenied())
    )
    listening_child = SimpleNamespace(net_connections=lambda **_kwargs: [listener])
    root = SimpleNamespace(
        children=lambda **_kwargs: [inaccessible, listening_child],
        net_connections=lambda **_kwargs: [],
    )
    monkeypatch.setattr(ollama_runtime.psutil, "Process", lambda _pid: root)

    assert _PRODUCTION_LISTENER_OWNER(_FakeProcess(), 11434) is True
    assert _PRODUCTION_PORT_DISCOVERER(_FakeProcess()) == 11434


@pytest.fixture(autouse=True)
def _prove_fake_process_listener_ownership(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        OllamaRuntime,
        "_listener_owned_by_process",
        staticmethod(lambda process, _port=11434: isinstance(process, _FakeProcess)),
    )
    monkeypatch.setattr(
        OllamaRuntime,
        "_discover_owned_loopback_port",
        staticmethod(lambda process: 43127 if isinstance(process, _FakeProcess) else 0),
    )
    yield
    with ollama_runtime._MANAGED_RUNTIME_OWNER_LOCK:
        ollama_runtime._MANAGED_RUNTIME_OWNER = None


def test_status_distinguishes_an_external_ollama_server(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: "0.32.0")

    status = runtime.status()

    assert status["ready"] is False
    assert status["state"] == "conflict"
    assert status["managed_process"] is False
    assert status["external_process"] is True
    assert status["server_version"] == "0.32.0"


def test_start_rejects_an_already_listening_unowned_process(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    spawn_calls = 0

    def process_factory(*_args: Any, **_kwargs: Any) -> _FakeProcess:
        nonlocal spawn_calls
        spawn_calls += 1
        return _FakeProcess()

    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        probe=lambda: "service-shaped-json",
        process_factory=process_factory,
        port_allocator=lambda: 43127,
    )
    runtime.install()

    with pytest.raises(OllamaRuntimeError, match="unowned process"):
        runtime.start()

    assert spawn_calls == 0
    assert runtime.status()["state"] == "conflict"


def test_start_never_replaces_an_owned_process_that_is_not_ready(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    spawn_calls = 0

    def process_factory(*_args: Any, **_kwargs: Any) -> _FakeProcess:
        nonlocal spawn_calls
        spawn_calls += 1
        return _FakeProcess()

    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        process_factory=process_factory,
        probe=lambda: None,
    )
    runtime.install()
    owned = _FakeProcess()
    runtime._process = owned

    with pytest.raises(OllamaRuntimeError, match="owned process is already running"):
        runtime.start(timeout_seconds=0)

    assert spawn_calls == 0
    assert runtime._process is owned


def test_start_uses_loopback_workspace_models_and_disables_cloud(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    asset = _fake_asset(archive)
    process = _FakeProcess()
    captured: dict[str, Any] = {}
    probes = iter([None, "0.32.0"])

    def process_factory(args: list[str], **kwargs: Any) -> _FakeProcess:
        captured["args"] = args
        captured.update(kwargs)
        return process

    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=asset,
        downloader=_copy_download(archive),
        process_factory=process_factory,
        probe=lambda: next(probes, "0.32.0"),
        sleep=lambda _seconds: None,
        port_allocator=lambda: 43127,
    )
    runtime.install()
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_HOST", "")

    status = runtime.start(timeout_seconds=1.0)

    assert status["ready"] is True
    assert status["managed_process"] is True
    assert captured["args"][-1] == "serve"
    assert captured["env"]["OLLAMA_HOST"] == "127.0.0.1:43127"
    assert runtime.base_url == "http://127.0.0.1:43127"
    assert captured["env"]["OLLAMA_MODELS"] == str(runtime.models_dir)
    assert captured["env"]["OLLAMA_NO_CLOUD"] == "1"
    assert captured["env"]["OLLAMA_MAX_QUEUE"] == "1"
    assert captured["env"]["OLLAMA_NUM_PARALLEL"] == "1"
    assert captured["env"]["OLLAMA_MAX_LOADED_MODELS"] == "1"
    if os.name == "nt":
        assert captured["creationflags"] & 0x00000200
    else:
        assert captured["start_new_session"] is True
    assert os.environ["LLM_PROVIDER"] == "anthropic"
    assert os.environ["LLM_HOST"] == ""


def test_managed_child_environment_preserves_only_valid_documented_controls() -> None:
    source = {
        "HOME": "/home/operator",
        "PATH": "/usr/bin",
        "HTTPS_PROXY": "http://proxy.example.test:8443",
        "NO_PROXY": "registry.internal",
        "CUDA_VISIBLE_DEVICES": "GPU-1234,1",
        "ROCR_VISIBLE_DEVICES": "0,2",
        "HSA_OVERRIDE_GFX_VERSION": "10.3.0",
        "HSA_OVERRIDE_GFX_VERSION_1": "11.0.0",
        "GGML_VK_VISIBLE_DEVICES": "1",
        "HTTP_PROXY": "http://must-not-be-forwarded.example.test",
        "LD_PRELOAD": "/tmp/injected.so",
        "OLLAMA_HOST": "0.0.0.0:11434",
    }

    environment = ollama_runtime._managed_child_environment(source, system_name="linux")

    assert environment["HTTPS_PROXY"] == source["HTTPS_PROXY"]
    assert environment["NO_PROXY"] == "registry.internal,127.0.0.1,localhost,::1"
    assert environment["CUDA_VISIBLE_DEVICES"] == "GPU-1234,1"
    assert environment["ROCR_VISIBLE_DEVICES"] == "0,2"
    assert environment["HSA_OVERRIDE_GFX_VERSION"] == "10.3.0"
    assert environment["HSA_OVERRIDE_GFX_VERSION_1"] == "11.0.0"
    assert environment["GGML_VK_VISIBLE_DEVICES"] == "1"
    assert "HTTP_PROXY" not in environment
    assert "LD_PRELOAD" not in environment
    assert "OLLAMA_HOST" not in environment


def test_start_uses_atomic_ephemeral_binding_and_discovers_the_owned_listener(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    process = _FakeProcess()
    captured: dict[str, Any] = {}
    probes = iter([None, "0.32.0"])

    def process_factory(args: list[str], **kwargs: Any) -> _FakeProcess:
        captured["args"] = args
        captured.update(kwargs)
        return process

    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        process_factory=process_factory,
        probe=lambda: next(probes, "0.32.0"),
        sleep=lambda _seconds: None,
        port_discoverer=lambda _process: 43127,
    )
    runtime.install()

    status = runtime.start(timeout_seconds=1.0)

    assert status["ready"] is True
    assert captured["env"]["OLLAMA_HOST"] == "127.0.0.1:0"
    assert runtime.base_url == "http://127.0.0.1:43127"
    assert runtime._read_process_owner_record()["port"] == 43127


def test_process_owner_read_cannot_follow_a_file_swapped_before_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = OllamaRuntime(tmp_path)
    record = {
        "schema": 1,
        "backend_pid": 123,
        "backend_create_time": 1.0,
        "child_pid": 456,
        "child_create_time": 2.0,
        "port": 43127,
        "executable_sha256": "a" * 64,
    }
    runtime._write_process_owner_record(record)
    owner_path = runtime._process_owner_path()
    outside = tmp_path / "outside.json"
    outside.write_text(ollama_runtime.json.dumps(record), encoding="utf-8")
    original_open = ollama_runtime.os.open
    swapped = False

    def swapping_open(path: Any, flags: int, *args: Any) -> int:
        nonlocal swapped
        if Path(path) == owner_path and not swapped:
            swapped = True
            owner_path.unlink()
            owner_path.symlink_to(outside)
        return original_open(path, flags, *args)

    monkeypatch.setattr(ollama_runtime.os, "O_NOFOLLOW", 0, raising=False)
    monkeypatch.setattr(ollama_runtime.os, "open", swapping_open)

    with pytest.raises(OllamaRuntimeError, match="ownership state is invalid"):
        runtime._read_process_owner_record()


def test_install_marker_read_cannot_follow_a_file_swapped_without_nofollow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = OllamaRuntime(tmp_path / "workspace")
    runtime.install_dir.mkdir(parents=True)
    marker = runtime.install_dir / ollama_runtime._INSTALL_MARKER_NAME
    marker.write_text('{"schema":3}', encoding="utf-8")
    outside = tmp_path / "outside-marker.json"
    outside.write_text('{"schema":99}', encoding="utf-8")
    original_open = ollama_runtime.os.open
    swapped = False

    def swapping_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        nonlocal swapped
        if Path(path) == marker and not swapped:
            swapped = True
            marker.unlink()
            marker.symlink_to(outside)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(ollama_runtime.os, "O_NOFOLLOW", 0, raising=False)
    monkeypatch.setattr(ollama_runtime.os, "open", swapping_open)

    with pytest.raises(OllamaRuntimeError, match="integrity verification failed"):
        runtime._read_install_json(marker)


@pytest.mark.skipif(not getattr(ollama_runtime.os, "O_NOFOLLOW", 0), reason="POSIX no-follow open is unavailable")
def test_install_marker_read_keeps_its_open_ancestor_when_the_visible_directory_is_swapped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = OllamaRuntime(tmp_path / "workspace")
    runtime.install_dir.mkdir(parents=True)
    marker = runtime.install_dir / ollama_runtime._INSTALL_MARKER_NAME
    marker.write_text('{"schema":3}', encoding="utf-8")
    original_install = runtime.install_dir.with_name("original-install")
    outside_install = tmp_path / "outside-install"
    outside_install.mkdir()
    (outside_install / ollama_runtime._INSTALL_MARKER_NAME).write_text('{"schema":99}', encoding="utf-8")
    original_open = ollama_runtime.os.open
    swapped = False

    def swapping_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        nonlocal swapped
        if (Path(path) == marker or str(path) == marker.name) and not swapped:
            swapped = True
            ollama_runtime.os.replace(runtime.install_dir, original_install)
            runtime.install_dir.symlink_to(outside_install, target_is_directory=True)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(ollama_runtime.os, "open", swapping_open)

    payload, _raw = runtime._read_install_json(marker)

    assert swapped is True
    assert payload == {"schema": 3}


def test_windows_native_state_open_rejects_a_reparse_handle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    open_calls: list[tuple[str, int]] = []

    class NativeFunction:
        def __init__(self, callback: Any) -> None:
            self.callback = callback

        def __call__(self, *args: Any) -> Any:
            return self.callback(*args)

    class Kernel32:
        def __init__(self) -> None:
            handles = iter((10, 20))
            self.CreateFileW = NativeFunction(
                lambda path, _access, _share, _security, _creation, flags, _template: (
                    open_calls.append((path, flags)) or next(handles)
                )
            )
            self.CloseHandle = NativeFunction(lambda _handle: 1)
            self.GetFileInformationByHandle = NativeFunction(self.get_info)
            self.GetFinalPathNameByHandleW = NativeFunction(self.get_final_path)

        @staticmethod
        def get_info(handle: Any, output: Any) -> int:
            info = output._obj  # noqa: SLF001
            info.file_attributes = 0x10 if handle.value == 10 else 0x400
            info.volume_serial_number = 1
            info.file_index_low = handle.value
            info.number_of_links = 1
            return 1

        @staticmethod
        def get_final_path(_handle: Any, buffer: Any, _size: int, _flags: int) -> int:
            buffer.value = "/managed"
            return len(buffer.value)

    kernel32 = Kernel32()
    monkeypatch.setattr(
        ollama_runtime,
        "_windows_private_file_api",
        lambda: (kernel32, SimpleNamespace(open_osfhandle=pytest.fail)),
        raising=False,
    )
    monkeypatch.setattr(
        ollama_runtime,
        "_normalise_windows_expected_path",
        lambda _path: "/managed",
    )
    managed_root = tmp_path / "workspace"

    with pytest.raises(OllamaRuntimeError, match="invalid state"):
        ollama_runtime._open_windows_private_regular_descriptor(
            managed_root / "runtime" / "owner.json",
            managed_root=managed_root,
            invalid_message="invalid state",
        )

    assert len(open_calls) == 2
    assert all(flags & 0x00200000 for _path, flags in open_calls)


def test_windows_native_state_open_rejects_changed_file_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    open_calls: list[str] = []

    class NativeFunction:
        def __init__(self, callback: Any) -> None:
            self.callback = callback

        def __call__(self, *args: Any) -> Any:
            return self.callback(*args)

    class Kernel32:
        def __init__(self) -> None:
            handles = iter((10, 20, 30))
            self.CreateFileW = NativeFunction(
                lambda path, *_args: open_calls.append(path) or next(handles)
            )
            self.CloseHandle = NativeFunction(lambda _handle: 1)
            self.GetFileInformationByHandle = NativeFunction(self.get_info)
            self.GetFinalPathNameByHandleW = NativeFunction(self.get_final_path)

        @staticmethod
        def get_info(handle: Any, output: Any) -> int:
            info = output._obj  # noqa: SLF001
            info.file_attributes = 0x10 if handle.value == 10 else 0
            info.volume_serial_number = 1
            info.file_index_low = 100 if handle.value == 20 else handle.value
            info.number_of_links = 1
            return 1

        @staticmethod
        def get_final_path(handle: Any, buffer: Any, _size: int, _flags: int) -> int:
            buffer.value = "/managed" if handle.value == 10 else "/managed/owner.json"
            return len(buffer.value)

    kernel32 = Kernel32()
    monkeypatch.setattr(
        ollama_runtime,
        "_windows_private_file_api",
        lambda: (kernel32, SimpleNamespace(open_osfhandle=pytest.fail)),
        raising=False,
    )
    monkeypatch.setattr(
        ollama_runtime,
        "_normalise_windows_expected_path",
        lambda _path: "/managed",
    )
    managed_root = tmp_path / "workspace"

    with pytest.raises(OllamaRuntimeError, match="invalid state"):
        ollama_runtime._open_windows_private_regular_descriptor(
            managed_root / "owner.json",
            managed_root=managed_root,
            invalid_message="invalid state",
        )

    assert len(open_calls) == 3


def test_windows_native_state_open_rejects_changed_managed_root_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    open_calls: list[str] = []

    class NativeFunction:
        def __init__(self, callback: Any) -> None:
            self.callback = callback

        def __call__(self, *args: Any) -> Any:
            return self.callback(*args)

    class Kernel32:
        def __init__(self) -> None:
            handles = iter((10, 20, 30, 40))
            self.CreateFileW = NativeFunction(
                lambda path, *_args: open_calls.append(path) or next(handles)
            )
            self.CloseHandle = NativeFunction(lambda _handle: 1)
            self.GetFileInformationByHandle = NativeFunction(self.get_info)
            self.GetFinalPathNameByHandleW = NativeFunction(self.get_final_path)

        @staticmethod
        def get_info(handle: Any, output: Any) -> int:
            info = output._obj  # noqa: SLF001
            info.file_attributes = 0x10 if handle.value in {10, 40} else 0
            info.volume_serial_number = 1
            info.file_index_low = 20 if handle.value in {20, 30} else handle.value
            info.number_of_links = 1
            return 1

        @staticmethod
        def get_final_path(handle: Any, buffer: Any, _size: int, _flags: int) -> int:
            buffer.value = "/managed" if handle.value in {10, 40} else "/managed/owner.json"
            return len(buffer.value)

    kernel32 = Kernel32()
    monkeypatch.setattr(
        ollama_runtime,
        "_windows_private_file_api",
        lambda: (kernel32, SimpleNamespace(open_osfhandle=pytest.fail)),
    )
    monkeypatch.setattr(
        ollama_runtime,
        "_normalise_windows_expected_path",
        lambda _path: "/managed",
    )
    managed_root = tmp_path / "workspace"

    with pytest.raises(OllamaRuntimeError, match="invalid state"):
        ollama_runtime._open_windows_private_regular_descriptor(
            managed_root / "owner.json",
            managed_root=managed_root,
            invalid_message="invalid state",
        )

    assert len(open_calls) == 4


def test_windows_native_state_open_returns_only_a_stable_verified_descriptor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "descriptor-source.json"
    source.write_bytes(b"verified")

    class NativeFunction:
        def __init__(self, callback: Any) -> None:
            self.callback = callback

        def __call__(self, *args: Any) -> Any:
            return self.callback(*args)

    class Kernel32:
        def __init__(self) -> None:
            handles = iter((10, 20, 30, 40))
            self.CreateFileW = NativeFunction(lambda *_args: next(handles))
            self.CloseHandle = NativeFunction(lambda _handle: 1)
            self.GetFileInformationByHandle = NativeFunction(self.get_info)
            self.GetFinalPathNameByHandleW = NativeFunction(self.get_final_path)

        @staticmethod
        def get_info(handle: Any, output: Any) -> int:
            info = output._obj  # noqa: SLF001
            info.file_attributes = 0x10 if handle.value in {10, 40} else 0
            info.volume_serial_number = 1
            info.file_index_low = 10 if handle.value in {10, 40} else 20
            info.number_of_links = 1
            return 1

        @staticmethod
        def get_final_path(handle: Any, buffer: Any, _size: int, _flags: int) -> int:
            buffer.value = "/managed" if handle.value in {10, 40} else "/managed/owner.json"
            return len(buffer.value)

    kernel32 = Kernel32()
    monkeypatch.setattr(
        ollama_runtime,
        "_windows_private_file_api",
        lambda: (
            kernel32,
            SimpleNamespace(
                open_osfhandle=lambda _handle, flags: os.open(source, flags),
            ),
        ),
    )
    monkeypatch.setattr(
        ollama_runtime,
        "_normalise_windows_expected_path",
        lambda _path: "/managed",
    )
    managed_root = tmp_path / "workspace"

    descriptor = ollama_runtime._open_windows_private_regular_descriptor(
        managed_root / "owner.json",
        managed_root=managed_root,
        invalid_message="invalid state",
    )
    try:
        assert os.read(descriptor, 8) == b"verified"
    finally:
        os.close(descriptor)


def test_start_refuses_to_publish_a_matching_unowned_listener_that_wins_the_bind_race(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    process = _FakeProcess()
    probes = iter([None, "0.32.0"])

    if os.name != "nt":
        def killpg(_process_group: int, sent_signal: int) -> None:
            if sent_signal == 0:
                raise ProcessLookupError
            process.returncode = 0

        monkeypatch.setattr(ollama_runtime.os, "killpg", killpg)

    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        process_factory=lambda *_args, **_kwargs: process,
        probe=lambda: next(probes, "0.32.0"),
        sleep=lambda _seconds: None,
    )
    runtime.install()
    runtime._listener_is_owned = lambda _process: False  # type: ignore[attr-defined]

    with pytest.raises(OllamaRuntimeError, match="listener ownership"):
        runtime.start(timeout_seconds=1.0)

    assert process.poll() is not None
    assert ollama_runtime.managed_ollama_is_ready() is False


def test_start_rejects_a_server_version_that_does_not_match_the_pinned_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    process = _FakeProcess()
    probes = iter([None, "0.30.0"])

    if os.name != "nt":
        def killpg(_process_group: int, sent_signal: int) -> None:
            if sent_signal == 0:
                raise ProcessLookupError
            process.returncode = 0

        monkeypatch.setattr(ollama_runtime.os, "killpg", killpg)

    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        process_factory=lambda *_args, **_kwargs: process,
        probe=lambda: next(probes, "0.30.0"),
        sleep=lambda _seconds: None,
    )
    runtime.install()

    with pytest.raises(OllamaRuntimeError, match="version does not match"):
        runtime.start(timeout_seconds=1.0)

    assert process.poll() is not None
    assert ollama_runtime.managed_ollama_is_ready() is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group assertion")
def test_stop_terminates_the_full_owned_process_group(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = _FakeProcess()
    signals: list[int] = []

    def killpg(process_group: int, sent_signal: int) -> None:
        assert process_group == process.pid
        if sent_signal == 0:
            raise ProcessLookupError
        signals.append(sent_signal)
        process.returncode = 0

    monkeypatch.setattr(ollama_runtime.os, "killpg", killpg)
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    runtime._process = process

    runtime.stop()

    assert signals == [signal.SIGTERM]
    assert process.terminate_calls == 0
    assert process.kill_calls == 0


def test_stop_returns_truthful_state_after_resetting_the_private_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = _FakeProcess()
    runtime = OllamaRuntime(tmp_path, probe=lambda: "0.32.0")
    runtime._process = process
    runtime._port = 43127
    monkeypatch.setattr(
        ollama_runtime,
        "_terminate_process_tree",
        lambda owned_process, **_kwargs: setattr(owned_process, "returncode", 0),
    )

    status = runtime.stop()

    assert status["ready"] is False
    assert status["managed_process"] is False
    assert status["external_process"] is False
    assert status["teardown"]["state"] == "stopped"
    assert status["teardown"]["mode"] == "graceful"
    assert runtime.base_url == ""


def test_windows_containment_uses_a_new_group_and_tree_termination() -> None:
    options_factory = getattr(ollama_runtime, "_managed_process_options", None)
    tree_terminator = getattr(ollama_runtime, "_terminate_windows_process_tree", None)

    assert callable(options_factory)
    assert options_factory("nt")["creationflags"] & 0x00000200
    assert options_factory("nt")["creationflags"] & 0x00000004
    assert callable(tree_terminator)

    process = _FakeProcess()
    commands: list[list[str]] = []

    def run_command(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        commands.append(command)
        process.returncode = 0
        return SimpleNamespace(returncode=0)

    tree_terminator(process, run_command=run_command)

    assert commands == [["taskkill", "/PID", str(process.pid), "/T"]]


def test_windows_production_teardown_uses_the_retained_job_object() -> None:
    tree_terminator = getattr(ollama_runtime, "_terminate_windows_process_tree")
    process = _FakeProcess()
    events: list[str] = []

    class FakeJob:
        def terminate(self, *, deadline: float) -> None:
            assert deadline > 0
            events.append("terminate-job")
            process.returncode = 0

        def close(self) -> None:
            events.append("close-job")

    tree_terminator(
        process,
        job=FakeJob(),
        run_command=lambda *_args, **_kwargs: pytest.fail("Job teardown must not fall back to taskkill"),
    )

    assert events == ["terminate-job", "close-job"]


def test_windows_job_assignment_failure_terminates_the_still_suspended_child() -> None:
    contain = getattr(ollama_runtime, "_contain_suspended_windows_process")
    process = _FakeProcess()
    resumed = False

    def fail_assignment(_process: Any) -> None:
        raise OllamaRuntimeError("simulated job assignment failure")

    def resume(_process: Any) -> None:
        nonlocal resumed
        resumed = True

    with pytest.raises(OllamaRuntimeError, match="job assignment failure"):
        contain(
            process,
            create_job=fail_assignment,
            resume_process=resume,
            deadline=time.monotonic() + 1.0,
        )

    assert resumed is False
    assert process.terminate_calls == 1
    assert process.poll() is not None


def test_windows_resume_failure_terminates_the_assigned_job() -> None:
    contain = getattr(ollama_runtime, "_contain_suspended_windows_process")
    process = _FakeProcess()
    events: list[str] = []

    class FakeJob:
        def terminate(self, *, deadline: float) -> None:
            assert deadline > 0
            events.append("terminate-job")
            process.returncode = 0

        def close(self) -> None:
            events.append("close-job")

    with pytest.raises(OllamaRuntimeError, match="could not be resumed"):
        contain(
            process,
            create_job=lambda _process: FakeJob(),
            resume_process=lambda _process: (_ for _ in ()).throw(OSError("resume failed")),
            deadline=time.monotonic() + 1.0,
        )

    assert events == ["terminate-job", "close-job"]
    assert process.poll() is not None


def test_windows_teardown_fails_closed_when_taskkill_cannot_prove_the_tree_is_gone() -> None:
    tree_terminator = getattr(ollama_runtime, "_terminate_windows_process_tree")
    process = _ExitedProcess()

    with pytest.raises(OllamaRuntimeError, match="prove managed Ollama teardown"):
        tree_terminator(
            process,
            run_command=lambda *_args, **_kwargs: SimpleNamespace(returncode=128),
        )


def test_windows_expired_deadline_still_signals_the_owned_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree_terminator = getattr(ollama_runtime, "_terminate_windows_process_tree")
    process = _FakeProcess()
    monkeypatch.setattr(ollama_runtime.time, "monotonic", lambda: 1.0)

    with pytest.raises(OllamaRuntimeError, match="prove managed Ollama teardown"):
        tree_terminator(
            process,
            deadline=1.0,
            run_command=lambda *_args, **_kwargs: pytest.fail("expired teardown must not start taskkill"),
        )

    assert process.terminate_calls == 1


def test_windows_graceful_timeout_reserves_force_budget_and_signals_the_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree_terminator = getattr(ollama_runtime, "_terminate_windows_process_tree")
    process = _FakeProcess()
    clock = [0.0]
    commands: list[list[str]] = []
    timeouts: list[float] = []
    monkeypatch.setattr(ollama_runtime.time, "monotonic", lambda: clock[0])

    def run_command(command: list[str], *, timeout: float, **_kwargs: Any) -> None:
        commands.append(command)
        timeouts.append(timeout)
        clock[0] += timeout
        raise subprocess.TimeoutExpired(command, timeout)

    with pytest.raises(OllamaRuntimeError, match="prove managed Ollama teardown"):
        tree_terminator(process, deadline=1.0, run_command=run_command)

    assert commands == [
        ["taskkill", "/PID", str(process.pid), "/T"],
        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
    ]
    assert 0.0 < timeouts[0] < 1.0
    assert 0.0 < timeouts[1] <= 1.0 - timeouts[0]
    assert clock[0] <= 1.0
    assert process.terminate_calls == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group assertion")
def test_stop_retains_failed_ownership_when_tree_teardown_is_unproved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = _FakeProcess()
    monkeypatch.setattr(
        ollama_runtime.os,
        "killpg",
        lambda *_args: (_ for _ in ()).throw(PermissionError("denied")),
    )
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    runtime._process = process

    with pytest.raises(OllamaRuntimeError, match="prove managed Ollama teardown"):
        runtime.stop()

    assert runtime._process is process
    status = runtime.status()
    assert status["state"] == "failed"
    assert status["managed_process"] is True

    external = OllamaRuntime(tmp_path / "external", probe=lambda: "0.32.0")
    external.stop()
    assert external.status()["external_process"] is True


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group assertion")
def test_posix_teardown_never_signals_the_group_after_reaping_its_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess()
    clock = [0.0]
    signals: list[int] = []

    def killpg(_process_group: int, sent_signal: int) -> None:
        if sent_signal == signal.SIGTERM:
            signals.append(sent_signal)
            process.returncode = 0
            return
        if sent_signal == 0:
            clock[0] += 0.02
            return
        signals.append(sent_signal)

    monkeypatch.setattr(ollama_runtime.os, "killpg", killpg)
    monkeypatch.setattr(ollama_runtime.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(ollama_runtime.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))

    with pytest.raises(OllamaRuntimeError, match="prove managed Ollama teardown"):
        ollama_runtime._terminate_posix_process_tree(process, deadline=0.1)

    assert signals == [signal.SIGTERM]


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group assertion")
def test_stop_holds_the_process_lock_while_signalling_the_owned_group(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = _FakeProcess()
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    runtime._process = process
    observer_started = threading.Event()
    observer_finished = threading.Event()
    observer: threading.Thread | None = None

    def observe_status() -> None:
        observer_started.set()
        runtime.status()
        observer_finished.set()

    def terminate(owned_process: Any, **_kwargs: Any) -> None:
        nonlocal observer
        observer = threading.Thread(target=observe_status)
        observer.start()
        assert observer_started.wait(timeout=1.0)
        assert observer_finished.wait(timeout=0.05) is False
        owned_process.returncode = 0

    monkeypatch.setattr(ollama_runtime, "_terminate_process_tree", terminate)

    runtime.stop()

    assert observer is not None
    observer.join(timeout=1.0)
    assert observer_finished.is_set()


def test_status_holds_the_process_lock_while_proving_listener_ownership(tmp_path: Path) -> None:
    process = _FakeProcess()
    runtime = OllamaRuntime(tmp_path, probe=lambda: "0.32.0")
    runtime._process = process
    observer_started = threading.Event()
    observer_finished = threading.Event()
    observer: threading.Thread | None = None

    def observe_process_lock() -> None:
        observer_started.set()
        with runtime._process_lock:
            observer_finished.set()

    def listener_owned(_process: Any) -> bool:
        nonlocal observer
        observer = threading.Thread(target=observe_process_lock)
        observer.start()
        assert observer_started.wait(timeout=1.0)
        assert observer_finished.wait(timeout=0.05) is False
        return True

    runtime._listener_is_owned = listener_owned

    assert runtime.status()["managed_process"] is True

    assert observer is not None
    observer.join(timeout=1.0)
    assert observer_finished.is_set()


def test_status_holds_the_process_lock_while_probing_the_captured_process(tmp_path: Path) -> None:
    process = _FakeProcess()
    probe_started = threading.Event()
    observer_finished = threading.Event()
    observer: threading.Thread | None = None

    def observe_process_lock() -> None:
        with runtime._process_lock:
            observer_finished.set()

    def probe() -> str:
        nonlocal observer
        probe_started.set()
        observer = threading.Thread(target=observe_process_lock)
        observer.start()
        assert observer_finished.wait(timeout=0.05) is False
        return "0.32.0"

    runtime = OllamaRuntime(tmp_path, probe=probe, listener_owner=lambda owned: owned is process)
    runtime._process = process

    assert runtime.status()["ready"] is True
    assert probe_started.is_set()
    assert observer is not None
    observer.join(timeout=1.0)
    assert observer_finished.is_set()


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group assertion")
def test_shutdown_uses_one_deadline_and_retains_unproved_ownership(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    clock = [0.0]
    waits: list[float] = []

    class NeverExitsProcess(_FakeProcess):
        def wait(self, timeout: float | None = None) -> int:
            bounded_timeout = float(timeout or 0.0)
            waits.append(bounded_timeout)
            clock[0] += bounded_timeout
            raise ollama_runtime.subprocess.TimeoutExpired("ollama", bounded_timeout)

    process = NeverExitsProcess()
    monkeypatch.setattr(ollama_runtime.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(ollama_runtime.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(ollama_runtime.os, "killpg", lambda *_args: None)
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    runtime._process = process

    assert runtime.shutdown(timeout=0.25) is False
    assert waits
    assert all(0 <= wait <= 0.25 for wait in waits)
    assert clock[0] <= 0.25
    assert runtime._process is process
    assert runtime.status()["state"] == "failed"


@pytest.mark.unit
def test_shutdown_reserves_deadline_for_forcing_an_owned_child(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Shutdown spends only the inference grace waiting, then forces the child with the rest.

    ``shutdown`` derives one deadline from its timeout and bounds the operation
    control, the state lock, the inference drain, the teardown and the worker wait on
    it. The behaviour pinned here is the split: an inference that never finishes may
    consume the *grace* half of the budget, after which the child is forced and the
    teardown is reported as ``forced`` — with the remainder of the deadline still
    unspent, which is what "reserves deadline for forcing" names.

    The clock is driven so that only the grace expires. Against real time the same
    assertion additionally requires a loaded runner to complete two lock acquisitions,
    a process teardown, a status snapshot and a worker wait inside the leftover 25 ms.
    """
    clock = _DrivenClock()
    process = _FakeProcess()
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    runtime._process = process
    runtime._active_inferences = 1
    monkeypatch.setattr(
        ollama_runtime,
        "_terminate_process_tree",
        lambda owned_process, **_kwargs: setattr(owned_process, "returncode", -9),
    )
    clock.install(monkeypatch)
    clock.drive_condition(monkeypatch, runtime._lifecycle_condition)

    assert runtime.shutdown(timeout=0.05) is True
    assert process.poll() is not None
    assert runtime.status()["teardown"]["mode"] == "forced"

    # The drain waited for the inference grace (half the 50 ms budget) and nothing
    # else touched the clock, so half the deadline was still reserved for forcing.
    assert clock.waits == [pytest.approx(0.025)]
    assert clock.elapsed == pytest.approx(0.025)

    runtime._active_inferences = 0


def test_synchronous_mutation_caps_its_wait_for_an_active_inference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    runtime._active_inferences = 1
    monkeypatch.setattr(ollama_runtime, "_SYNC_LIFECYCLE_WAIT_SECONDS", 0.0)

    with pytest.raises(OllamaRuntimeError, match="inference did not finish"):
        runtime.rollback()

    assert runtime._lifecycle_transition is False


def test_integrity_hashing_stops_when_the_teardown_deadline_expires(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = tmp_path / "runtime.bin"
    payload.write_bytes(b"x" * (2 * 1024 * 1024))
    clock = iter((0.0, 2.0))
    monkeypatch.setattr(ollama_runtime.time, "monotonic", lambda: next(clock))

    with pytest.raises(OllamaRuntimeError, match="integrity verification timed out"):
        ollama_runtime._sha256_file(payload, deadline=1.0)


def test_install_metadata_read_rejects_an_oversized_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    runtime.install_dir.mkdir(parents=True)
    manifest = runtime.install_dir / ollama_runtime._INSTALL_MANIFEST_NAME
    payload = json.dumps({"schema": 2, "files": []}).encode("utf-8")
    manifest.write_bytes(payload)
    monkeypatch.setattr(
        ollama_runtime,
        "_MAX_INSTALL_MANIFEST_BYTES",
        len(payload) - 1,
        raising=False,
    )

    with pytest.raises(OllamaRuntimeError, match="integrity verification failed"):
        runtime._read_install_json(manifest)


def test_shutdown_never_signals_a_child_inherited_from_an_owner_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    child = _FakeProcess()
    runtime._write_process_owner_record(
        {
            "schema": 1,
            "backend_pid": os.getpid(),
            "backend_create_time": runtime._process_create_time(os.getpid(), strict=True),
            "child_pid": child.pid,
            "child_create_time": 2.0,
            "port": 43127,
            "executable_sha256": "a" * 64,
        }
    )
    monkeypatch.setattr(runtime, "_process_identity_is_alive", lambda *_args: True)
    termination_attempted = False

    def terminate(*_args: Any, **_kwargs: Any) -> None:
        nonlocal termination_attempted
        termination_attempted = True

    monkeypatch.setattr(ollama_runtime, "_terminate_process_tree", terminate)

    assert runtime.shutdown(timeout=0.25) is False
    assert termination_attempted is False
    assert runtime._process_owner_path().exists()


def test_process_owner_read_receives_the_stale_recovery_deadline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = OllamaRuntime(tmp_path / "workspace", probe=lambda: None)
    runtime._write_process_owner_record(
        {
            "schema": 1,
            "backend_pid": 99991,
            "backend_create_time": 1.0,
            "child_pid": 99992,
            "child_create_time": 2.0,
            "port": 0,
            "executable_sha256": "a" * 64,
        }
    )
    expected_deadline = time.monotonic() + 1.0
    observed_deadlines: list[float | None] = []
    read_private_regular_file = ollama_runtime._read_private_regular_file

    def observe_owner_read(path: Path, **kwargs: Any) -> bytes:
        if path == runtime._process_owner_path():
            observed_deadlines.append(kwargs.get("deadline"))
            raise OllamaRuntimeError("injected owner-read stop")
        return read_private_regular_file(path, **kwargs)

    monkeypatch.setattr(ollama_runtime, "_read_private_regular_file", observe_owner_read)

    with pytest.raises(OllamaRuntimeError, match="ownership state is invalid"):
        runtime._recover_stale_owned_process(deadline=expected_deadline)

    assert observed_deadlines == [expected_deadline]


def test_internal_stop_skips_install_scan_when_status_is_not_requested(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    runtime._process = _ExitedProcess()
    monkeypatch.setattr(
        runtime,
        "_status_snapshot",
        lambda *_args, **_kwargs: pytest.fail("internal stop unexpectedly scanned install status"),
    )

    assert runtime._stop_owned_process(cancel_operation=False, probe_status=False) == {}


def test_stop_bounds_its_post_teardown_status_verification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    runtime._process = _ExitedProcess()
    observed_deadlines: list[float | None] = []

    def snapshot(*, probe_server: bool = False, verification_deadline: float | None = None) -> dict[str, Any]:
        assert probe_server is False
        observed_deadlines.append(verification_deadline)
        return {"stopped": True}

    monkeypatch.setattr(runtime, "_status_snapshot", snapshot)

    assert runtime.stop(timeout_seconds=0.25) == {"stopped": True}
    assert len(observed_deadlines) == 1
    assert observed_deadlines[0] is not None


def test_list_models_returns_a_bounded_live_server_shape(tmp_path: Path) -> None:
    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        request_json=lambda method, path, payload: {
            "models": [
                {
                    "name": "qwen3:8b",
                    "model": "qwen3:8b",
                    "size": 5_000_000_000,
                    "digest": "a" * 64,
                    "modified_at": "2026-07-14T00:00:00Z",
                    "details": {"family": "qwen3"},
                    "private_internal": "must not leak",
                }
            ]
        },
    )
    runtime._process = _FakeProcess()

    models = runtime.list_models()

    assert models == [
        {
            "name": "qwen3:8b",
            "model": "qwen3:8b",
            "size": 5_000_000_000,
            "digest": "a" * 64,
            "modified_at": "2026-07-14T00:00:00Z",
            "details": {"family": "qwen3"},
        }
    ]


def test_model_inventory_rejects_more_than_the_authoritative_limit_without_reconciling_trust(
    tmp_path: Path,
) -> None:
    digest = "a" * 64
    locked_alias = ollama_runtime._locked_model_alias(digest)
    models = [
        {"name": f"model-{index}:latest", "model": f"model-{index}:latest", "digest": f"{index:064x}"}
        for index in range(500)
    ]
    models.append({"name": locked_alias, "model": locked_alias, "digest": digest})
    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        request_json=lambda _method, _path, _payload: {"models": models},
    )
    runtime._process = _FakeProcess()
    runtime._write_model_trust_state({locked_alias: digest}, {})

    with pytest.raises(OllamaRuntimeError, match="too many models"):
        runtime.list_models()

    assert runtime._read_model_trust_state() == ({locked_alias: digest}, {})


def test_model_inventory_cannot_erase_a_concurrent_digest_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    digest = "a" * 64
    locked_alias = ollama_runtime._locked_model_alias(digest)
    models = {"qwen3:8b": digest}
    list_reached_reconcile = threading.Event()
    release_list = threading.Event()
    acceptance_done = threading.Event()
    errors: list[BaseException] = []

    def request_json(method: str, path: str, payload: Any) -> dict[str, Any] | None:
        if method == "POST" and path == "/api/copy":
            models[str(payload["destination"])] = models[str(payload["source"])]
            return None
        return {
            "models": [
                {"name": name, "model": name, "digest": model_digest}
                for name, model_digest in models.items()
            ]
        }

    runtime = OllamaRuntime(tmp_path, probe=lambda: "0.32.0", request_json=request_json)
    runtime._process = _FakeProcess()
    reconcile = runtime._reconcile_model_trust_state

    def block_reconcile(raw_models: list[dict[str, Any]]) -> None:
        list_reached_reconcile.set()
        assert release_list.wait(timeout=2.0)
        reconcile(raw_models)

    monkeypatch.setattr(runtime, "_reconcile_model_trust_state", block_reconcile)

    def list_inventory() -> None:
        try:
            runtime.list_models()
        except BaseException as exc:  # noqa: BLE001 - asserted by the parent
            errors.append(exc)

    def accept_digest() -> None:
        try:
            runtime.accept_model_digest("qwen3:8b", digest)
        except BaseException as exc:  # noqa: BLE001 - asserted by the parent
            errors.append(exc)
        finally:
            acceptance_done.set()

    list_thread = threading.Thread(target=list_inventory)
    accept_thread = threading.Thread(target=accept_digest)
    list_thread.start()
    assert list_reached_reconcile.wait(timeout=2.0)
    accept_thread.start()
    time.sleep(0.05)
    release_list.set()
    list_thread.join(timeout=2.0)
    accept_thread.join(timeout=2.0)

    assert not list_thread.is_alive()
    assert not accept_thread.is_alive()
    assert acceptance_done.is_set()
    assert errors == []
    assert runtime._read_model_trust_state() == (
        {locked_alias: digest},
        {"qwen3:8b": locked_alias},
    )


def test_external_listener_cannot_be_used_for_managed_model_operations(tmp_path: Path) -> None:
    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        request_json=lambda *_args: {"models": []},
        puller=lambda *_args: None,
    )

    with pytest.raises(OllamaRuntimeError, match="managed Ollama server is not ready"):
        runtime.list_models()
    with pytest.raises(OllamaRuntimeError, match="managed Ollama server is not ready"):
        runtime.pull_model("qwen3:8b")


@pytest.mark.parametrize("model", ["", " qwen3:8b", "qwen3 8b", "../qwen", "qwen\n3"])
def test_pull_model_rejects_non_canonical_identifiers(tmp_path: Path, model: str) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: "0.32.0")

    with pytest.raises(ValueError, match="canonical model identifier"):
        runtime.pull_model(model)


def test_pull_model_reports_streamed_progress(tmp_path: Path) -> None:
    updates: list[tuple[int, int, str]] = []

    def puller(model: str, progress: Any) -> None:
        assert model == "qwen3:8b"
        digest = f"sha256:{'a' * 64}"
        progress(50, 100, "pulling layer", digest)
        progress(100, 100, "success", digest)

    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        puller=puller,
        request_json=lambda *_args: {
            "models": [{"name": "qwen3:8b", "model": "qwen3:8b", "digest": "a" * 64}]
        },
    )
    runtime._process = _FakeProcess()

    runtime.pull_model("qwen3:8b", on_progress=lambda done, total, status: updates.append((done, total, status)))

    assert updates == [(50, 100, "pulling layer"), (100, 100, "success")]
    assert runtime.status()["model_pull"] == {
        "model": "qwen3:8b",
        "status": "awaiting_digest_acceptance",
        "completed": 100,
        "total": 100,
        "error": None,
        "digest": "a" * 64,
        "previous_digest": None,
        "digest_changed": False,
        "acceptance_required": True,
    }
    assert runtime._read_accepted_model_digests() == {}


def test_pull_model_rejects_a_reported_total_above_the_hard_limit(tmp_path: Path) -> None:
    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        puller=lambda _model, progress: progress(
            0,
            10**18,
            "pulling layer",
            f"sha256:{'a' * 64}",
        ),
        disk_usage=lambda _path: SimpleNamespace(free=10**18),
    )
    runtime._process = _FakeProcess()

    with pytest.raises(OllamaRuntimeError, match="model pull exceeds the size limit"):
        runtime.pull_model("qwen3:8b")


def test_pull_model_enforces_the_aggregate_model_store_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(ollama_runtime, "_MAX_MODEL_STORE_BYTES", 100)
    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        puller=lambda _model, progress: progress(
            0,
            30,
            "pulling layer",
            f"sha256:{'a' * 64}",
        ),
        disk_usage=lambda _path: SimpleNamespace(free=10**12),
    )
    runtime._process = _FakeProcess()
    blob = runtime.models_dir / "blobs" / "existing"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"x" * 80)

    with pytest.raises(OllamaRuntimeError, match="model store size limit"):
        runtime.pull_model("qwen3:8b")


def test_pull_model_enforces_the_aggregate_managed_workspace_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(ollama_runtime, "_MAX_MODEL_STORE_BYTES", 1_000)
    monkeypatch.setattr(ollama_runtime, "_MAX_MANAGED_STORAGE_BYTES", 100)
    monkeypatch.setattr(ollama_runtime, "_MAX_LOG_STORAGE_BYTES", 0)
    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        puller=lambda _model, progress: progress(
            0,
            30,
            "pulling layer",
            f"sha256:{'a' * 64}",
        ),
        disk_usage=lambda _path: SimpleNamespace(free=10**12),
    )
    runtime._process = _FakeProcess()
    runtime.log_path.parent.mkdir(parents=True)
    runtime.log_path.write_bytes(b"x" * 80)

    with pytest.raises(OllamaRuntimeError, match="managed storage size limit"):
        runtime.pull_model("qwen3:8b")


def test_pull_model_refuses_an_unsafe_model_store(tmp_path: Path) -> None:
    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        puller=lambda _model, progress: progress(
            0,
            1,
            "pulling layer",
            f"sha256:{'a' * 64}",
        ),
    )
    runtime._process = _FakeProcess()
    outside = tmp_path / "outside"
    outside.write_bytes(b"x")
    runtime.models_dir.mkdir(parents=True)
    try:
        (runtime.models_dir / "linked").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    with pytest.raises(OllamaRuntimeError, match="model store is unsafe"):
        runtime.pull_model("qwen3:8b")


def test_pull_model_caps_the_aggregate_of_unique_layers(tmp_path: Path) -> None:
    gibibyte = 1024**3

    def puller(_model: str, progress: Any) -> None:
        progress(0, 40 * gibibyte, "pulling first layer", f"sha256:{'a' * 64}")
        progress(0, 30 * gibibyte, "pulling second layer", f"sha256:{'b' * 64}")

    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        puller=puller,
        disk_usage=lambda _path: SimpleNamespace(free=100 * gibibyte),
    )
    runtime._process = _FakeProcess()

    with pytest.raises(OllamaRuntimeError, match="model pull exceeds the size limit"):
        runtime.pull_model("qwen3:8b")


def test_pull_model_rejects_negative_layer_progress(tmp_path: Path) -> None:
    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        puller=lambda _model, progress: progress(
            -1,
            10,
            "pulling layer",
            f"sha256:{'a' * 64}",
        ),
    )
    runtime._process = _FakeProcess()

    with pytest.raises(OllamaRuntimeError, match="invalid model pull progress"):
        runtime.pull_model("qwen3:8b")


def test_pull_model_rejects_a_changed_layer_total(tmp_path: Path) -> None:
    digest = f"sha256:{'a' * 64}"

    def puller(_model: str, progress: Any) -> None:
        progress(0, 100, "pulling layer", digest)
        progress(1, 101, "pulling layer", digest)

    runtime = OllamaRuntime(tmp_path, probe=lambda: "0.32.0", puller=puller)
    runtime._process = _FakeProcess()

    with pytest.raises(OllamaRuntimeError, match="changed model layer total"):
        runtime.pull_model("qwen3:8b")


def test_pull_model_rejects_byte_progress_without_a_digest(tmp_path: Path) -> None:
    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        puller=lambda _model, progress: progress(1, 10, "pulling layer"),
    )
    runtime._process = _FakeProcess()

    with pytest.raises(OllamaRuntimeError, match="requires a layer digest"):
        runtime.pull_model("qwen3:8b")


def test_pull_model_rejects_mixed_aggregate_and_layer_progress(tmp_path: Path) -> None:
    def puller(_model: str, progress: Any) -> None:
        progress(0, 100, "pulling aggregate", "sha256:model")
        progress(0, 50, "pulling layer", f"sha256:{'a' * 64}")

    runtime = OllamaRuntime(tmp_path, probe=lambda: "0.32.0", puller=puller)
    runtime._process = _FakeProcess()

    with pytest.raises(OllamaRuntimeError, match="mixed model pull progress modes"):
        runtime.pull_model("qwen3:8b")


def test_pull_model_accepts_the_aggregate_progress_sentinel(tmp_path: Path) -> None:
    updates: list[tuple[int, int, str]] = []

    def puller(_model: str, progress: Any) -> None:
        progress(40, 100, "pulling aggregate", "sha256:model")
        progress(100, 100, "success", "sha256:model")

    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        puller=puller,
        request_json=lambda *_args: {
            "models": [{"name": "qwen3:8b", "model": "qwen3:8b", "digest": "a" * 64}]
        },
    )
    runtime._process = _FakeProcess()

    result = runtime.pull_model(
        "qwen3:8b",
        on_progress=lambda completed, total, status: updates.append((completed, total, status)),
    )

    assert result["status"] == "awaiting_digest_acceptance"
    assert result["acceptance_required"] is True
    assert updates == [(40, 100, "pulling aggregate"), (100, 100, "success")]


def test_pull_model_aggregates_duplicate_and_out_of_order_layer_progress(tmp_path: Path) -> None:
    updates: list[tuple[int, int, str]] = []
    first = f"sha256:{'a' * 64}"
    second = f"sha256:{'b' * 64}"

    def puller(_model: str, progress: Any) -> None:
        progress(40, 100, "first", first)
        progress(20, 100, "stale first", first)
        progress(40, 100, "duplicate first", first)
        progress(10, 50, "second", second)
        progress(100, 100, "first complete", first)
        progress(50, 50, "success", second)

    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        puller=puller,
        request_json=lambda *_args: {
            "models": [{"name": "qwen3:8b", "model": "qwen3:8b", "digest": "c" * 64}]
        },
    )
    runtime._process = _FakeProcess()

    runtime.pull_model(
        "qwen3:8b",
        on_progress=lambda completed, total, status: updates.append((completed, total, status)),
    )

    assert updates == [
        (40, 100, "first"),
        (40, 100, "stale first"),
        (40, 100, "duplicate first"),
        (50, 150, "second"),
        (110, 150, "first complete"),
        (150, 150, "success"),
    ]


@pytest.mark.parametrize(
    ("completed", "total"),
    [(True, 10), (1, False), ("1", 10), (1, "10"), (1.5, 10), (11, 10), (0, -1)],
)
def test_pull_model_rejects_malformed_layer_counters(
    tmp_path: Path,
    completed: Any,
    total: Any,
) -> None:
    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        puller=lambda _model, progress: progress(
            completed,
            total,
            "pulling layer",
            f"sha256:{'a' * 64}",
        ),
    )
    runtime._process = _FakeProcess()

    with pytest.raises(OllamaRuntimeError, match="invalid model pull progress"):
        runtime.pull_model("qwen3:8b")


def test_pull_model_projects_disk_across_interleaved_layers(tmp_path: Path) -> None:
    reserve = ollama_runtime._MODEL_PULL_DISK_RESERVE_BYTES

    def puller(_model: str, progress: Any) -> None:
        progress(50, 100, "first", f"sha256:{'a' * 64}")
        progress(0, 100, "second", f"sha256:{'b' * 64}")

    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        puller=puller,
        disk_usage=lambda _path: SimpleNamespace(free=reserve + 149),
    )
    runtime._process = _FakeProcess()

    with pytest.raises(OllamaRuntimeError, match="free disk space for the Ollama model"):
        runtime.pull_model("qwen3:8b")


def test_pull_model_rejects_a_reported_total_that_cannot_fit(tmp_path: Path) -> None:
    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        puller=lambda _model, progress: progress(
            0,
            5_000_000_000,
            "pulling layer",
            f"sha256:{'a' * 64}",
        ),
        disk_usage=lambda _path: SimpleNamespace(free=1_000_000_000),
    )
    runtime._process = _FakeProcess()

    with pytest.raises(OllamaRuntimeError, match="free disk space for the Ollama model"):
        runtime.pull_model("qwen3:8b")


def test_pull_model_rejects_completion_without_accounted_byte_progress(tmp_path: Path) -> None:
    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        puller=lambda _model, progress: progress(0, 0, "success"),
        request_json=lambda *_args: {
            "models": [{"name": "qwen3:8b", "model": "qwen3:8b", "digest": "a" * 64}]
        },
    )
    runtime._process = _FakeProcess()

    with pytest.raises(OllamaRuntimeError, match="accounted byte progress"):
        runtime.pull_model("qwen3:8b")

    assert not runtime._model_digests_path().exists()


def test_model_pull_preserves_digest_and_reports_later_tag_drift(tmp_path: Path) -> None:
    source_digest = ["a" * 64]
    copied: dict[str, str] = {}

    def puller(_model: str, progress: Any) -> None:
        progress(100, 100, "success", f"sha256:{'a' * 64}")

    def request_json(method: str, path: str, payload: Any) -> dict[str, Any] | None:
        if method == "POST" and path == "/api/copy":
            copied[str(payload["destination"])] = source_digest[0]
            return None
        return {
            "models": [
                {"name": "qwen3:8b", "model": "qwen3:8b", "digest": source_digest[0]},
                *[
                    {"name": name, "model": name, "digest": digest}
                    for name, digest in copied.items()
                ],
            ]
        }

    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        puller=puller,
        request_json=request_json,
    )
    runtime._process = _FakeProcess()

    first = runtime.pull_model("qwen3:8b")
    accepted = runtime.accept_model_digest("qwen3:8b", "a" * 64)
    accepted_pull = runtime.status()["model_pull"]
    source_digest[0] = "b" * 64
    second = runtime.pull_model("qwen3:8b")
    source_digest[0] = "c" * 64
    models = runtime.list_models()

    assert first["digest"] == "a" * 64
    assert first["digest_changed"] is False
    assert first["acceptance_required"] is True
    assert accepted["model"] == ollama_runtime._locked_model_alias("a" * 64)
    assert accepted_pull["status"] == "accepted"
    assert accepted_pull["acceptance_required"] is False
    assert second["digest"] == "b" * 64
    assert second["previous_digest"] == "a" * 64
    assert second["digest_changed"] is True
    assert second["acceptance_required"] is True
    assert second["status"] == "awaiting_digest_acceptance"
    source = next(model for model in models if model.get("name") == "qwen3:8b")
    assert source["accepted_digest"] == "a" * 64
    assert source["digest_drift"] is True
    assert runtime.status()["model_digest_drift"] == {"qwen3:8b": {"accepted": "a" * 64, "current": "c" * 64}}


def test_changed_model_digest_requires_exact_explicit_acceptance(tmp_path: Path) -> None:
    current_digest = ["b" * 64]
    copied: dict[str, str] = {}

    def request_json(method: str, path: str, payload: Any) -> dict[str, Any] | None:
        if method == "POST" and path == "/api/copy":
            copied[str(payload["destination"])] = current_digest[0]
            return None
        return {
            "models": [
                {
                    "name": "qwen3:8b",
                    "model": "qwen3:8b",
                    "digest": current_digest[0],
                },
                *[
                    {"name": name, "model": name, "digest": digest}
                    for name, digest in copied.items()
                ],
            ]
        }

    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        request_json=request_json,
    )
    runtime._process = _FakeProcess()
    previous_alias = ollama_runtime._locked_model_alias("a" * 64)
    runtime._write_model_trust_state({previous_alias: "a" * 64}, {"qwen3:8b": previous_alias})

    with pytest.raises(OllamaRuntimeError, match="does not match the installed model"):
        runtime.accept_model_digest("qwen3:8b", "c" * 64)

    result = runtime.accept_model_digest("qwen3:8b", "b" * 64)

    locked_alias = ollama_runtime._locked_model_alias("b" * 64)
    assert result == {
        "accepted": True,
        "source_model": "qwen3:8b",
        "model": locked_alias,
        "digest": "b" * 64,
    }
    assert runtime._read_accepted_model_digests() == {locked_alias: "b" * 64}
    assert runtime.model_is_accepted("qwen3:8b") is False
    assert runtime.model_is_accepted(locked_alias) is True


def test_reset_model_digest_state_removes_only_corrupt_trust_metadata(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    runtime.models_dir.mkdir(parents=True)
    digest_state = runtime._model_digests_path()
    runtime._ensure_managed_directory(runtime.trust_dir, create=True)
    digest_state.write_text("{not-json", encoding="utf-8")
    model_blob = runtime.models_dir / "blobs" / f"sha256-{'a' * 64}"
    model_blob.parent.mkdir()
    model_blob.write_bytes(b"model-data")

    result = runtime.reset_model_digest_state()

    assert result["reset"] is True
    assert not digest_state.exists()
    assert model_blob.read_bytes() == b"model-data"


def test_reset_model_digest_state_unlinks_a_symlink_without_touching_its_target(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    runtime.models_dir.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("sensitive", encoding="utf-8")
    digest_state = runtime._model_digests_path()
    runtime._ensure_managed_directory(runtime.trust_dir, create=True)
    try:
        digest_state.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    result = runtime.reset_model_digest_state()

    assert result["reset"] is True
    assert not digest_state.exists()
    assert outside.read_text(encoding="utf-8") == "sensitive"


def test_reset_model_digest_state_refuses_a_symlinked_trust_ancestor(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside-trust"
    outside.mkdir()
    digest_state = outside / ollama_runtime._MODEL_DIGESTS_NAME
    digest_state.write_text("{not-json", encoding="utf-8")
    (workspace / "trust").mkdir(parents=True)
    try:
        (workspace / "trust" / "ollama").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this platform")
    runtime = OllamaRuntime(workspace, probe=lambda: None)

    with pytest.raises(OllamaRuntimeError, match="managed Ollama path is unsafe"):
        runtime.reset_model_digest_state()

    assert digest_state.read_text(encoding="utf-8") == "{not-json"


def test_reset_model_digest_state_refuses_to_discard_valid_metadata(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    runtime._write_accepted_model_digests({"qwen3:8b": "a" * 64})

    with pytest.raises(OllamaRuntimeError, match="already valid"):
        runtime.reset_model_digest_state()

    assert runtime._read_accepted_model_digests() == {"qwen3:8b": "a" * 64}


def test_model_pull_recognises_explicit_latest_but_still_requires_first_acceptance(tmp_path: Path) -> None:
    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        puller=lambda _model, progress: progress(1, 1, "success", f"sha256:{'a' * 64}"),
        request_json=lambda *_args: {
            "models": [{"name": "qwen3:latest", "model": "qwen3:latest", "digest": "a" * 64}]
        },
    )
    runtime._process = _FakeProcess()

    result = runtime.pull_model("qwen3")

    assert result["digest"] == "a" * 64
    assert result["status"] == "awaiting_digest_acceptance"
    assert result["acceptance_required"] is True
    assert "accepted_digest" not in runtime.list_models()[0]


def test_cancelled_pull_after_remote_progress_is_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    started = threading.Event()
    release = threading.Event()

    def puller(_model: str, progress: Any) -> None:
        started.set()
        assert release.wait(timeout=2.0)
        progress(1, 1, "success", f"sha256:{'a' * 64}")

    process = _FakeProcess()

    def killpg(_process_group: int, sent_signal: int) -> None:
        if sent_signal == 0:
            raise ProcessLookupError
        process.returncode = 0

    if os.name != "nt":
        monkeypatch.setattr(ollama_runtime.os, "killpg", killpg)
    runtime = OllamaRuntime(tmp_path, probe=lambda: "0.32.0", puller=puller)
    runtime._process = process

    queued = runtime.pull_model_async("qwen3:8b")
    assert started.wait(timeout=2.0)
    threading.Timer(0.05, release.set).start()
    runtime.stop(expected_operation_id=queued["operation"]["id"])

    assert runtime.wait_for_operation(timeout=2.0) is True
    status = runtime.status()
    assert status["operation"]["state"] == "indeterminate"
    assert status["operation"]["error"] == ollama_runtime._INDETERMINATE_OPERATION_ERROR
    assert status["unresolved_operation"]["id"] == queued["operation"]["id"]
    assert status["model_pull"]["status"] == "cancelled"


def test_stop_cancels_only_the_server_confirmed_operation(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)

    def operation() -> None:
        started.set()
        assert release.wait(timeout=2.0)
        runtime._raise_if_cancelled()

    queued = runtime._start_background("start", operation)
    operation_id = queued["operation"]["id"]
    assert isinstance(operation_id, str)
    assert operation_id.startswith("op_")
    assert started.wait(timeout=2.0)

    with pytest.raises(OllamaRuntimeError, match="operation ID is required"):
        runtime.stop(timeout_seconds=1.0)
    with pytest.raises(OllamaRuntimeError, match="no longer running"):
        runtime.stop(
            timeout_seconds=1.0,
            expected_operation_id=f"op_{'f' * 32}",
        )

    threading.Timer(0.05, release.set).start()
    runtime.stop(timeout_seconds=1.0, expected_operation_id=operation_id)

    assert runtime.wait_for_operation(timeout=1.0) is True
    assert runtime.status()["operation"]["state"] == "cancelled"


def test_stop_rejects_the_matching_id_after_the_operation_finishes(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    queued = runtime.start_async(timeout_seconds=0.0)
    operation_id = queued["operation"]["id"]
    assert runtime.wait_for_operation(timeout=2.0) is True
    assert runtime.status()["operation"]["state"] == "failed"

    with pytest.raises(OllamaRuntimeError, match="no longer running"):
        runtime.stop(expected_operation_id=operation_id)

    assert runtime.status()["teardown"]["state"] == "idle"


def test_shutdown_deadline_includes_operation_control_lock_admission(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    lock_held = threading.Event()
    release_lock = threading.Event()

    def hold_lock() -> None:
        with runtime._operation_control_lock:
            lock_held.set()
            assert release_lock.wait(timeout=2.0)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert lock_held.wait(timeout=2.0)
    started = time.monotonic()
    try:
        assert runtime.shutdown(timeout=0.05) is False
    finally:
        release_lock.set()
        holder.join(timeout=2.0)

    assert time.monotonic() - started < 0.5
    assert holder.is_alive() is False


def test_stop_deadline_includes_state_lock_admission(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    lock_held = threading.Event()
    release_lock = threading.Event()

    def hold_lock() -> None:
        with runtime._state_lock:
            lock_held.set()
            assert release_lock.wait(timeout=2.0)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert lock_held.wait(timeout=2.0)
    started = time.monotonic()
    try:
        with pytest.raises(OllamaRuntimeError, match="stop transition timed out"):
            runtime.stop(timeout_seconds=0.05)
    finally:
        release_lock.set()
        holder.join(timeout=2.0)

    assert time.monotonic() - started < 0.5
    assert holder.is_alive() is False


def test_shutdown_deadline_includes_state_lock_admission(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    lock_held = threading.Event()
    release_lock = threading.Event()

    def hold_lock() -> None:
        with runtime._state_lock:
            lock_held.set()
            assert release_lock.wait(timeout=2.0)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert lock_held.wait(timeout=2.0)
    started = time.monotonic()
    try:
        assert runtime.shutdown(timeout=0.05) is False
    finally:
        release_lock.set()
        holder.join(timeout=2.0)

    assert time.monotonic() - started < 0.5
    assert holder.is_alive() is False


def test_wait_for_operation_timeout_includes_state_lock_admission(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    lock_held = threading.Event()
    release_lock = threading.Event()

    def hold_lock() -> None:
        with runtime._state_lock:
            lock_held.set()
            assert release_lock.wait(timeout=2.0)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert lock_held.wait(timeout=2.0)
    started = time.monotonic()
    try:
        assert runtime.wait_for_operation(timeout=0.05) is False
    finally:
        release_lock.set()
        holder.join(timeout=2.0)

    assert time.monotonic() - started < 0.5
    assert holder.is_alive() is False


def test_operation_admission_is_idempotent_and_survives_backend_restart(tmp_path: Path) -> None:
    admission_id = f"adm_{'a' * 32}"
    calls = 0
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)

    def reset() -> dict[str, bool]:
        nonlocal calls
        calls += 1
        return {"reset": True}

    first, first_status = runtime.run_synchronous_operation(
        "reset_model_digests",
        admission_id,
        reset,
    )
    replay, replay_status = runtime.run_synchronous_operation(
        "reset_model_digests",
        admission_id,
        lambda: pytest.fail("an admitted operation must not execute twice"),
    )
    restarted = OllamaRuntime(tmp_path, probe=lambda: None)
    restored, restored_status = restarted.run_synchronous_operation(
        "reset_model_digests",
        admission_id,
        lambda: pytest.fail("a durable operation receipt must survive restart"),
    )

    assert calls == 1
    assert (first, first_status) == ({"reset": True}, 200)
    assert (replay, replay_status) == ({"reset": True}, 200)
    assert (restored, restored_status) == ({"reset": True}, 200)
    assert restarted.status()["operation"]["admission_id"] == admission_id


def test_operation_admission_replay_survives_later_operations(tmp_path: Path) -> None:
    first_admission = f"adm_{'a' * 32}"
    second_admission = f"adm_{'b' * 32}"
    calls: list[str] = []
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)

    first, _status = runtime.run_synchronous_operation(
        "reset_model_digests",
        first_admission,
        lambda: calls.append("first") or {"reset": True},
    )
    runtime.run_synchronous_operation(
        "reset_model_digests",
        second_admission,
        lambda: calls.append("second") or {"reset": True},
    )
    restarted = OllamaRuntime(tmp_path, probe=lambda: None)
    replay, replay_status = restarted.run_synchronous_operation(
        "reset_model_digests",
        first_admission,
        lambda: pytest.fail("an older admitted operation must not execute twice"),
    )

    assert calls == ["first", "second"]
    assert first == {"reset": True}
    assert (replay, replay_status) == ({"reset": True}, 200)


def test_model_pull_replay_keeps_the_admitted_model_and_digest(tmp_path: Path) -> None:
    first_admission = f"adm_{'a' * 32}"
    second_admission = f"adm_{'b' * 32}"
    first_digest = "a" * 64
    second_digest = "b" * 64
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)

    def pull_result(model: str, digest: str) -> dict[str, Any]:
        return {
            "model": model,
            "status": "awaiting_digest_acceptance",
            "completed": 1,
            "total": 1,
            "error": None,
            "digest": digest,
            "previous_digest": None,
            "digest_changed": False,
            "acceptance_required": True,
        }

    first, _status = runtime.run_synchronous_operation(
        "pull_model",
        first_admission,
        lambda: pull_result("model-a:latest", first_digest),
        operation_subject={"model": "model-a:latest"},
    )
    runtime.run_synchronous_operation(
        "pull_model",
        second_admission,
        lambda: pull_result("model-b:latest", second_digest),
        operation_subject={"model": "model-b:latest"},
    )
    replay, replay_status = runtime.run_synchronous_operation(
        "pull_model",
        first_admission,
        lambda: pytest.fail("a completed pull admission must not execute twice"),
        operation_subject={"model": "model-a:latest"},
    )
    restarted = OllamaRuntime(tmp_path, probe=lambda: None)
    restored, restored_status = restarted.run_synchronous_operation(
        "pull_model",
        first_admission,
        lambda: pytest.fail("a durable pull receipt must survive restart"),
        operation_subject={"model": "model-a:latest"},
    )

    assert first["model"] == replay["model"] == restored["model"] == "model-a:latest"
    assert first["digest"] == replay["digest"] == restored["digest"] == first_digest
    assert (replay_status, restored_status) == (200, 200)


def test_current_successful_model_receipt_requires_its_admitted_subject(tmp_path: Path) -> None:
    admission_id = f"adm_{'a' * 32}"
    digest = "a" * 64
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    runtime.run_synchronous_operation(
        "pull_model",
        admission_id,
        lambda: {
            "model": "model-a:latest",
            "status": "awaiting_digest_acceptance",
            "completed": 1,
            "total": 1,
            "error": None,
            "digest": digest,
            "previous_digest": None,
            "digest_changed": False,
            "acceptance_required": True,
        },
        operation_subject={"model": "model-a:latest"},
    )
    operation_path = runtime._operation_state_path()
    payload = json.loads(operation_path.read_text(encoding="utf-8"))
    payload["operations"][-1]["subject"] = None
    operation_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(OllamaRuntimeError, match="operation state is invalid"):
        OllamaRuntime(tmp_path, probe=lambda: None)


def test_legacy_subjectless_model_receipt_migrates_to_unknown_truth(tmp_path: Path) -> None:
    admission_id = f"adm_{'b' * 32}"
    digest = "b" * 64
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    runtime.run_synchronous_operation(
        "pull_model",
        admission_id,
        lambda: {
            "model": "model-b:latest",
            "status": "awaiting_digest_acceptance",
            "completed": 1,
            "total": 1,
            "error": None,
            "digest": digest,
            "previous_digest": None,
            "digest_changed": False,
            "acceptance_required": True,
        },
        operation_subject={"model": "model-b:latest"},
    )
    operation_path = runtime._operation_state_path()
    payload = json.loads(operation_path.read_text(encoding="utf-8"))
    payload["schema"] = 3
    payload["operations"][-1]["subject"] = None
    operation_path.write_text(json.dumps(payload), encoding="utf-8")

    restarted = OllamaRuntime(tmp_path, probe=lambda: None)

    blocker = restarted.status()["unresolved_operation"]
    assert blocker["admission_id"] == admission_id
    assert blocker["state"] == "indeterminate"
    assert blocker["result"] is None
    migrated = json.loads(operation_path.read_text(encoding="utf-8"))
    assert migrated["schema"] == 4
    assert migrated["operations"][-1]["state"] == "indeterminate"


def test_reconciled_legacy_subjectless_model_receipt_becomes_unresolved(tmp_path: Path) -> None:
    admission_id = f"adm_{'c' * 32}"
    digest = "c" * 64
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    runtime.run_synchronous_operation(
        "pull_model",
        admission_id,
        lambda: {
            "model": "model-c:latest",
            "status": "awaiting_digest_acceptance",
            "completed": 1,
            "total": 1,
            "error": None,
            "digest": digest,
            "previous_digest": None,
            "digest_changed": False,
            "acceptance_required": True,
        },
        operation_subject={"model": "model-c:latest"},
    )
    operation_path = runtime._operation_state_path()
    payload = json.loads(operation_path.read_text(encoding="utf-8"))
    operation = payload["operations"][-1]
    payload["schema"] = 3
    operation.update({
        "state": "indeterminate",
        "reconciled_at": operation["finished_at"],
        "subject": None,
        "error": "legacy unknown outcome",
        "result": None,
    })
    operation_path.write_text(json.dumps(payload), encoding="utf-8")

    restarted = OllamaRuntime(tmp_path, probe=lambda: None)

    blocker = restarted.status()["unresolved_operation"]
    assert blocker["admission_id"] == admission_id
    assert blocker["state"] == "indeterminate"
    migrated = json.loads(operation_path.read_text(encoding="utf-8"))["operations"][-1]
    assert migrated["reconciled_at"] is None
    callback_ran = False

    def callback() -> dict[str, bool]:
        nonlocal callback_ran
        callback_ran = True
        return {"reset": True}

    with pytest.raises(OllamaRuntimeError, match="operation outcome is unknown"):
        restarted.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'d' * 32}",
            callback,
        )
    assert callback_ran is False


def test_exception_after_model_mutation_started_is_indeterminate(tmp_path: Path) -> None:
    admission_id = f"adm_{'c' * 32}"
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)

    def mutate_then_lose_verification() -> dict[str, bool]:
        runtime._mark_operation_mutation_started()
        raise OllamaRuntimeError("post-mutation verification failed")

    with pytest.raises(OllamaRuntimeError, match="verification failed"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            admission_id,
            mutate_then_lose_verification,
        )

    operation = runtime.status()["operation"]
    assert operation["state"] == "indeterminate"
    assert operation["error"] == ollama_runtime._INDETERMINATE_OPERATION_ERROR
    with pytest.raises(OllamaRuntimeError, match="outcome is unknown"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'d' * 32}",
            lambda: pytest.fail("an unknown mutation must block fresh admissions"),
        )


def test_operation_journal_compacts_without_reexecuting_expired_admissions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first_admission = f"adm_{'1' * 32}"
    second_admission = f"adm_{'2' * 32}"
    third_admission = f"adm_{'3' * 32}"
    monkeypatch.setattr(ollama_runtime, "_MAX_OPERATION_RECEIPTS", 2)
    monkeypatch.setattr(ollama_runtime, "_OPERATION_SPENT_FILTER_BYTES", 64)
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    runtime.run_synchronous_operation(
        "reset_model_digests",
        first_admission,
        lambda: {"reset": True},
    )
    runtime.run_synchronous_operation(
        "reset_model_digests",
        second_admission,
        lambda: {"reset": True},
    )

    third, third_status = runtime.run_synchronous_operation(
        "reset_model_digests",
        third_admission,
        lambda: {"reset": True},
    )

    replay, replay_status = runtime.run_synchronous_operation(
        "reset_model_digests",
        second_admission,
        lambda: pytest.fail("a retained receipt must still replay without re-execution"),
    )
    with pytest.raises(OllamaRuntimeError, match="already consumed"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            first_admission,
            lambda: pytest.fail("an expired admission must never execute twice"),
        )

    restarted = OllamaRuntime(tmp_path, probe=lambda: None)
    with pytest.raises(OllamaRuntimeError, match="already consumed"):
        restarted.run_synchronous_operation(
            "reset_model_digests",
            first_admission,
            lambda: pytest.fail("a compacted admission must survive restart"),
        )

    assert (third, third_status) == ({"reset": True}, 200)
    assert (replay, replay_status) == ({"reset": True}, 200)
    persisted = json.loads(runtime._operation_state_path().read_text(encoding="utf-8"))
    assert persisted["schema"] == 4
    assert persisted["spent_admissions"]["count"] == 1


def test_schema_three_pull_without_result_migrates_to_unresolved_indeterminate_truth(tmp_path: Path) -> None:
    admission_id = f"adm_{'3' * 32}"
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    runtime.run_synchronous_operation(
        "reset_model_digests",
        admission_id,
        lambda: {"reset": True},
    )
    operation_path = runtime._operation_state_path()
    payload = json.loads(operation_path.read_text(encoding="utf-8"))
    legacy_pull = payload["operations"][-1]
    legacy_pull.update(
        {
            "kind": "pull_model",
            "subject": {"model": "qwen3:8b"},
            "result": None,
        }
    )
    payload["schema"] = 3
    operation_path.write_text(json.dumps(payload), encoding="utf-8")

    restarted = OllamaRuntime(tmp_path, probe=lambda: None)

    blocker = restarted.status()["unresolved_operation"]
    assert blocker["admission_id"] == admission_id
    assert blocker["kind"] == "pull_model"
    assert blocker["state"] == "indeterminate"
    assert "outcome is unknown" in blocker["error"]
    migrated = json.loads(operation_path.read_text(encoding="utf-8"))
    assert migrated["schema"] == 4
    restarted.reconcile_indeterminate_operation(blocker["id"], admission_id)
    assert restarted.status()["unresolved_operation"] is None


def test_operation_journal_compacts_before_the_byte_limit_is_reached(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(ollama_runtime, "_OPERATION_SPENT_FILTER_BYTES", 64)
    monkeypatch.setattr(ollama_runtime, "_MAX_OPERATION_STATE_BYTES", 4_000)
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    result = {
        "deleted": [],
        "pruned": [f"flinttrade/sha256-{index:064x}:locked" for index in range(20)],
    }

    for index in range(8):
        runtime.run_synchronous_operation(
            "prune_models",
            f"adm_{index:032x}",
            lambda: result,
        )

    persisted = json.loads(runtime._operation_state_path().read_text(encoding="utf-8"))
    assert runtime._operation_state_path().stat().st_size <= 4_000
    assert persisted["spent_admissions"]["count"] > 0
    restarted = OllamaRuntime(tmp_path, probe=lambda: None)
    with pytest.raises(OllamaRuntimeError, match="already consumed"):
        restarted.run_synchronous_operation(
            "prune_models",
            f"adm_{0:032x}",
            lambda: pytest.fail("a size-compacted admission must never execute twice"),
        )


def test_runtime_instances_share_one_durable_admission_journal(tmp_path: Path) -> None:
    admission_id = f"adm_{'c' * 32}"
    started = threading.Event()
    release = threading.Event()
    calls = 0
    first_runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    second_runtime = OllamaRuntime(tmp_path, probe=lambda: None)

    def operation() -> None:
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(timeout=2.0)

    first = first_runtime._start_background("start", operation, admission_id=admission_id)
    assert started.wait(timeout=2.0)
    retry = second_runtime._start_background(
        "start",
        lambda: pytest.fail("a shared admission must not start in a second runtime"),
        admission_id=admission_id,
    )
    release.set()
    assert first_runtime.wait_for_operation(timeout=2.0) is True

    assert calls == 1
    assert retry["operation"]["id"] == first["operation"]["id"]
    assert retry["operation"]["admission_id"] == admission_id
    assert "owner_pid" not in retry["operation"]
    assert "owner_create_time" not in retry["operation"]
    assert "owner_token" not in retry["operation"]
    next_result, next_status = second_runtime.run_synchronous_operation(
        "reset_model_digests",
        f"adm_{'e' * 32}",
        lambda: {"reset": True},
    )
    assert (next_result, next_status) == ({"reset": True}, 200)


def test_operation_owner_lease_rejects_a_preexisting_hard_link_without_truncating_target(
    tmp_path: Path,
) -> None:
    runtime = OllamaRuntime(tmp_path / "workspace", probe=lambda: None)
    target = tmp_path / "outside.txt"
    target.write_text("do-not-truncate", encoding="utf-8")
    lock_path = runtime.workspace_dir / ollama_runtime._OPERATION_OWNER_LOCK_NAME
    try:
        os.link(target, lock_path)
    except OSError:
        pytest.skip("hard links are unavailable on this platform")

    with pytest.raises(OllamaRuntimeError, match="owner lease path is unsafe"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'1' * 32}",
            lambda: pytest.fail("an unsafe owner lease must prevent execution"),
        )

    assert target.read_text(encoding="utf-8") == "do-not-truncate"


def test_operation_owner_lease_does_not_truncate_a_hard_link_swapped_after_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = OllamaRuntime(tmp_path / "workspace", probe=lambda: None)
    target = tmp_path / "outside.txt"
    target.write_text("do-not-truncate", encoding="utf-8")
    original_prepare = runtime._prepare_operation_lock_path
    swapped = False

    def prepare_and_swap(lock_path: Path, purpose: str) -> None:
        nonlocal swapped
        original_prepare(lock_path, purpose)
        if purpose != "owner" or swapped:
            return
        lock_path.unlink()
        try:
            os.link(target, lock_path)
        except OSError:
            pytest.skip("hard links are unavailable on this platform")
        swapped = True

    monkeypatch.setattr(runtime, "_prepare_operation_lock_path", prepare_and_swap)

    with pytest.raises(OllamaRuntimeError, match="lease path is unsafe"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'2' * 32}",
            lambda: pytest.fail("an unsafe owner lease must prevent execution"),
        )

    assert swapped is True
    assert target.read_text(encoding="utf-8") == "do-not-truncate"


def test_lifecycle_lease_rejects_a_preexisting_hard_link_without_truncating_target(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("do-not-truncate", encoding="utf-8")
    lock_path = workspace / ollama_runtime._LIFECYCLE_LOCK_NAME
    try:
        os.link(target, lock_path)
    except OSError:
        pytest.skip("hard links are unavailable on this platform")

    with pytest.raises(OllamaRuntimeError, match="lifecycle lease path is unsafe"):
        OllamaRuntime(workspace, probe=lambda: None)

    assert target.read_text(encoding="utf-8") == "do-not-truncate"


def test_terminal_receipt_failure_is_reported_as_indeterminate_after_restart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    admission_id = f"adm_{'d' * 32}"
    committed = False
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    write_operation_state = runtime._write_operation_state

    def fail_terminal_receipt(operations: Any) -> None:
        latest = operations[-1] if isinstance(operations, list) else operations
        if latest["state"] != "running":
            raise OllamaRuntimeError("simulated receipt persistence failure")
        write_operation_state(operations)

    def mutate() -> dict[str, bool]:
        nonlocal committed
        committed = True
        return {"reset": True}

    monkeypatch.setattr(runtime, "_write_operation_state", fail_terminal_receipt)

    with pytest.raises(OllamaRuntimeError, match="receipt persistence failure"):
        runtime.run_synchronous_operation("reset_model_digests", admission_id, mutate)

    assert committed is True
    assert runtime.status()["operation"]["state"] == "indeterminate"

    restarted = OllamaRuntime(tmp_path, probe=lambda: None)
    restored = restarted.status()["operation"]
    assert restored["state"] == "indeterminate"
    assert "outcome is unknown" in restored["error"]
    with pytest.raises(OllamaRuntimeError, match="outcome is unknown"):
        restarted.run_synchronous_operation(
            "reset_model_digests",
            admission_id,
            lambda: pytest.fail("an indeterminate admission must never execute twice"),
        )
    with pytest.raises(OllamaRuntimeError, match="outcome is unknown"):
        restarted.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'e' * 32}",
            lambda: pytest.fail("a fresh admission must not bypass an indeterminate receipt"),
        )


def test_stale_runtime_publishes_foreign_unresolved_receipt_before_rejecting_admission(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    stale_runtime = OllamaRuntime(workspace, probe=lambda: None)
    writer = OllamaRuntime(workspace, probe=lambda: None)
    admission_id = f"adm_{'7' * 32}"

    def mutate_then_fail() -> dict[str, bool]:
        writer._mark_operation_mutation_started()
        raise OllamaRuntimeError("verification was lost")

    with pytest.raises(OllamaRuntimeError, match="verification was lost"):
        writer.run_synchronous_operation(
            "reset_model_digests",
            admission_id,
            mutate_then_fail,
        )
    blocker = writer.status()["unresolved_operation"]
    assert blocker is not None
    observed = stale_runtime.status()["unresolved_operation"]
    assert observed is not None
    assert observed["id"] == blocker["id"]

    with pytest.raises(OllamaRuntimeError, match="outcome is unknown"):
        stale_runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'6' * 32}",
            lambda: pytest.fail("a foreign unresolved receipt must block fresh work"),
        )

    published = stale_runtime.status()["unresolved_operation"]
    assert published is not None
    assert published["id"] == blocker["id"]
    assert published["admission_id"] == admission_id


def test_every_runtime_status_refreshes_foreign_unresolved_receipt(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    writer = OllamaRuntime(workspace, probe=lambda: None)
    observer_b = OllamaRuntime(workspace, probe=lambda: None)
    observer_c = OllamaRuntime(workspace, probe=lambda: None)
    admission_id = f"adm_{'3' * 32}"

    def mutate_then_fail() -> dict[str, bool]:
        writer._mark_operation_mutation_started()
        raise OllamaRuntimeError("verification was lost")

    with pytest.raises(OllamaRuntimeError, match="verification was lost"):
        writer.run_synchronous_operation(
            "reset_model_digests",
            admission_id,
            mutate_then_fail,
        )
    blocker = writer.status()["unresolved_operation"]
    assert blocker is not None

    for observer in (observer_b, observer_c):
        published = observer.status()["unresolved_operation"]
        assert published is not None
        assert published["id"] == blocker["id"]
        assert published["admission_id"] == admission_id


def test_invalid_operation_journal_never_fails_open_when_runtime_state_is_also_invalid(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    runtime._runtime_state_error = "managed Ollama runtime version state is invalid"
    runtime.runtime_root.mkdir(parents=True, exist_ok=True)
    runtime._operation_state_path().write_text("{not-json", encoding="utf-8")
    calls = 0

    def mutate() -> dict[str, bool]:
        nonlocal calls
        calls += 1
        return {"reset": True}

    with pytest.raises(OllamaRuntimeError, match="operation state is invalid"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'2' * 32}",
            mutate,
        )

    assert calls == 0


def test_missing_observed_operation_journal_keeps_unknown_truth_sticky(tmp_path: Path) -> None:
    admission_id = f"adm_{'4' * 32}"
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)

    def mutate_then_fail() -> dict[str, bool]:
        runtime._mark_operation_mutation_started()
        raise OllamaRuntimeError("verification was lost")

    with pytest.raises(OllamaRuntimeError, match="verification was lost"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            admission_id,
            mutate_then_fail,
        )
    blocker = runtime.status()["unresolved_operation"]
    runtime._operation_state_path().unlink()

    with pytest.raises(OllamaRuntimeError, match="operation truth is unavailable"):
        with runtime.provider_transition_guard():
            pytest.fail("a missing observed journal must block provider persistence")

    status = runtime.status()
    assert status["unresolved_operation"]["id"] == blocker["id"]
    assert "receipt journal is missing" in status["integrity_error"]
    assert status["repair_allowed"] is False
    assert "runtime-file repair cannot recover" in status["repair_blocked_reason"]
    with pytest.raises(OllamaRuntimeError, match="runtime-file repair is blocked"):
        runtime.repair()
    with pytest.raises(OllamaRuntimeError, match="operation truth is unavailable"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'5' * 32}",
            lambda: pytest.fail("sticky missing-journal truth must block fresh admissions"),
        )
    with pytest.raises(OllamaRuntimeError, match="operation truth is unavailable"):
        OllamaRuntime(tmp_path, probe=lambda: None)


def test_direct_repair_cannot_bypass_an_unresolved_durable_receipt(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"replacement")
    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        probe=lambda: None,
    )
    corrupt_file = runtime.install_dir / "bin" / "ollama.exe"
    corrupt_file.parent.mkdir(parents=True)
    corrupt_file.write_bytes(b"corrupt")

    def leave_unknown_outcome() -> dict[str, bool]:
        runtime._mark_operation_mutation_started()
        raise OllamaRuntimeError("verification was lost")

    with pytest.raises(OllamaRuntimeError, match="verification was lost"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'6' * 32}",
            leave_unknown_outcome,
        )

    status = runtime.status()
    assert status["unresolved_operation"] is not None
    assert status["repair_allowed"] is False
    with pytest.raises(OllamaRuntimeError, match="outcome is unknown"):
        runtime.repair()
    assert corrupt_file.read_bytes() == b"corrupt"


def test_stale_runtime_reloads_required_marker_before_treating_missing_journal_as_pristine(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    stale_runtime = OllamaRuntime(workspace, probe=lambda: None)
    writer = OllamaRuntime(workspace, probe=lambda: None)

    def mutate_then_fail() -> dict[str, bool]:
        writer._mark_operation_mutation_started()
        raise OllamaRuntimeError("verification was lost")

    with pytest.raises(OllamaRuntimeError, match="verification was lost"):
        writer.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'8' * 32}",
            mutate_then_fail,
        )
    writer._operation_state_path().unlink()

    with pytest.raises(OllamaRuntimeError, match="operation truth is unavailable"):
        with stale_runtime.provider_transition_guard():
            pytest.fail("a stale runtime must reload the durable journal marker")

    callback_ran = False

    def callback() -> dict[str, bool]:
        nonlocal callback_ran
        callback_ran = True
        return {"reset": True}

    with pytest.raises(OllamaRuntimeError, match="operation truth is unavailable"):
        stale_runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'9' * 32}",
            callback,
        )
    assert callback_ran is False
    assert "receipt journal is missing" in stale_runtime.status()["integrity_error"]


def test_first_receipt_marks_the_journal_required_before_state_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    durable_replace = ollama_runtime.durable_replace
    callback_ran = False

    def fail_state_commit(source: Path, target: Path) -> None:
        if target == runtime._operation_state_path():
            raise OSError("simulated state commit failure")
        durable_replace(source, target)

    def callback() -> dict[str, bool]:
        nonlocal callback_ran
        callback_ran = True
        return {"reset": True}

    monkeypatch.setattr(ollama_runtime, "durable_replace", fail_state_commit)

    with pytest.raises(OllamaRuntimeError, match="operation state could not be saved"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'a' * 32}",
            callback,
        )

    marker = json.loads(runtime._operation_journal_marker_path().read_text(encoding="utf-8"))
    assert marker == {"journal_created": True, "schema": 1}
    assert callback_ran is False
    with pytest.raises(OllamaRuntimeError, match="operation truth is unavailable"):
        OllamaRuntime(tmp_path, probe=lambda: None)


def test_journal_removal_during_a_running_operation_blocks_provider_and_fresh_admission(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()
    mutation_ran = threading.Event()
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)

    def operation() -> None:
        started.set()
        assert release.wait(timeout=2.0)

    runtime._start_background(
        "start",
        operation,
        admission_id=f"adm_{'6' * 32}",
    )
    assert started.wait(timeout=2.0)
    runtime._operation_state_path().unlink()

    with pytest.raises(OllamaRuntimeError, match="operation truth is unavailable"):
        with runtime.provider_transition_guard():
            pytest.fail("a deleted running receipt must block provider persistence")

    release.set()
    assert runtime.wait_for_operation(timeout=2.0) is True
    assert runtime.status()["operation"]["state"] == "running"
    with pytest.raises(OllamaRuntimeError, match="operation truth is unavailable"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'7' * 32}",
            lambda: mutation_ran.set() or {"reset": True},
        )
    assert mutation_ran.is_set() is False


@pytest.mark.integration
def test_terminal_receipt_failure_is_indeterminate_while_foreign_owner_process_is_alive(tmp_path: Path) -> None:
    """A live foreign owner leaves its unpersisted terminal receipt indeterminate, and unreplayable.

    The readiness handshake uses the same explicit wait as the cross-process lease test.
    Its previous 5.0 second budget had to cover interpreter startup *plus* importing
    ``flinttrade_core.ollama_runtime`` in a child, which a loaded runner exceeds -- it
    failed twice in eight ``-n 4`` runs on the maintainer's host, reporting only a bare
    ``assert ready.exists()`` that said nothing about the child.
    """
    workspace = tmp_path / "workspace"
    ready = tmp_path / "child-ready"
    release = tmp_path / "child-release"
    admission_id = f"adm_{'f' * 32}"
    child_code = """
import sys
import time
from pathlib import Path

from flinttrade_core.ollama_runtime import OllamaRuntime, OllamaRuntimeError

workspace = Path(sys.argv[1])
ready = Path(sys.argv[2])
release = Path(sys.argv[3])
admission_id = sys.argv[4]
runtime = OllamaRuntime(workspace, probe=lambda: None)
write_operation_state = runtime._write_operation_state

def fail_terminal_receipt(operations):
    latest = operations[-1] if isinstance(operations, list) else operations
    if latest["state"] != "running":
        raise OllamaRuntimeError("simulated receipt persistence failure")
    write_operation_state(operations)

runtime._write_operation_state = fail_terminal_receipt
try:
    runtime.run_synchronous_operation("reset_model_digests", admission_id, lambda: {"reset": True})
except OllamaRuntimeError:
    ready.write_text("ready", encoding="utf-8")
while not release.exists():
    time.sleep(0.01)
"""
    child = subprocess.Popen(
        [sys.executable, "-c", child_code, str(workspace), str(ready), str(release), admission_id],
        stdin=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _await_holder_readiness(child, ready)
        assert child.poll() is None

        restored = OllamaRuntime(workspace, probe=lambda: None)
        operation = restored.status()["operation"]
        assert operation["state"] == "indeterminate"
        assert "outcome is unknown" in operation["error"]
        with pytest.raises(OllamaRuntimeError, match="outcome is unknown"):
            restored.run_synchronous_operation(
                "reset_model_digests",
                admission_id,
                lambda: pytest.fail("a foreign indeterminate admission must not execute twice"),
            )
    finally:
        release.touch()
        try:
            child.wait(timeout=_HANDOFF_CEILING_SECONDS)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=_HANDOFF_CEILING_SECONDS)
        if child.stderr is not None:
            child.stderr.close()


def test_prune_receipt_accepts_the_full_bounded_model_inventory(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    result = {
        "deleted": [],
        "pruned": [f"flinttrade/sha256-{index:064x}:locked" for index in range(500)],
    }

    first, first_status = runtime.run_synchronous_operation(
        "prune_models",
        f"adm_{'9' * 32}",
        lambda: result,
    )

    assert (first, first_status) == (result, 200)
    assert runtime.status()["operation"]["state"] == "succeeded"


def test_prune_receipt_rejects_more_than_the_bounded_model_inventory(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    result = {
        "deleted": [],
        "pruned": [f"flinttrade/sha256-{index:064x}:locked" for index in range(501)],
    }

    with pytest.raises(OllamaRuntimeError, match="invalid result"):
        runtime.run_synchronous_operation(
            "prune_models",
            f"adm_{'8' * 32}",
            lambda: result,
        )

    assert runtime.status()["operation"]["state"] == "indeterminate"


def test_malformed_synchronous_result_is_not_recorded_as_success(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)

    with pytest.raises(OllamaRuntimeError, match="invalid result"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'e' * 32}",
            lambda: {"reset": False},
        )

    operation = runtime.status()["operation"]
    assert operation["state"] == "indeterminate"
    assert "invalid result" in operation["error"]


def test_delete_receipt_cannot_publish_prune_output_as_success(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)

    with pytest.raises(OllamaRuntimeError, match="invalid result"):
        runtime.run_synchronous_operation(
            "delete_model",
            f"adm_{'1' * 32}",
            lambda: {
                "deleted": [],
                "pruned": [f"flinttrade/sha256-{'a' * 64}:locked"],
            },
            operation_subject={"model": "qwen3:8b"},
        )

    assert runtime.status()["operation"]["state"] == "indeterminate"


def test_digest_acceptance_receipt_is_bound_to_the_admitted_model_and_digest(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    digest = "a" * 64

    with pytest.raises(OllamaRuntimeError, match="invalid result"):
        runtime.run_synchronous_operation(
            "accept_model_digest",
            f"adm_{'2' * 32}",
            lambda: {
                "accepted": True,
                "source_model": "unrelated:latest",
                "model": f"flinttrade/sha256-{digest}:locked",
                "digest": digest,
            },
            operation_subject={"model": "qwen3:8b", "digest": digest},
        )

    assert runtime.status()["operation"]["state"] == "indeterminate"


def test_admission_id_cannot_replay_against_a_different_operation_target(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    admission_id = f"adm_{'3' * 32}"

    result, status_code = runtime.run_synchronous_operation(
        "delete_model",
        admission_id,
        lambda: {"deleted": ["qwen3:8b"], "pruned": []},
        operation_subject={"model": "qwen3:8b"},
    )

    assert (result, status_code) == ({"deleted": ["qwen3:8b"], "pruned": []}, 200)
    with pytest.raises(OllamaRuntimeError, match="another Ollama operation target"):
        runtime.run_synchronous_operation(
            "delete_model",
            admission_id,
            lambda: pytest.fail("a rebound admission must never execute"),
            operation_subject={"model": "llama3:8b"},
        )


def test_exact_operator_reconciliation_preserves_unknown_receipt_and_unblocks_fresh_admission(
    tmp_path: Path,
) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    admission_id = f"adm_{'e' * 32}"

    with pytest.raises(OllamaRuntimeError, match="invalid result"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            admission_id,
            lambda: {"reset": False},
        )

    blocker = runtime.status()["unresolved_operation"]
    assert blocker["state"] == "indeterminate"
    assert blocker["admission_id"] == admission_id
    assert blocker["reconciled_at"] is None
    with pytest.raises(OllamaRuntimeError, match="do not identify"):
        runtime.reconcile_indeterminate_operation(
            blocker["id"],
            f"adm_{'f' * 32}",
        )

    reconciled = runtime.reconcile_indeterminate_operation(blocker["id"], admission_id)

    assert reconciled["unresolved_operation"] is None
    assert reconciled["operation"]["state"] == "indeterminate"
    assert reconciled["operation"]["error"] == blocker["error"]
    assert reconciled["operation"]["reconciled_at"] >= reconciled["operation"]["finished_at"]
    replay = runtime.reconcile_indeterminate_operation(blocker["id"], admission_id)
    assert replay["operation"]["reconciled_at"] == reconciled["operation"]["reconciled_at"]

    result, status_code = runtime.run_synchronous_operation(
        "reset_model_digests",
        f"adm_{'a' * 32}",
        lambda: {"reset": True},
    )

    assert (result, status_code) == ({"reset": True}, 200)
    with pytest.raises(OllamaRuntimeError, match="invalid result"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            admission_id,
            lambda: pytest.fail("the original admission must remain non-replayable"),
        )
    restarted = OllamaRuntime(tmp_path, probe=lambda: None)
    operations, _legacy = restarted._read_operation_state()
    original = next(operation for operation in operations if operation["id"] == blocker["id"])
    assert original["state"] == "indeterminate"
    assert original["error"] == blocker["error"]
    assert original["reconciled_at"] == reconciled["operation"]["reconciled_at"]
    assert restarted.status()["unresolved_operation"] is None


@pytest.mark.parametrize("reconciled_at", [None, 3.0])
def test_receipt_compaction_never_discards_an_unknown_outcome(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reconciled_at: float | None,
) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    monkeypatch.setattr(ollama_runtime, "_MAX_OPERATION_RECEIPTS", 1)
    unresolved = {
        "id": f"op_{'1' * 32}",
        "admission_id": f"adm_{'1' * 32}",
        "kind": "start",
        "state": "indeterminate",
        "started_at": 1.0,
        "finished_at": 2.0,
        "reconciled_at": reconciled_at,
        "error": "outcome is unknown",
        "result": None,
        "owner_pid": 0,
        "owner_create_time": 0.0,
        "owner_token": "",
    }
    current = {
        **unresolved,
        "id": f"op_{'2' * 32}",
        "admission_id": f"adm_{'2' * 32}",
        "state": "succeeded",
        "finished_at": 3.0,
        "reconciled_at": None,
        "error": None,
    }

    with pytest.raises(OllamaRuntimeError, match="cannot be compacted safely"):
        runtime._fit_operation_receipts(
            [unresolved, current],
            protected_operation_ids={current["id"]},
        )


def test_async_admission_retry_returns_the_original_operation(tmp_path: Path) -> None:
    admission_id = f"adm_{'b' * 32}"
    started = threading.Event()
    release = threading.Event()
    calls = 0
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)

    def operation() -> None:
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(timeout=2.0)

    first = runtime._start_background("start", operation, admission_id=admission_id)
    assert started.wait(timeout=2.0)
    retry = runtime._start_background("start", operation, admission_id=admission_id)
    release.set()
    assert runtime.wait_for_operation(timeout=2.0) is True

    assert calls == 1
    assert retry["operation"]["id"] == first["operation"]["id"]
    assert retry["operation"]["admission_id"] == admission_id
    assert runtime.status()["operation"]["state"] == "succeeded"


def test_managed_model_admission_rechecks_the_accepted_digest(tmp_path: Path) -> None:
    accepted_digest = "a" * 64
    alias = ollama_runtime._locked_model_alias(accepted_digest)
    alias_digest = [accepted_digest]
    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        request_json=lambda *_args: {
            "models": [
                {
                    "name": alias,
                    "model": alias,
                    "digest": alias_digest[0],
                }
            ]
        },
    )
    runtime._process = _FakeProcess()

    assert runtime.model_is_accepted("qwen3:8b") is False

    runtime._write_model_trust_state({alias: accepted_digest}, {"qwen3:8b": alias})
    assert runtime.model_is_accepted("qwen3:8b") is False
    assert runtime.model_is_accepted(alias) is True

    alias_digest[0] = "b" * 64
    assert runtime.model_is_accepted(alias) is False


def test_model_digest_trust_state_is_separate_from_the_ollama_model_store(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path)

    runtime._write_accepted_model_digests({"qwen3:8b": "a" * 64})

    digest_path = runtime._model_digests_path()
    assert digest_path.parent == runtime.trust_dir
    assert runtime.models_dir not in digest_path.parents
    assert runtime._read_accepted_model_digests() == {"qwen3:8b": "a" * 64}


def test_inference_session_discards_admission_when_the_loaded_digest_differs(tmp_path: Path) -> None:
    accepted_digest = "a" * 64
    alias = ollama_runtime._locked_model_alias(accepted_digest)

    def request_json(_method: str, path: str, _payload: dict[str, Any] | None) -> dict[str, Any]:
        digest = "b" * 64 if path == "/api/ps" else "a" * 64
        return {
            "models": [
                {
                    "name": alias,
                    "model": alias,
                    "digest": digest,
                }
            ]
        }

    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        request_json=request_json,
    )
    runtime._process = _FakeProcess()
    runtime._port = 43127
    runtime._write_model_trust_state({alias: accepted_digest}, {"qwen3:8b": alias})

    with pytest.raises(OllamaRuntimeError, match="loaded model digest"):
        with runtime.inference_session(alias) as admission:
            assert admission.base_url == "http://127.0.0.1:43127"
            assert admission.model == alias
            assert admission.digest == accepted_digest


def test_inference_session_rechecks_the_alias_after_a_client_error(tmp_path: Path) -> None:
    accepted_digest = "a" * 64
    alias = ollama_runtime._locked_model_alias(accepted_digest)
    requested_paths: list[str] = []

    def request_json(_method: str, path: str, _payload: dict[str, Any] | None) -> dict[str, Any]:
        requested_paths.append(path)
        return {
            "models": [
                {
                    "name": alias,
                    "model": alias,
                    "digest": accepted_digest,
                    "size": 10,
                    "size_vram": 10,
                }
            ]
        }

    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        request_json=request_json,
    )
    runtime._process = _FakeProcess()
    runtime._port = 43127
    runtime._write_model_trust_state({alias: accepted_digest}, {"qwen3:8b": alias})

    with pytest.raises(RuntimeError, match="client failed"):
        with runtime.inference_session(alias):
            raise RuntimeError("client failed")

    assert requested_paths == ["/api/tags", "/api/tags", "/api/ps"]


def test_stop_waits_for_an_active_inference_admission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    digest = "a" * 64
    alias = ollama_runtime._locked_model_alias(digest)
    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        request_json=lambda *_args: {
            "models": [
                {
                    "name": alias,
                    "model": alias,
                    "digest": digest,
                }
            ]
        },
    )
    process = _FakeProcess()
    runtime._process = process
    runtime._port = 43127
    runtime._write_model_trust_state({alias: digest}, {"qwen3:8b": alias})
    monkeypatch.setattr(
        ollama_runtime,
        "_terminate_process_tree",
        lambda owned_process, **_kwargs: setattr(owned_process, "returncode", 0),
    )
    entered = threading.Event()
    release = threading.Event()
    stopped = threading.Event()

    def hold_admission() -> None:
        with runtime.inference_session(alias):
            entered.set()
            release.wait(timeout=2.0)

    inference_thread = threading.Thread(target=hold_admission)
    inference_thread.start()
    assert entered.wait(timeout=2.0)

    stop_thread = threading.Thread(target=lambda: (runtime.stop(), stopped.set()))
    stop_thread.start()
    assert stopped.wait(timeout=0.05) is False

    release.set()
    inference_thread.join(timeout=2.0)
    stop_thread.join(timeout=2.0)

    assert stopped.is_set() is True
    assert process.poll() is not None


def test_stop_forces_the_exact_owned_child_after_the_inference_grace_deadline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    digest = "a" * 64
    alias = ollama_runtime._locked_model_alias(digest)
    process = _FakeProcess()
    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0" if process.poll() is None else None,
        request_json=lambda *_args: {
            "models": [{"name": alias, "model": alias, "digest": digest}]
        },
    )
    runtime._process = process
    runtime._port = 43127
    runtime._write_model_trust_state({alias: digest}, {"qwen3:8b": alias})
    terminated: list[_FakeProcess] = []

    def terminate(owned_process: _FakeProcess, **_kwargs: Any) -> None:
        terminated.append(owned_process)
        owned_process.returncode = -9

    monkeypatch.setattr(ollama_runtime, "_terminate_process_tree", terminate)
    entered = threading.Event()
    release = threading.Event()

    def hold_admission() -> None:
        try:
            with runtime.inference_session(alias):
                entered.set()
                release.wait(timeout=2.0)
        except OllamaRuntimeError:
            pass

    inference_thread = threading.Thread(target=hold_admission)
    inference_thread.start()
    assert entered.wait(timeout=2.0)

    status = runtime.stop(timeout_seconds=0.25, inference_grace_seconds=0.01)

    assert terminated == [process]
    assert status["managed_process"] is False
    assert status["ready"] is False
    assert status["teardown"] == {
        "state": "stopped",
        "mode": "forced",
        "active_inferences": 1,
    }
    release.set()
    inference_thread.join(timeout=2.0)
    assert inference_thread.is_alive() is False


def test_stop_publishes_stopped_state_before_status_can_observe_process_removal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = _FakeProcess()
    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0" if process.poll() is None else None,
        listener_owner=lambda owned_process: owned_process is process,
    )
    runtime._process = process
    runtime._port = 43127
    runtime._phase = "ready"
    observed_during_teardown: list[dict[str, Any]] = []

    monkeypatch.setattr(
        ollama_runtime,
        "_terminate_process_tree",
        lambda owned_process, **_kwargs: setattr(owned_process, "returncode", 0),
    )

    def finish_log_pump(*, deadline: float) -> bool:
        assert deadline > time.monotonic()
        observed_during_teardown.append(runtime.status())
        return True

    monkeypatch.setattr(runtime, "_finish_log_pump", finish_log_pump)

    result = runtime.stop(timeout_seconds=1.0)

    assert observed_during_teardown[0]["state"] != "failed"
    assert observed_during_teardown[0]["managed_process"] is False
    assert result["state"] != "failed"
    assert runtime._phase == "stopped"


def test_stop_deadline_is_not_blocked_by_the_pre_inference_digest_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    digest = "a" * 64
    alias = ollama_runtime._locked_model_alias(digest)
    process = _FakeProcess()
    digest_check_entered = threading.Event()
    release_digest_check = threading.Event()

    def request_json(_method: str, path: str, _payload: dict[str, Any] | None) -> dict[str, Any]:
        if path == "/api/tags":
            digest_check_entered.set()
            release_digest_check.wait(timeout=2.0)
        return {"models": [{"name": alias, "model": alias, "digest": digest}]}

    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0" if process.poll() is None else None,
        request_json=request_json,
    )
    runtime._process = process
    runtime._port = 43127
    runtime._write_model_trust_state({alias: digest}, {"qwen3:8b": alias})
    monkeypatch.setattr(
        ollama_runtime,
        "_terminate_process_tree",
        lambda owned_process, **_kwargs: setattr(owned_process, "returncode", -9),
    )
    inference_errors: list[Exception] = []

    def run_inference() -> None:
        try:
            with runtime.inference_session(alias):
                pass
        except Exception as exc:  # noqa: BLE001 - asserted below
            inference_errors.append(exc)

    inference_thread = threading.Thread(target=run_inference)
    inference_thread.start()
    assert digest_check_entered.wait(timeout=2.0)

    status = runtime.stop(timeout_seconds=0.25, inference_grace_seconds=0.01)

    assert status["teardown"]["mode"] == "forced"
    assert process.poll() is not None
    release_digest_check.set()
    inference_thread.join(timeout=2.0)
    assert inference_thread.is_alive() is False
    assert inference_errors and isinstance(inference_errors[0], OllamaRuntimeError)


def test_stop_deadline_bounds_a_state_lock_acquired_during_late_teardown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = _FakeProcess()
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    runtime._process = process
    lock_held = threading.Event()
    release_lock = threading.Event()
    holder: threading.Thread | None = None

    monkeypatch.setattr(
        ollama_runtime,
        "_terminate_process_tree",
        lambda owned_process, **_kwargs: setattr(owned_process, "returncode", 0),
    )

    def finish_log_pump(*, deadline: float) -> bool:
        del deadline
        nonlocal holder

        def hold_state_lock() -> None:
            with runtime._state_lock:
                lock_held.set()
                assert release_lock.wait(timeout=2.0)

        holder = threading.Thread(target=hold_state_lock)
        holder.start()
        assert lock_held.wait(timeout=2.0)
        return True

    monkeypatch.setattr(runtime, "_finish_log_pump", finish_log_pump)
    started = time.monotonic()
    try:
        with pytest.raises(OllamaRuntimeError, match="process teardown timed out"):
            runtime.stop(timeout_seconds=0.05)
    finally:
        release_lock.set()
        if holder is not None:
            holder.join(timeout=2.0)

    assert time.monotonic() - started < 0.5
    assert holder is not None and holder.is_alive() is False


def test_stop_deadline_bounds_the_final_status_state_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = _FakeProcess()
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    runtime._process = process
    lock_held = threading.Event()
    release_lock = threading.Event()
    holder: threading.Thread | None = None

    monkeypatch.setattr(
        ollama_runtime,
        "_terminate_process_tree",
        lambda owned_process, **_kwargs: setattr(owned_process, "returncode", 0),
    )

    def installation_status(**_kwargs: Any) -> tuple[bool, str | None]:
        nonlocal holder

        def hold_state_lock() -> None:
            with runtime._state_lock:
                lock_held.set()
                assert release_lock.wait(timeout=2.0)

        holder = threading.Thread(target=hold_state_lock)
        holder.start()
        assert lock_held.wait(timeout=2.0)
        return False, None

    monkeypatch.setattr(runtime, "_installation_status", installation_status)
    started = time.monotonic()
    try:
        with pytest.raises(OllamaRuntimeError, match="status snapshot timed out"):
            runtime.stop(timeout_seconds=0.05)
    finally:
        release_lock.set()
        if holder is not None:
            holder.join(timeout=2.0)

    assert time.monotonic() - started < 0.5
    assert holder is not None and holder.is_alive() is False


def test_stop_deadline_includes_lifecycle_condition_admission(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    lock_held = threading.Event()
    release_lock = threading.Event()

    def hold_lifecycle_lock() -> None:
        with runtime._lifecycle_condition:
            lock_held.set()
            assert release_lock.wait(timeout=2.0)

    holder = threading.Thread(target=hold_lifecycle_lock)
    holder.start()
    assert lock_held.wait(timeout=2.0)
    started = time.monotonic()
    try:
        with pytest.raises(OllamaRuntimeError, match="stop transition timed out"):
            runtime.stop(timeout_seconds=0.05)
    finally:
        release_lock.set()
        holder.join(timeout=2.0)

    assert time.monotonic() - started < 0.5
    assert holder.is_alive() is False


def test_exclusive_lifecycle_deadline_includes_condition_admission(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    lock_held = threading.Event()
    release_lock = threading.Event()

    def hold_lifecycle_lock() -> None:
        with runtime._lifecycle_condition:
            lock_held.set()
            assert release_lock.wait(timeout=2.0)

    holder = threading.Thread(target=hold_lifecycle_lock)
    holder.start()
    assert lock_held.wait(timeout=2.0)
    started = time.monotonic()
    try:
        with pytest.raises(OllamaRuntimeError, match="lifecycle transition timed out"):
            with runtime._exclusive_lifecycle(deadline=time.monotonic() + 0.05):
                pytest.fail("lifecycle transition entered while its condition lock was held")
    finally:
        release_lock.set()
        holder.join(timeout=2.0)

    assert time.monotonic() - started < 0.5
    assert holder.is_alive() is False


def test_exclusive_lifecycle_deadline_includes_model_trust_lock_admission(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    lock_held = threading.Event()
    release_lock = threading.Event()

    def hold_model_trust_lock() -> None:
        with runtime._model_trust_lock:
            lock_held.set()
            assert release_lock.wait(timeout=2.0)

    holder = threading.Thread(target=hold_model_trust_lock)
    holder.start()
    assert lock_held.wait(timeout=2.0)
    started = time.monotonic()
    try:
        with pytest.raises(OllamaRuntimeError, match="lifecycle transition timed out"):
            with runtime._exclusive_lifecycle(deadline=time.monotonic() + 0.05):
                pytest.fail("lifecycle transition entered while its model trust lock was held")
    finally:
        release_lock.set()
        holder.join(timeout=2.0)

    assert time.monotonic() - started < 0.5
    assert holder.is_alive() is False


@pytest.mark.unit
def test_exclusive_lifecycle_cleanup_condition_admission_is_deadline_bounded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Cleanup that cannot retake the lifecycle condition fails on the deadline, not on the holder.

    Three behaviours are pinned: an expired deadline turns the cleanup re-acquisition
    into a non-blocking attempt rather than a wait on whoever holds the condition; that
    attempt reports ``lifecycle transition timed out``; and the transition flag is still
    cleared afterwards by the recovery thread, leaving the runtime reusable.

    Previously the deadline was ``time.monotonic() + 0.05`` and "did not block" was
    inferred from ``time.monotonic() - started < 0.5``. Both are host-speed wagers: a
    loaded runner can burn the 50 ms inside the workspace lease before the body ever
    runs (leaving ``holder`` unset), and 0.5 s of wall clock is not a property of the
    code. The deadline is now expired deliberately, and the bound is asserted directly
    from the timeout the production code passes to ``acquire``.
    """
    clock = _DrivenClock()
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    clock.install(monkeypatch)
    requested_acquisitions = _record_bounded_acquisitions(monkeypatch, runtime._lifecycle_condition)

    transition_cleared = threading.Event()
    recover_transition = runtime._clear_lifecycle_transition_when_available

    def recover_and_signal() -> None:
        recover_transition()
        transition_cleared.set()

    monkeypatch.setattr(runtime, "_clear_lifecycle_transition_when_available", recover_and_signal)

    lock_held = threading.Event()
    release_lock = threading.Event()
    holder: threading.Thread | None = None
    try:
        with pytest.raises(OllamaRuntimeError, match="lifecycle transition timed out"):
            with runtime._exclusive_lifecycle(deadline=clock.monotonic() + 0.05):

                def hold_lifecycle_lock() -> None:
                    with runtime._lifecycle_condition:
                        lock_held.set()
                        assert release_lock.wait(timeout=_HANDOFF_CEILING_SECONDS)

                holder = threading.Thread(target=hold_lifecycle_lock)
                holder.start()
                assert lock_held.wait(timeout=_HANDOFF_CEILING_SECONDS)
                # The condition is now demonstrably held by another thread; expire the
                # deadline so cleanup must choose between blocking and reporting.
                clock.advance(1.0)
    finally:
        release_lock.set()
        if holder is not None:
            holder.join(timeout=_HANDOFF_CEILING_SECONDS)

    assert holder is not None and holder.is_alive() is False
    # Entry asked for the whole budget; cleanup, past the deadline, asked for none --
    # a single non-blocking attempt, which is why it could not wait on the holder.
    assert requested_acquisitions[0] == pytest.approx(0.05)
    assert requested_acquisitions[-1] == 0.0

    assert transition_cleared.wait(timeout=_HANDOFF_CEILING_SECONDS)
    assert runtime._lifecycle_transition is False
    with runtime._exclusive_lifecycle(deadline=clock.monotonic() + 1.0):
        assert runtime._lifecycle_transition is True
    assert runtime._lifecycle_transition is False


def test_synchronous_commit_with_lifecycle_cleanup_timeout_is_indeterminate_on_replay(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    admission_id = f"adm_{'a' * 32}"
    lock_held = threading.Event()
    release_lock = threading.Event()
    committed = threading.Event()
    holder: threading.Thread | None = None

    def mutate() -> dict[str, bool]:
        nonlocal holder
        with runtime._exclusive_lifecycle(deadline=time.monotonic() + 0.05):
            committed.set()

            def hold_lifecycle_lock() -> None:
                with runtime._lifecycle_condition:
                    lock_held.set()
                    assert release_lock.wait(timeout=2.0)

            holder = threading.Thread(target=hold_lifecycle_lock)
            holder.start()
            assert lock_held.wait(timeout=2.0)
        return {"reset": True}

    try:
        with pytest.raises(OllamaRuntimeError, match="lifecycle transition timed out"):
            runtime.run_synchronous_operation("reset_model_digests", admission_id, mutate)
    finally:
        release_lock.set()
        if holder is not None:
            holder.join(timeout=2.0)

    assert committed.is_set()
    with runtime._exclusive_lifecycle(deadline=time.monotonic() + 1.0):
        pass
    operation = runtime.status()["operation"]
    assert operation["state"] == "indeterminate"
    assert operation["error"] == ollama_runtime._INDETERMINATE_OPERATION_ERROR

    restarted = OllamaRuntime(tmp_path, probe=lambda: None)
    with pytest.raises(OllamaRuntimeError, match="outcome is unknown"):
        restarted.run_synchronous_operation(
            "reset_model_digests",
            admission_id,
            lambda: pytest.fail("an indeterminate committed mutation must not run twice"),
        )


def test_stop_deadline_bounds_the_lifecycle_lease_cancellation_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    original_prepare = runtime._prepare_operation_lock_path
    lock_held = threading.Event()
    release_lock = threading.Event()
    holder: threading.Thread | None = None

    def prepare_lock_path(lock_path: Path, purpose: str) -> None:
        nonlocal holder
        original_prepare(lock_path, purpose)
        if purpose != "lifecycle":
            return

        def hold_state_lock() -> None:
            with runtime._state_lock:
                lock_held.set()
                assert release_lock.wait(timeout=2.0)

        holder = threading.Thread(target=hold_state_lock)
        holder.start()
        assert lock_held.wait(timeout=2.0)

    monkeypatch.setattr(runtime, "_prepare_operation_lock_path", prepare_lock_path)
    started = time.monotonic()
    try:
        with pytest.raises(OllamaRuntimeError, match="lifecycle transition timed out"):
            runtime.stop(timeout_seconds=0.05)
    finally:
        release_lock.set()
        if holder is not None:
            holder.join(timeout=2.0)

    assert time.monotonic() - started < 0.5
    assert holder is not None and holder.is_alive() is False


def test_stop_holds_lifecycle_admission_through_its_final_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = _FakeProcess()
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    runtime._process = process
    snapshot_entered = threading.Event()
    release_snapshot = threading.Event()
    contender_entered = threading.Event()
    stop_result: list[dict[str, Any]] = []

    monkeypatch.setattr(
        ollama_runtime,
        "_terminate_process_tree",
        lambda owned_process, **_kwargs: setattr(owned_process, "returncode", 0),
    )

    def installation_status(**_kwargs: Any) -> tuple[bool, str | None]:
        snapshot_entered.set()
        assert release_snapshot.wait(timeout=2.0)
        return False, None

    monkeypatch.setattr(runtime, "_installation_status", installation_status)

    def stop_runtime() -> None:
        stop_result.append(runtime.stop(timeout_seconds=1.0))

    def contend_for_lifecycle() -> None:
        with runtime._exclusive_lifecycle():
            contender_entered.set()

    stopper = threading.Thread(target=stop_runtime)
    stopper.start()
    assert snapshot_entered.wait(timeout=2.0)
    contender = threading.Thread(target=contend_for_lifecycle)
    contender.start()
    assert contender_entered.wait(timeout=0.05) is False

    release_snapshot.set()
    stopper.join(timeout=2.0)
    contender.join(timeout=2.0)

    assert stopper.is_alive() is False
    assert contender.is_alive() is False
    assert contender_entered.is_set()
    assert stop_result[0]["managed_process"] is False


def test_managed_global_readiness_refuses_model_digest_drift(tmp_path: Path) -> None:
    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        request_json=lambda *_args: {
            "models": [{"name": "qwen3:8b", "model": "qwen3:8b", "digest": "b" * 64}]
        },
    )
    runtime._process = _FakeProcess()
    runtime._write_accepted_model_digests({"qwen3:8b": "a" * 64})
    ollama_runtime._publish_managed_ollama_owner(runtime)
    try:
        assert ollama_runtime.managed_ollama_is_ready() is True
        assert ollama_runtime.managed_ollama_is_ready("qwen3:8b") is False
        assert ollama_runtime.managed_ollama_base_url() == runtime.base_url
    finally:
        ollama_runtime._clear_managed_ollama_owner(runtime)


def test_readiness_rechecks_listener_ownership_after_the_version_probe(tmp_path: Path) -> None:
    ownership = iter([True, False])
    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        listener_owner=lambda _process: next(ownership),
    )
    runtime._process = _FakeProcess()
    runtime._port = 43127

    assert runtime._managed_server_version() is None


def test_legacy_mutable_tag_trust_is_not_presented_as_inference_acceptance(tmp_path: Path) -> None:
    digest = "a" * 64
    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0",
        listener_owner=lambda _process: True,
        request_json=lambda *_args: {
            "models": [{"name": "qwen3:8b", "model": "qwen3:8b", "digest": digest}]
        },
    )
    runtime._process = _FakeProcess()
    runtime._port = 43127
    runtime._write_accepted_model_digests({"qwen3:8b": digest})

    models = runtime.list_models()

    assert "accepted_digest" not in models[0]
    assert "inference_model" not in models[0]
    assert runtime.model_is_accepted("qwen3:8b") is False


def test_inference_processor_is_cleared_when_ollama_cannot_verify_a_loaded_model(tmp_path: Path) -> None:
    runtime = OllamaRuntime(
        tmp_path,
        request_json=lambda *_args: {"models": []},
    )
    runtime._inference_processor = "100% GPU"

    assert runtime._loaded_model_matches("qwen3:8b", "a" * 64) is False
    assert runtime.status()["inference_processor"] is None


def test_version_probe_has_a_hard_wall_clock_and_byte_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]

    class TrickleSocket:
        recv_calls = 0

        def __enter__(self) -> TrickleSocket:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def settimeout(self, _timeout: float) -> None:
            return None

        def sendall(self, _request: bytes) -> None:
            return None

        def recv(self, _size: int) -> bytes:
            self.recv_calls += 1
            clock[0] += 0.3
            if self.recv_calls == 1:
                return b"HTTP/1.1 200 OK\r\nContent-Length: 20\r\n\r\n{"
            return b'"'

    trickle = TrickleSocket()
    monkeypatch.setattr(ollama_runtime.socket, "create_connection", lambda *_args, **_kwargs: trickle)
    monkeypatch.setattr(ollama_runtime.time, "monotonic", lambda: clock[0])

    assert ollama_runtime._probe_ollama_server("http://127.0.0.1:43127") is None
    assert trickle.recv_calls <= 2
    assert clock[0] <= ollama_runtime._PROBE_DEADLINE_SECONDS + 0.3


def test_version_probe_clips_socket_timeout_to_the_remaining_shutdown_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [10.0]
    observed_timeouts: list[float] = []

    def create_connection(_address: tuple[str, int], *, timeout: float) -> None:
        observed_timeouts.append(timeout)
        raise TimeoutError("injected probe timeout")

    monkeypatch.setattr(ollama_runtime.socket, "create_connection", create_connection)
    monkeypatch.setattr(ollama_runtime.time, "monotonic", lambda: clock[0])

    assert (
        ollama_runtime._probe_ollama_server(
            "http://127.0.0.1:43127",
            deadline=10.125,
        )
        is None
    )
    assert observed_timeouts == pytest.approx([0.125])


def test_live_child_from_a_stale_owner_record_is_never_signalled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: None)
    stale = _FakeProcess()
    terminated: list[Any] = []
    runtime._write_process_owner_record(
        {
            "schema": 1,
            "backend_pid": 99991,
            "backend_create_time": 1.0,
            "child_pid": stale.pid,
            "child_create_time": 2.0,
            "port": 43127,
            "executable_sha256": "a" * 64,
        }
    )
    monkeypatch.setattr(runtime, "_process_identity_is_alive", lambda pid, created: pid == stale.pid)
    def terminate_stale(process: Any, **_kwargs: Any) -> None:
        terminated.append(process)
        process.returncode = 0

    monkeypatch.setattr(
        ollama_runtime,
        "_terminate_process_tree",
        terminate_stale,
    )

    with pytest.raises(OllamaRuntimeError, match="survived its owning backend"):
        runtime._recover_stale_owned_process()

    assert terminated == []
    assert runtime._process_owner_path().exists()


def test_loopback_http_transport_ignores_an_ambient_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    local_seen = threading.Event()
    proxy_seen = threading.Event()

    class LocalHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: Any) -> None:
            return None

        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler API
            local_seen.set()
            payload = b'{"transport":"loopback"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    class ProxyHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: Any) -> None:
            return None

        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler API
            proxy_seen.set()
            payload = b'{"transport":"proxy"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    local_server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), LocalHandler)
    proxy_server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
    local_thread = threading.Thread(target=local_server.serve_forever, daemon=True)
    proxy_thread = threading.Thread(target=proxy_server.serve_forever, daemon=True)
    local_thread.start()
    proxy_thread.start()
    monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{proxy_server.server_port}")
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy_server.server_port}")
    monkeypatch.setenv("no_proxy", "")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setattr(ollama_runtime.urllib.request, "_opener", None)
    monkeypatch.setattr(ollama_runtime.urllib.request, "proxy_bypass", lambda _host: False)
    try:
        payload = ollama_runtime._request_ollama_json(
            "GET",
            "/api/tags",
            None,
            base_url=f"http://127.0.0.1:{local_server.server_port}",
        )
    finally:
        local_server.shutdown()
        proxy_server.shutdown()
        local_server.server_close()
        proxy_server.server_close()
        local_thread.join(timeout=1.0)
        proxy_thread.join(timeout=1.0)

    assert payload == {"transport": "loopback"}
    assert local_seen.is_set()
    assert proxy_seen.is_set() is False


def test_bodyless_http_copy_success_is_verified_by_follow_up_tags(tmp_path: Path) -> None:
    digest = "a" * 64
    locked_alias = ollama_runtime._locked_model_alias(digest)
    copied = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: Any) -> None:
            return None

        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler API
            assert self.path == "/api/tags"
            models = [{"name": "qwen3:8b", "model": "qwen3:8b", "digest": digest}]
            if copied.is_set():
                models.append({"name": locked_alias, "model": locked_alias, "digest": digest})
            payload = json.dumps({"models": models}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler API
            assert self.path == "/api/copy"
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert payload == {"source": "qwen3:8b", "destination": locked_alias}
            copied.set()
            self.send_response(204)
            self.end_headers()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        runtime = OllamaRuntime(tmp_path, probe=lambda: "0.32.0")
        runtime._process = _FakeProcess()
        runtime._port = int(server.server_port)

        result = runtime.accept_model_digest("qwen3:8b", digest)

        assert copied.is_set()
        assert result["model"] == locked_alias
        assert result["digest"] == digest
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=1.0)


def test_loopback_api_socket_read_is_interrupted_by_cancellation() -> None:
    response_started = threading.Event()
    release_response = threading.Event()
    cancelled = threading.Event()
    failures: list[BaseException] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: Any) -> None:
            return None

        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler API
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "1")
            self.end_headers()
            self.wfile.flush()
            response_started.set()
            release_response.wait(timeout=2.0)
            try:
                self.wfile.write(b"{")
            except OSError:
                pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    def request() -> None:
        try:
            ollama_runtime._request_ollama_json(
                "GET",
                "/api/tags",
                None,
                base_url=f"http://127.0.0.1:{server.server_port}",
                cancel_event=cancelled,
            )
        except BaseException as exc:  # noqa: BLE001 - collected from the worker for assertion
            failures.append(exc)

    worker = threading.Thread(target=request, daemon=True)
    worker.start()
    try:
        assert response_started.wait(timeout=1.0)
        cancelled.set()
        worker.join(timeout=1.0)
    finally:
        release_response.set()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=1.0)
        worker.join(timeout=1.0)

    assert worker.is_alive() is False
    assert len(failures) == 1
    assert isinstance(failures[0], ollama_runtime._OllamaOperationCancelled)


def test_download_read_is_interrupted_when_runtime_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    read_started = threading.Event()
    closed = threading.Event()
    cancelled = threading.Event()
    failures: list[BaseException] = []

    class BlockingResponse:
        headers = {"Content-Length": "1"}

        def __enter__(self) -> BlockingResponse:
            return self

        def __exit__(self, *_args: Any) -> None:
            self.close()

        def read1(self, _size: int) -> bytes:
            read_started.set()
            closed.wait(timeout=2.0)
            return b""

        def close(self) -> None:
            closed.set()

    monkeypatch.setattr(
        ollama_runtime.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: BlockingResponse(),
    )
    asset = OllamaAsset(
        name="runtime.zip",
        sha256="0" * 64,
        url="https://downloads.example.invalid/runtime.zip",
        max_extracted_bytes=1,
        size_bytes=1,
    )

    def download() -> None:
        try:
            _download_asset(
                asset,
                tmp_path / "runtime.zip",
                lambda *_args: None,
                cancel_event=cancelled,
            )
        except BaseException as exc:  # noqa: BLE001 - collected from the worker for assertion
            failures.append(exc)

    worker = threading.Thread(target=download, daemon=True)
    worker.start()
    assert read_started.wait(timeout=1.0)
    cancelled.set()
    worker.join(timeout=1.0)

    assert worker.is_alive() is False
    assert closed.is_set()
    assert len(failures) == 1
    assert isinstance(failures[0], ollama_runtime._OllamaOperationCancelled)


def test_model_pull_read_is_interrupted_when_runtime_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_started = threading.Event()
    closed = threading.Event()
    cancelled = threading.Event()
    failures: list[BaseException] = []

    class BlockingResponse:
        def __enter__(self) -> BlockingResponse:
            return self

        def __exit__(self, *_args: Any) -> None:
            self.close()

        def __iter__(self) -> BlockingResponse:
            return self

        def __next__(self) -> bytes:
            read_started.set()
            closed.wait(timeout=2.0)
            raise StopIteration

        def close(self) -> None:
            closed.set()

    monkeypatch.setattr(
        ollama_runtime,
        "_open_loopback_request",
        lambda *_args, **_kwargs: BlockingResponse(),
    )

    def pull() -> None:
        try:
            ollama_runtime._pull_ollama_model(
                "qwen3:8b",
                lambda *_args: None,
                base_url="http://127.0.0.1:43127",
                cancel_event=cancelled,
            )
        except BaseException as exc:  # noqa: BLE001 - collected from the worker for assertion
            failures.append(exc)

    worker = threading.Thread(target=pull, daemon=True)
    worker.start()
    assert read_started.wait(timeout=1.0)
    cancelled.set()
    worker.join(timeout=1.0)

    assert worker.is_alive() is False
    assert closed.is_set()
    assert len(failures) == 1
    assert isinstance(failures[0], ollama_runtime._OllamaOperationCancelled)


def test_archive_extraction_checks_cancellation_between_chunks(tmp_path: Path) -> None:
    archive = tmp_path / "runtime.zip"
    payload = b"x" * (2 * 1024 * 1024)
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", payload)
    cancelled = threading.Event()

    def ensure_capacity(_next_bytes: int) -> None:
        cancelled.set()

    def check_cancelled() -> None:
        if cancelled.is_set():
            raise ollama_runtime._OllamaOperationCancelled("managed Ollama operation was cancelled")

    destination = tmp_path / "runtime"
    with pytest.raises(ollama_runtime._OllamaOperationCancelled):
        _extract_archive(
            archive,
            destination,
            ensure_capacity=ensure_capacity,
            check_cancelled=check_cancelled,
        )

    assert (destination / "bin" / "ollama.exe").stat().st_size < len(payload)


def test_managed_directory_rejects_a_reparse_ancestor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = OllamaRuntime(tmp_path / "workspace", probe=lambda: None)
    inspections = 0

    def reparse_on_first_descendant(_path_stat: os.stat_result) -> bool:
        nonlocal inspections
        inspections += 1
        return inspections == 2

    monkeypatch.setattr(runtime, "_path_is_reparse", reparse_on_first_descendant)

    with pytest.raises(OllamaRuntimeError, match="path is unsafe"):
        runtime._ensure_managed_directory(runtime.models_dir, create=True)


def test_log_normalisation_scavenges_crash_residue_and_bounds_retained_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(ollama_runtime, "_MAX_LOG_FILE_BYTES", 8)
    monkeypatch.setattr(ollama_runtime, "_LOG_BACKUP_COUNT", 2)
    monkeypatch.setattr(ollama_runtime, "_MAX_LOG_STORAGE_BYTES", 24)
    runtime = OllamaRuntime(tmp_path / "workspace", probe=lambda: None)
    runtime.log_path.parent.mkdir(parents=True)
    retained = (
        runtime.log_path,
        runtime.log_path.with_name("ollama.log.1"),
        runtime.log_path.with_name("ollama.log.2"),
    )
    for index, path in enumerate(retained, start=1):
        path.write_bytes(bytes([index]) * (8 + index))
    out_of_range = runtime.log_path.with_name("ollama.log.9")
    temporary = runtime.log_path.with_name(".ollama.log.123.456.tmp")
    rotated_temporary = runtime.log_path.with_name(".ollama.log.1.123.456.tmp")
    out_of_range.write_bytes(b"out-of-range")
    temporary.write_bytes(b"temporary")
    rotated_temporary.write_bytes(b"rotated-temporary")

    runtime._normalise_existing_logs()

    assert all(path.stat().st_size == 8 for path in retained)
    assert not out_of_range.exists()
    assert not temporary.exists()
    assert not rotated_temporary.exists()
    assert runtime._log_storage_bytes() <= 24


@pytest.mark.parametrize("operation", ["stop", "repair"])
def test_stop_and_repair_refuse_to_signal_an_inherited_child(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    operation: str,
) -> None:
    runtime = OllamaRuntime(tmp_path / "workspace", probe=lambda: None)
    stale = _FakeProcess()
    terminated: list[Any] = []
    runtime._write_process_owner_record(
        {
            "schema": 1,
            "backend_pid": 99991,
            "backend_create_time": 1.0,
            "child_pid": stale.pid,
            "child_create_time": 2.0,
            "port": 43127,
            "executable_sha256": "a" * 64,
        }
    )
    monkeypatch.setattr(runtime, "_process_identity_is_alive", lambda pid, _created: pid == stale.pid)
    def terminate_stale(process: Any, **_kwargs: Any) -> None:
        terminated.append(process)
        process.returncode = 0

    monkeypatch.setattr(ollama_runtime, "_terminate_process_tree", terminate_stale)

    if operation == "stop":
        with pytest.raises(OllamaRuntimeError, match="survived its owning backend"):
            runtime.stop(timeout_seconds=1.0)
    else:
        with pytest.raises(OllamaRuntimeError, match="survived its owning backend"):
            runtime.repair()

    assert terminated == []
    assert runtime._process_owner_path().exists()


def test_inconclusive_prepublication_recovery_retains_the_owner_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"binary")
    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        probe=lambda: None,
    )
    runtime.install()
    executable = runtime._verified_executable(rehash=True)
    runtime._write_process_owner_record(
        {
            "schema": 1,
            "backend_pid": 99991,
            "backend_create_time": 1.0,
            "child_pid": 0,
            "child_create_time": 0.0,
            "port": 0,
            "bind_port": 0,
            "executable_sha256": ollama_runtime._sha256_file(executable),
        }
    )

    monkeypatch.setattr(runtime, "_process_identity_is_alive", lambda *_args: False)

    with pytest.raises(OllamaRuntimeError, match="startup ownership is incomplete"):
        runtime._recover_stale_owned_process()

    assert runtime._process_owner_path().exists()


@pytest.mark.parametrize(
    "inspection_error",
    [
        pytest.param(ollama_runtime.psutil.AccessDenied(99991), id="access-denied"),
        pytest.param(ollama_runtime.psutil.Error(), id="psutil-error"),
    ],
)
def test_inconclusive_process_identity_retains_the_owner_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    inspection_error: BaseException,
) -> None:
    runtime = OllamaRuntime(tmp_path / "workspace", probe=lambda: None)
    runtime._write_process_owner_record(
        {
            "schema": 1,
            "backend_pid": 99991,
            "backend_create_time": 1.0,
            "child_pid": 99992,
            "child_create_time": 2.0,
            "port": 0,
            "executable_sha256": "a" * 64,
        }
    )

    def inaccessible_process(_pid: int) -> Any:
        raise inspection_error

    monkeypatch.setattr(ollama_runtime.psutil, "Process", inaccessible_process)

    with pytest.raises(OllamaRuntimeError, match="identity could not be verified"):
        runtime._recover_stale_owned_process(deadline=time.monotonic() + 1.0)

    assert runtime._process_owner_path().exists()


def test_stop_retries_owner_record_cleanup_before_forgetting_the_child(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = OllamaRuntime(tmp_path / "workspace", probe=lambda: None)
    process = _FakeProcess()
    runtime._process = process
    runtime._port = 43127
    runtime._write_process_owner_record(
        {
            "schema": 1,
            "backend_pid": os.getpid(),
            "backend_create_time": 1.0,
            "child_pid": process.pid,
            "child_create_time": 2.0,
            "port": 43127,
            "executable_sha256": "a" * 64,
        }
    )
    termination_calls: list[Any] = []

    def terminate(owned_process: Any, **_kwargs: Any) -> None:
        termination_calls.append(owned_process)
        owned_process.returncode = 0

    monkeypatch.setattr(ollama_runtime, "_terminate_process_tree", terminate)
    remove_owner_record = runtime._remove_process_owner_record
    removal_attempts = 0

    def flaky_remove() -> None:
        nonlocal removal_attempts
        removal_attempts += 1
        if removal_attempts == 1:
            raise OllamaRuntimeError("injected owner record unlink failure")
        remove_owner_record()

    monkeypatch.setattr(runtime, "_remove_process_owner_record", flaky_remove)

    with pytest.raises(OllamaRuntimeError, match="unlink failure"):
        runtime.stop(timeout_seconds=1.0)

    assert runtime._process is process
    assert runtime._port == 43127
    assert runtime._error == "managed Ollama ownership cleanup is incomplete"
    runtime.stop(timeout_seconds=1.0)

    assert removal_attempts == 2
    assert termination_calls == [process]
    assert runtime._process is None
    assert runtime._port == 0
    assert runtime._error == ""
    assert not runtime._process_owner_path().exists()


def test_legacy_install_is_discovered_as_active_until_update(tmp_path: Path) -> None:
    old_archive = tmp_path / "ollama-v0.31.2.zip"
    new_archive = tmp_path / "ollama-v0.32.0.zip"
    for archive, payload in ((old_archive, b"old"), (new_archive, b"new")):
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("bin/ollama.exe", payload)
    workspace = tmp_path / "workspace"
    archives = {"v0.31.2": old_archive, "v0.32.0": new_archive}
    old_runtime = _versioned_runtime(workspace, archives, target_version="v0.31.2")
    old_runtime.install()
    old_runtime._runtime_state_path().unlink()

    runtime = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    status = runtime.status()

    assert status["installed"] is True
    assert status["active_version"] == "v0.31.2"
    assert status["target_version"] == "v0.32.0"
    assert status["previous_version"] is None
    assert status["update_available"] is True
    assert status["rollback_available"] is False


def test_update_stages_target_then_retains_one_verified_rollback(tmp_path: Path) -> None:
    old_archive = tmp_path / "ollama-v0.31.2.zip"
    new_archive = tmp_path / "ollama-v0.32.0.zip"
    for archive, payload in ((old_archive, b"old"), (new_archive, b"new")):
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("bin/ollama.exe", payload)
    workspace = tmp_path / "workspace"
    archives = {"v0.31.2": old_archive, "v0.32.0": new_archive}
    _versioned_runtime(workspace, archives, target_version="v0.31.2").install()
    runtime = _versioned_runtime(workspace, archives, target_version="v0.32.0")

    result = runtime.update()

    assert result["active_version"] == "v0.32.0"
    assert result["previous_version"] == "v0.31.2"
    assert result["update_available"] is False
    assert result["rollback_available"] is True
    assert (workspace / "runtime" / "ollama" / "v0.31.2").is_dir()
    assert (workspace / "runtime" / "ollama" / "v0.32.0" / "bin" / "ollama.exe").read_bytes() == b"new"


def test_failed_update_leaves_the_known_good_release_active(tmp_path: Path) -> None:
    old_archive = tmp_path / "ollama-v0.31.2.zip"
    new_archive = tmp_path / "ollama-v0.32.0.zip"
    for archive, payload in ((old_archive, b"old"), (new_archive, b"new")):
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("bin/ollama.exe", payload)
    workspace = tmp_path / "workspace"
    archives = {"v0.31.2": old_archive, "v0.32.0": new_archive}
    _versioned_runtime(workspace, archives, target_version="v0.31.2").install()
    runtime = _versioned_runtime(
        workspace,
        archives,
        target_version="v0.32.0",
        bad_version="v0.32.0",
    )

    with pytest.raises(OllamaRuntimeError, match="hash verification failed"):
        runtime.update()

    status = _versioned_runtime(workspace, archives, target_version="v0.32.0").status()
    assert status["active_version"] == "v0.31.2"
    assert status["installed"] is True
    assert not (workspace / "runtime" / "ollama" / "v0.32.0").exists()


def test_rollback_state_durability_failure_is_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    old_archive = tmp_path / "ollama-v0.31.2.zip"
    new_archive = tmp_path / "ollama-v0.32.0.zip"
    for archive, payload in ((old_archive, b"old"), (new_archive, b"new")):
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("bin/ollama.exe", payload)
    workspace = tmp_path / "workspace"
    archives = {"v0.31.2": old_archive, "v0.32.0": new_archive}
    _versioned_runtime(workspace, archives, target_version="v0.31.2").install()
    runtime = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    runtime.update()
    state_path = runtime._runtime_state_path()
    durable_replace = ollama_runtime.durable_replace

    def fail_state_durability(source: Path, destination: Path) -> None:
        if destination == state_path:
            ollama_runtime.os.replace(source, destination)
            raise OSError("injected rollback durability failure")
        durable_replace(source, destination)

    monkeypatch.setattr(ollama_runtime, "durable_replace", fail_state_durability)

    with pytest.raises(OllamaRuntimeError, match="could not be saved"):
        runtime.run_synchronous_operation(
            "rollback",
            f"adm_{'3' * 32}",
            runtime.rollback,
        )

    status = runtime.status()
    assert status["active_version"] == "v0.32.0"
    assert status["operation"]["state"] == "indeterminate"
    assert status["unresolved_operation"]["id"] == status["operation"]["id"]
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["active_version"] == "v0.31.2"
    with pytest.raises(OllamaRuntimeError, match="outcome is unknown"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'4' * 32}",
            lambda: pytest.fail("fresh mutation must remain blocked"),
        )


def test_legacy_update_commits_old_selection_before_staging_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    old_archive = tmp_path / "ollama-v0.31.2.zip"
    new_archive = tmp_path / "ollama-v0.32.0.zip"
    for archive, payload in ((old_archive, b"old"), (new_archive, b"new")):
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("bin/ollama.exe", payload)
    workspace = tmp_path / "workspace"
    archives = {"v0.31.2": old_archive, "v0.32.0": new_archive}
    legacy = _versioned_runtime(workspace, archives, target_version="v0.31.2")
    legacy.install()
    legacy._runtime_state_path().unlink()
    runtime = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    write_state = runtime._write_runtime_state
    writes = 0

    def fail_final_state(active: str, previous: str | None) -> None:
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OllamaRuntimeError("injected final state failure")
        write_state(active, previous)

    monkeypatch.setattr(runtime, "_write_runtime_state", fail_final_state)

    with pytest.raises(OllamaRuntimeError, match="injected final state failure"):
        runtime.update()

    restarted = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    status = restarted.status()
    assert writes == 2
    assert status["active_version"] == "v0.31.2"
    assert status["installed"] is True
    assert status["integrity_error"] is None
    assert status["update_available"] is True
    assert (workspace / "runtime" / "ollama" / "v0.32.0").is_dir()


def test_missing_version_state_with_multiple_releases_fails_closed(tmp_path: Path) -> None:
    old_archive = tmp_path / "ollama-v0.31.2.zip"
    new_archive = tmp_path / "ollama-v0.32.0.zip"
    for archive, payload in ((old_archive, b"old"), (new_archive, b"new")):
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("bin/ollama.exe", payload)
    workspace = tmp_path / "workspace"
    archives = {"v0.31.2": old_archive, "v0.32.0": new_archive}
    runtime = _versioned_runtime(workspace, archives, target_version="v0.31.2")
    runtime.install()
    updater = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    updater.update()
    updater._runtime_state_path().unlink()

    restarted = _versioned_runtime(workspace, archives, target_version="v0.32.0")

    assert restarted.status()["integrity_error"] == "managed Ollama runtime version state is invalid"
    with pytest.raises(OllamaRuntimeError, match="runtime version state is invalid"):
        restarted.start(timeout_seconds=0.0)


def test_rollback_rehashes_previous_release_before_switching(tmp_path: Path) -> None:
    old_archive = tmp_path / "ollama-v0.31.2.zip"
    new_archive = tmp_path / "ollama-v0.32.0.zip"
    for archive, payload in ((old_archive, b"old"), (new_archive, b"new")):
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("bin/ollama.exe", payload)
    workspace = tmp_path / "workspace"
    archives = {"v0.31.2": old_archive, "v0.32.0": new_archive}
    _versioned_runtime(workspace, archives, target_version="v0.31.2").install()
    runtime = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    runtime.update()

    result = runtime.rollback()

    assert result["active_version"] == "v0.31.2"
    assert result["previous_version"] == "v0.32.0"
    assert result["update_available"] is True
    assert result["rollback_available"] is True


def test_cancelled_rollback_cannot_publish_the_verified_release(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    old_archive = tmp_path / "ollama-v0.31.2.zip"
    new_archive = tmp_path / "ollama-v0.32.0.zip"
    for archive, payload in ((old_archive, b"old"), (new_archive, b"new")):
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("bin/ollama.exe", payload)
    workspace = tmp_path / "workspace"
    archives = {"v0.31.2": old_archive, "v0.32.0": new_archive}
    _versioned_runtime(workspace, archives, target_version="v0.31.2").install()
    runtime = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    runtime.update()
    verification_started = threading.Event()
    release_verification = threading.Event()
    verified_executable = runtime._verified_executable
    blocked = False

    def block_rollback_verification(*args: Any, **kwargs: Any) -> Path:
        nonlocal blocked
        if kwargs.get("version") == "v0.31.2" and not blocked:
            blocked = True
            verification_started.set()
            assert release_verification.wait(timeout=2.0)
        return verified_executable(*args, **kwargs)

    monkeypatch.setattr(runtime, "_verified_executable", block_rollback_verification)
    errors: list[Exception] = []

    def rollback() -> None:
        try:
            runtime.run_synchronous_operation(
                "rollback",
                f"adm_{'7' * 32}",
                runtime.rollback,
            )
        except Exception as exc:  # noqa: BLE001 - asserted below
            errors.append(exc)

    worker = threading.Thread(target=rollback)
    worker.start()
    assert verification_started.wait(timeout=2.0)
    operation_id = runtime.status()["operation"]["id"]
    threading.Timer(0.05, release_verification.set).start()

    runtime.stop(timeout_seconds=2.0, expected_operation_id=operation_id)
    worker.join(timeout=2.0)

    assert worker.is_alive() is False
    assert len(errors) == 1
    assert "cancelled" in str(errors[0]).lower()
    assert runtime.status()["active_version"] == "v0.32.0"
    assert runtime.status()["operation"]["state"] == "cancelled"


def test_corrupt_active_release_still_reports_verified_rollback_capability(tmp_path: Path) -> None:
    old_archive = tmp_path / "ollama-v0.31.2.zip"
    new_archive = tmp_path / "ollama-v0.32.0.zip"
    for archive, payload in ((old_archive, b"old"), (new_archive, b"new")):
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("bin/ollama.exe", payload)
    workspace = tmp_path / "workspace"
    archives = {"v0.31.2": old_archive, "v0.32.0": new_archive}
    _versioned_runtime(workspace, archives, target_version="v0.31.2").install()
    runtime = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    runtime.update()
    (runtime.install_dir / "bin" / "ollama.exe").write_bytes(b"corrupt")

    status = _versioned_runtime(workspace, archives, target_version="v0.32.0").status()

    assert status["installed"] is False
    assert status["integrity_error"] is not None
    assert status["rollback_available"] is True
    assert status["rollback_allowed"] is True
    assert status["rollback_blocked_reason"] is None


def test_repair_reconstructs_corrupt_version_state_without_replacing_valid_runtime(tmp_path: Path) -> None:
    archive = tmp_path / "ollama-v0.32.0.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"known-good")
    workspace = tmp_path / "workspace"
    archives = {"v0.32.0": archive}
    installed = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    installed.install()
    executable = installed.install_dir / "bin" / "ollama.exe"
    state_path = installed._runtime_state_path()
    state_path.write_text("{not-json", encoding="utf-8")

    runtime = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    assert runtime.status()["integrity_error"] == "managed Ollama runtime version state is invalid"

    result = runtime.repair()

    assert result["installed"] is True
    assert result["integrity_error"] is None
    assert executable.read_bytes() == b"known-good"
    assert json.loads(state_path.read_text(encoding="utf-8")) == {
        "schema": 1,
        "active_version": "v0.32.0",
        "previous_version": None,
    }


def test_corrupt_version_state_blocks_direct_start_until_confirmed_repair(tmp_path: Path) -> None:
    archive = tmp_path / "ollama-v0.32.0.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"known-good")
    workspace = tmp_path / "workspace"
    archives = {"v0.32.0": archive}
    installed = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    installed.install()
    installed._runtime_state_path().write_text("{not-json", encoding="utf-8")
    spawn_calls = 0

    def process_factory(*_args: Any, **_kwargs: Any) -> _FakeProcess:
        nonlocal spawn_calls
        spawn_calls += 1
        return _FakeProcess()

    runtime = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    runtime._process_factory = process_factory

    with pytest.raises(OllamaRuntimeError, match="runtime version state is invalid"):
        runtime.start(timeout_seconds=0.0)

    assert spawn_calls == 0


def test_repair_unlinks_version_state_symlink_without_touching_its_target(tmp_path: Path) -> None:
    archive = tmp_path / "ollama-v0.32.0.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"known-good")
    workspace = tmp_path / "workspace"
    archives = {"v0.32.0": archive}
    installed = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    installed.install()
    state_path = installed._runtime_state_path()
    state_path.unlink()
    outside = tmp_path / "outside-state.json"
    outside.write_text("outside", encoding="utf-8")
    try:
        state_path.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    runtime = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    result = runtime.repair()

    assert result["integrity_error"] is None
    assert not state_path.is_symlink()
    assert outside.read_text(encoding="utf-8") == "outside"


def test_repair_state_rewrite_failure_is_indeterminate_after_symlink_unlink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "ollama-v0.32.0.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"known-good")
    workspace = tmp_path / "workspace"
    archives = {"v0.32.0": archive}
    installed = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    installed.install()
    state_path = installed._runtime_state_path()
    state_path.unlink()
    outside = tmp_path / "outside-state.json"
    outside.write_text("outside", encoding="utf-8")
    try:
        state_path.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    runtime = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    monkeypatch.setattr(
        runtime,
        "_write_runtime_state",
        lambda *_args: (_ for _ in ()).throw(OllamaRuntimeError("injected state write failure")),
    )

    with pytest.raises(OllamaRuntimeError, match="injected state write failure"):
        runtime.repair()

    blocker = runtime.status()["unresolved_operation"]
    assert blocker is not None
    assert blocker["kind"] == "repair"
    assert blocker["state"] == "indeterminate"
    assert not state_path.exists()
    assert outside.read_text(encoding="utf-8") == "outside"
    with pytest.raises(OllamaRuntimeError, match="outcome is unknown"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'c' * 32}",
            lambda: pytest.fail("fresh mutation must remain blocked"),
        )


def test_repair_state_durability_failure_is_indeterminate_after_replace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "ollama-v0.32.0.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"known-good")
    workspace = tmp_path / "workspace"
    archives = {"v0.32.0": archive}
    installed = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    installed.install()
    state_path = installed._runtime_state_path()
    state_path.write_text("{not-json", encoding="utf-8")
    runtime = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    durable_replace = ollama_runtime.durable_replace

    def fail_state_durability(source: Path, destination: Path) -> None:
        if destination == state_path:
            ollama_runtime.os.replace(source, destination)
            raise OSError("injected state durability failure")
        durable_replace(source, destination)

    monkeypatch.setattr(ollama_runtime, "durable_replace", fail_state_durability)

    with pytest.raises(OllamaRuntimeError, match="could not be saved"):
        runtime.repair()

    blocker = runtime.status()["unresolved_operation"]
    assert blocker is not None
    assert blocker["kind"] == "repair"
    assert blocker["state"] == "indeterminate"
    with pytest.raises(OllamaRuntimeError, match="outcome is unknown"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'d' * 32}",
            lambda: pytest.fail("fresh mutation must remain blocked"),
        )


def test_uninstall_removes_managed_releases_but_preserves_models_and_trust(tmp_path: Path) -> None:
    old_archive = tmp_path / "ollama-v0.31.2.zip"
    new_archive = tmp_path / "ollama-v0.32.0.zip"
    for archive, payload in ((old_archive, b"old"), (new_archive, b"new")):
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("bin/ollama.exe", payload)
    workspace = tmp_path / "workspace"
    archives = {"v0.31.2": old_archive, "v0.32.0": new_archive}
    _versioned_runtime(workspace, archives, target_version="v0.31.2").install()
    runtime = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    runtime.update()
    runtime.models_dir.mkdir(parents=True)
    (runtime.models_dir / "blob").write_bytes(b"model")
    alias = _trust_locked_model(runtime, "qwen3:8b", "a" * 64)

    result = runtime.uninstall()

    assert result["installed"] is False
    assert result["active_version"] == "v0.32.0"
    assert not (workspace / "runtime" / "ollama" / "v0.31.2").exists()
    assert not (workspace / "runtime" / "ollama" / "v0.32.0").exists()
    assert (runtime.models_dir / "blob").read_bytes() == b"model"
    assert runtime._read_accepted_model_digests() == {alias: "a" * 64}


def test_zero_release_uninstall_cleanup_failure_is_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = OllamaRuntime(tmp_path / "workspace", probe=lambda: None)
    runtime._write_runtime_state(runtime.target_version, None)
    state_path = runtime._runtime_state_path()
    durable_unlink = ollama_runtime.durable_unlink

    def fail_runtime_state_durability(path: Path) -> None:
        if path == state_path:
            path.unlink()
            raise OSError("injected uninstall durability failure")
        durable_unlink(path)

    monkeypatch.setattr(ollama_runtime, "durable_unlink", fail_runtime_state_durability)

    with pytest.raises(OllamaRuntimeError, match="could not be removed"):
        runtime.run_synchronous_operation(
            "uninstall",
            f"adm_{'5' * 32}",
            runtime.uninstall,
        )

    status = runtime.status()
    assert not state_path.exists()
    assert runtime._uninstall_release_entries() == []
    assert runtime._read_uninstall_state()["phase"] == "committed"
    assert status["operation"]["state"] == "indeterminate"
    assert status["unresolved_operation"]["id"] == status["operation"]["id"]
    with pytest.raises(OllamaRuntimeError, match="outcome is unknown"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'6' * 32}",
            lambda: pytest.fail("fresh mutation must remain blocked"),
        )


def test_uninstall_refuses_a_running_managed_process(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: "0.32.0")
    runtime._process = _FakeProcess()

    with pytest.raises(OllamaRuntimeError, match="must be stopped"):
        runtime.uninstall()


def test_uninstall_rolls_back_all_quarantines_when_prepare_cannot_finish(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    old_archive = tmp_path / "ollama-v0.31.2.zip"
    new_archive = tmp_path / "ollama-v0.32.0.zip"
    for archive, payload in ((old_archive, b"old"), (new_archive, b"new")):
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("bin/ollama.exe", payload)
    workspace = tmp_path / "workspace"
    archives = {"v0.31.2": old_archive, "v0.32.0": new_archive}
    _versioned_runtime(workspace, archives, target_version="v0.31.2").install()
    runtime = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    runtime.update()
    state_before = runtime._runtime_state_path().read_bytes()
    replace = ollama_runtime.os.replace
    quarantine_moves = 0

    def fail_second_quarantine(source: Any, destination: Any) -> None:
        nonlocal quarantine_moves
        source_path = Path(source)
        destination_path = Path(destination)
        if source_path.name in archives and destination_path.name.startswith(".uninstall-"):
            quarantine_moves += 1
            if quarantine_moves == 2:
                raise OSError("injected quarantine failure")
        replace(source, destination)

    monkeypatch.setattr(ollama_runtime.os, "replace", fail_second_quarantine)

    with pytest.raises(OllamaRuntimeError, match="uninstall"):
        runtime.uninstall()

    assert quarantine_moves == 2
    assert runtime._runtime_state_path().read_bytes() == state_before
    assert all((runtime.runtime_root / version).is_dir() for version in archives)
    assert not (runtime.runtime_root / ".flinttrade-uninstall-state.json").exists()
    assert not list(runtime.runtime_root.glob(".uninstall-*"))


def test_unproved_uninstall_recovery_is_indeterminate_and_blocks_fresh_work(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "ollama-v0.32.0.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"runtime")
    workspace = tmp_path / "workspace"
    runtime = _versioned_runtime(
        workspace,
        {"v0.32.0": archive},
        target_version="v0.32.0",
    )
    runtime.install()
    write_state = runtime._write_uninstall_state

    def fail_commit(*, phase: str, token: str, releases: list[dict[str, str]]) -> dict[str, Any]:
        if phase == "committed":
            raise OllamaRuntimeError("commit state failed")
        return write_state(phase=phase, token=token, releases=releases)

    monkeypatch.setattr(runtime, "_write_uninstall_state", fail_commit)
    monkeypatch.setattr(
        runtime,
        "_rollback_prepared_uninstall",
        lambda _state: (_ for _ in ()).throw(OllamaRuntimeError("rollback is unproved")),
    )

    with pytest.raises(OllamaRuntimeError, match="recovery could not be proven"):
        runtime.run_synchronous_operation(
            "uninstall",
            f"adm_{'9' * 32}",
            runtime.uninstall,
        )

    blocker = runtime.status()["unresolved_operation"]
    assert blocker is not None
    assert blocker["kind"] == "uninstall"
    assert blocker["state"] == "indeterminate"
    assert not runtime.install_dir.exists()
    assert list(runtime.runtime_root.glob(".uninstall-*"))
    with pytest.raises(OllamaRuntimeError, match="outcome is unknown"):
        runtime.run_synchronous_operation(
            "reset_model_digests",
            f"adm_{'a' * 32}",
            lambda: pytest.fail("fresh mutation must remain blocked"),
        )


def test_prepared_uninstall_is_rolled_back_after_an_abrupt_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    old_archive = tmp_path / "ollama-v0.31.2.zip"
    new_archive = tmp_path / "ollama-v0.32.0.zip"
    for archive, payload in ((old_archive, b"old"), (new_archive, b"new")):
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("bin/ollama.exe", payload)
    workspace = tmp_path / "workspace"
    archives = {"v0.31.2": old_archive, "v0.32.0": new_archive}
    _versioned_runtime(workspace, archives, target_version="v0.31.2").install()
    runtime = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    runtime.update()
    replace = ollama_runtime.os.replace
    quarantine_moves = 0

    def interrupt_second_quarantine(source: Any, destination: Any) -> None:
        nonlocal quarantine_moves
        source_path = Path(source)
        destination_path = Path(destination)
        if source_path.name in archives and destination_path.name.startswith(".uninstall-"):
            quarantine_moves += 1
            if quarantine_moves == 2:
                raise SystemExit("simulated process exit")
        replace(source, destination)

    monkeypatch.setattr(ollama_runtime.os, "replace", interrupt_second_quarantine)
    with pytest.raises(SystemExit, match="simulated process exit"):
        runtime.uninstall()
    monkeypatch.setattr(ollama_runtime.os, "replace", replace)

    restarted = _versioned_runtime(workspace, archives, target_version="v0.32.0")

    assert restarted.status()["installed"] is True
    assert restarted.status()["active_version"] == "v0.32.0"
    assert all((restarted.runtime_root / version).is_dir() for version in archives)
    assert not (restarted.runtime_root / ".flinttrade-uninstall-state.json").exists()
    assert not list(restarted.runtime_root.glob(".uninstall-*"))


def test_committed_uninstall_cleanup_is_completed_on_restart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "ollama-v0.32.0.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"runtime")
    workspace = tmp_path / "workspace"
    archives = {"v0.32.0": archive}
    runtime = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    runtime.install()
    remove_path = ollama_runtime._remove_path_without_following_root
    failed = False

    def fail_first_quarantine_cleanup(path: Path) -> None:
        nonlocal failed
        if path.name.startswith(".uninstall-") and not failed:
            failed = True
            raise OllamaRuntimeError("injected uninstall cleanup failure")
        remove_path(path)

    monkeypatch.setattr(ollama_runtime, "_remove_path_without_following_root", fail_first_quarantine_cleanup)
    with pytest.raises(OllamaRuntimeError, match="cleanup"):
        runtime.uninstall()
    monkeypatch.setattr(ollama_runtime, "_remove_path_without_following_root", remove_path)

    restarted = _versioned_runtime(workspace, archives, target_version="v0.32.0")

    assert restarted.status()["installed"] is False
    assert not restarted._runtime_state_path().exists()
    assert not (restarted.runtime_root / ".flinttrade-uninstall-state.json").exists()
    assert not list(restarted.runtime_root.glob(".uninstall-*"))


def test_uninstall_refuses_an_unknown_version_directory_without_removing_known_releases(tmp_path: Path) -> None:
    archive = tmp_path / "ollama-v0.32.0.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"runtime")
    workspace = tmp_path / "workspace"
    archives = {"v0.32.0": archive}
    runtime = _versioned_runtime(workspace, archives, target_version="v0.32.0")
    runtime.install()
    unknown = runtime.runtime_root / "v9.9.9"
    unknown.mkdir()
    (unknown / "do-not-delete").write_text("unknown", encoding="utf-8")

    with pytest.raises(OllamaRuntimeError, match="not recognised"):
        runtime.uninstall()

    assert runtime.install_dir.is_dir()
    assert (unknown / "do-not-delete").read_text(encoding="utf-8") == "unknown"


def test_uninstall_unlinks_a_known_release_symlink_without_touching_its_target(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside-runtime"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("outside", encoding="utf-8")
    runtime = OllamaRuntime(workspace, probe=lambda: None)
    runtime.runtime_root.mkdir(parents=True)
    try:
        runtime.install_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this platform")

    result = runtime.uninstall()

    assert result["installed"] is False
    assert not runtime.install_dir.exists()
    assert not runtime.install_dir.is_symlink()
    assert sentinel.read_text(encoding="utf-8") == "outside"


def test_uninstall_removes_only_provably_owned_runtime_residue(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/ollama.exe", b"runtime")
    runtime = OllamaRuntime(
        tmp_path / "workspace",
        asset=_fake_asset(archive),
        downloader=_copy_download(archive),
        probe=lambda: None,
    )
    runtime.install()
    staging = runtime.runtime_root / ".staging"
    owned_install = staging / f"install-{'a' * 32}"
    unmarked_install = staging / f"install-{'b' * 32}"
    owned_repair = runtime.runtime_root / f".repair-{'c' * 32}"
    for path in (owned_install, unmarked_install, owned_repair):
        path.mkdir(parents=True)
        (path / "payload").write_bytes(b"residue")
    runtime._write_residue_marker(
        owned_install,
        kind="install",
        owner_pid=2**22,
        owner_create_time=1.0,
    )
    runtime._write_residue_marker(
        owned_repair,
        kind="repair",
        owner_pid=2**22,
        owner_create_time=1.0,
    )

    runtime.uninstall()

    assert not owned_install.exists()
    assert not owned_repair.exists()
    assert not runtime._residue_marker_path(owned_repair, kind="repair").exists()
    assert (unmarked_install / "payload").read_bytes() == b"residue"


def test_delete_model_removes_exact_alias_and_reconciles_trust(tmp_path: Path) -> None:
    digest = "a" * 64
    locked_alias = ollama_runtime._locked_model_alias(digest)
    models = {
        "qwen3:8b": digest,
        locked_alias: digest,
        "other:latest": "b" * 64,
    }
    calls: list[tuple[str, str]] = []

    def request_json(method: str, path: str, payload: Any) -> dict[str, Any] | None:
        if method == "DELETE" and path == "/api/delete":
            model = str(payload["model"])
            calls.append((method, model))
            models.pop(model, None)
            return None
        return {
            "models": [
                {"name": name, "model": name, "digest": model_digest}
                for name, model_digest in models.items()
            ]
        }

    runtime = OllamaRuntime(tmp_path, probe=lambda: "0.32.0", request_json=request_json)
    runtime._process = _FakeProcess()
    runtime._write_model_trust_state({locked_alias: digest}, {"qwen3:8b": locked_alias})

    result = runtime.delete_model("qwen3:8b", protected_models=(locked_alias,))

    assert result == {"deleted": ["qwen3:8b"], "pruned": []}
    assert calls == [("DELETE", "qwen3:8b")]
    assert runtime._read_model_trust_state() == ({locked_alias: digest}, {})
    assert set(models) == {locked_alias, "other:latest"}


def test_shutdown_waits_for_model_delete_reconciliation_before_cancelling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    digest = "a" * 64
    models = {"qwen3:8b": digest}
    delete_committed = threading.Event()
    release_delete = threading.Event()
    process = _FakeProcess()

    def request_json(method: str, path: str, payload: Any) -> dict[str, Any] | None:
        if method == "DELETE" and path == "/api/delete":
            models.pop(str(payload["model"]), None)
            delete_committed.set()
            assert release_delete.wait(timeout=2.0)
            return None
        return {
            "models": [
                {"name": name, "model": name, "digest": model_digest}
                for name, model_digest in models.items()
            ]
        }

    runtime = OllamaRuntime(
        tmp_path,
        probe=lambda: "0.32.0" if process.poll() is None else None,
        request_json=request_json,
    )
    runtime._process = process
    monkeypatch.setattr(
        ollama_runtime,
        "_terminate_process_tree",
        lambda owned_process, **_kwargs: setattr(owned_process, "returncode", 0),
    )
    result: list[tuple[dict[str, Any], int]] = []
    errors: list[BaseException] = []

    def delete() -> None:
        try:
            result.append(runtime.run_synchronous_operation(
                "delete_model",
                f"adm_{'a' * 32}",
                lambda: runtime.delete_model("qwen3:8b"),
                operation_subject={"model": "qwen3:8b"},
            ))
        except BaseException as exc:  # noqa: BLE001 - asserted below
            errors.append(exc)

    delete_thread = threading.Thread(target=delete)
    delete_thread.start()
    assert delete_committed.wait(timeout=2.0)
    shutdown_result: list[bool] = []
    shutdown_thread = threading.Thread(target=lambda: shutdown_result.append(runtime.shutdown(timeout=1.0)))
    shutdown_thread.start()
    assert shutdown_thread.is_alive() is True

    release_delete.set()
    delete_thread.join(timeout=2.0)
    shutdown_thread.join(timeout=2.0)

    assert errors == []
    assert result == [({"deleted": ["qwen3:8b"], "pruned": []}, 200)]
    assert runtime.status()["operation"]["state"] == "succeeded"
    assert shutdown_result == [True]
    assert delete_thread.is_alive() is False
    assert shutdown_thread.is_alive() is False


def test_delete_model_refuses_the_selected_model(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path, probe=lambda: "0.32.0")
    runtime._process = _FakeProcess()

    with pytest.raises(OllamaRuntimeError, match="selected model"):
        runtime.delete_model("qwen3:8b", protected_models=("qwen3:8b",))


def test_prune_removes_only_unreferenced_flinttrade_locked_aliases(tmp_path: Path) -> None:
    stale_digest = "a" * 64
    retained_digest = "b" * 64
    stale_alias = ollama_runtime._locked_model_alias(stale_digest)
    retained_alias = ollama_runtime._locked_model_alias(retained_digest)
    models = {
        stale_alias: stale_digest,
        retained_alias: retained_digest,
        "source:latest": retained_digest,
        "qwen3:8b": "c" * 64,
    }
    deleted: list[str] = []

    def request_json(method: str, path: str, payload: Any) -> dict[str, Any] | None:
        if method == "DELETE" and path == "/api/delete":
            model = str(payload["model"])
            deleted.append(model)
            models.pop(model, None)
            return None
        return {
            "models": [
                {"name": name, "model": name, "digest": digest}
                for name, digest in models.items()
            ]
        }

    runtime = OllamaRuntime(tmp_path, probe=lambda: "0.32.0", request_json=request_json)
    runtime._process = _FakeProcess()
    runtime._write_model_trust_state(
        {stale_alias: stale_digest, retained_alias: retained_digest},
        {"source:latest": retained_alias},
    )

    result = runtime.prune_models(protected_models=(retained_alias,))

    assert result == {"deleted": [], "pruned": [stale_alias]}
    assert deleted == [stale_alias]
    assert set(models) == {retained_alias, "source:latest", "qwen3:8b"}
    assert runtime._read_model_trust_state() == (
        {retained_alias: retained_digest},
        {"source:latest": retained_alias},
    )


def test_prune_recovers_an_unrecorded_locked_alias_left_by_interrupted_acceptance(tmp_path: Path) -> None:
    digest = "d" * 64
    orphaned_alias = ollama_runtime._locked_model_alias(digest)
    models = {orphaned_alias: digest, "qwen3:8b": digest}
    deleted: list[str] = []

    def request_json(method: str, path: str, payload: Any) -> dict[str, Any] | None:
        if method == "DELETE" and path == "/api/delete":
            model = str(payload["model"])
            deleted.append(model)
            models.pop(model, None)
            return None
        return {
            "models": [
                {"name": name, "model": name, "digest": model_digest}
                for name, model_digest in models.items()
            ]
        }

    runtime = OllamaRuntime(tmp_path, probe=lambda: "0.32.0", request_json=request_json)
    runtime._process = _FakeProcess()

    result = runtime.prune_models()

    assert result == {"deleted": [], "pruned": [orphaned_alias]}
    assert deleted == [orphaned_alias]
    assert set(models) == {"qwen3:8b"}


def test_prune_reconciles_successful_deletions_when_a_later_delete_fails(tmp_path: Path) -> None:
    first_digest = "a" * 64
    second_digest = "b" * 64
    first_alias = ollama_runtime._locked_model_alias(first_digest)
    second_alias = ollama_runtime._locked_model_alias(second_digest)
    models = {first_alias: first_digest, second_alias: second_digest}
    delete_calls = 0

    def request_json(method: str, path: str, payload: Any) -> dict[str, Any] | None:
        nonlocal delete_calls
        if method == "DELETE" and path == "/api/delete":
            delete_calls += 1
            if delete_calls == 2:
                raise OllamaRuntimeError("injected Ollama delete failure")
            models.pop(str(payload["model"]), None)
            return None
        return {
            "models": [
                {"name": name, "model": name, "digest": digest}
                for name, digest in models.items()
            ]
        }

    runtime = OllamaRuntime(tmp_path, probe=lambda: "0.32.0", request_json=request_json)
    runtime._process = _FakeProcess()
    runtime._write_model_trust_state(
        {first_alias: first_digest, second_alias: second_digest},
        {},
    )

    with pytest.raises(OllamaRuntimeError, match="injected Ollama delete failure"):
        runtime.prune_models()

    assert set(models) == {second_alias}
    assert runtime._read_model_trust_state() == ({second_alias: second_digest}, {})


def test_model_inventory_reconciles_a_missing_locked_alias_before_reporting_trust(tmp_path: Path) -> None:
    digest = "a" * 64
    locked_alias = ollama_runtime._locked_model_alias(digest)

    def request_json(_method: str, _path: str, _payload: Any) -> dict[str, Any]:
        return {
            "models": [
                {"name": "qwen3:8b", "model": "qwen3:8b", "digest": digest},
            ]
        }

    runtime = OllamaRuntime(tmp_path, probe=lambda: "0.32.0", request_json=request_json)
    runtime._process = _FakeProcess()
    runtime._write_model_trust_state({locked_alias: digest}, {"qwen3:8b": locked_alias})

    models = runtime.list_models()

    assert models == [{"name": "qwen3:8b", "model": "qwen3:8b", "digest": digest}]
    assert runtime._read_model_trust_state() == ({}, {})
