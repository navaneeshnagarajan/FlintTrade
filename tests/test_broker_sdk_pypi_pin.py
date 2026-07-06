"""The SDK audit downloader must cross-check the artifact against brokers.lock.

Verifying only PyPI's self-advertised digest is insufficient: PyPI permits
adding files to an existing release and this tool prefers wheels over sdists, so
the audit cache could silently hold an artifact different from the one the repo
pinned in brokers.lock. A mismatch against the brokers.lock sha256 must raise.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]


def _load_sync_module():
    spec = importlib.util.spec_from_file_location(
        "sync_broker_sdk_refs", REPO / "scripts" / "sync_broker_sdk_refs.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_ARTIFACT = b"fake wheel bytes"
_ARTIFACT_SHA = hashlib.sha256(_ARTIFACT).hexdigest()
_ARTIFACT_URL = "https://files.pythonhosted.org/packages/fake/pkg-1.0.0-py3-none-any.whl"


def _fake_opener(url: str):
    if url.startswith("https://pypi.org/pypi/"):
        payload = {
            "info": {"version": "1.0.0"},
            "releases": {
                "1.0.0": [
                    {
                        "url": _ARTIFACT_URL,
                        "filename": "pkg-1.0.0-py3-none-any.whl",
                        "packagetype": "bdist_wheel",
                        "digests": {"sha256": _ARTIFACT_SHA},
                    }
                ]
            },
        }
        return 200, json.dumps(payload).encode("utf-8")
    if url == _ARTIFACT_URL:
        return 200, _ARTIFACT
    raise AssertionError(f"unexpected URL: {url}")


def test_download_accepts_matching_brokers_lock_pin(tmp_path):
    sync = _load_sync_module()
    result = sync.download_pypi_artifact(
        "pkg", "1.0.0", tmp_path, _fake_opener, pinned_sha=_ARTIFACT_SHA
    )
    assert result["sha256"] == _ARTIFACT_SHA
    assert result["brokers_lock_sha_match"] == "true"


def test_download_raises_on_brokers_lock_pin_mismatch(tmp_path):
    sync = _load_sync_module()
    wrong = "0" * 64
    with pytest.raises(RuntimeError, match="brokers.lock sha256 mismatch"):
        sync.download_pypi_artifact("pkg", "1.0.0", tmp_path, _fake_opener, pinned_sha=wrong)


def test_download_without_pin_still_works(tmp_path):
    sync = _load_sync_module()
    result = sync.download_pypi_artifact("pkg", "1.0.0", tmp_path, _fake_opener)
    assert result["sha256"] == _ARTIFACT_SHA
    assert "brokers_lock_sha_match" not in result


def test_active_sdk_entries_carries_sha256():
    sync = _load_sync_module()
    entries = sync.active_sdk_entries([
        {"name": "dhanhq", "version": "2.2.0", "sha256": "abc123", "source_commit": ""},
    ])
    assert entries and entries[0]["sha256"] == "abc123"
