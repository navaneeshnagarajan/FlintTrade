"""Bounded About metadata, with no SDK execution or private provenance output."""

from __future__ import annotations

import builtins
import importlib
import json
import socket
from importlib import metadata
from pathlib import Path

import pytest
from flask import Flask

pytestmark = pytest.mark.unit

PACKAGES = (
    "flask", "werkzeug", "waitress", "pydantic", "httpx", "websockets",
    "numpy", "pandas", "duckdb", "pyarrow", "cryptography", "sentry-sdk", "flinttrade-ticks",
)
BROKERS = ("dhanhq", "upstox-python-sdk", "kotakneoapi", "growwapi")
CONFIGURED_COMMIT = "a" * 40
INSTALLED_COMMIT = "b" * 40


def _inventory_module():
    return importlib.import_module("flinttrade_core.version_inventory")


def _write_manifests(root: Path) -> None:
    (root / "uv.lock").write_text(
        "\n".join(f'[[package]]\nname = "{name}"\nversion = "1.2.3"\n' for name in PACKAGES)
        + '[[package]]\nname = "private-unrelated-package"\nversion = "9.9.9"\n',
        encoding="utf-8",
    )
    (root / "brokers.lock").write_text(
        "\n".join(
            f'[[broker]]\nname = "{name}"\nversion = "3.0.7"\n'
            + (f'source_commit = "{CONFIGURED_COMMIT}"\n' if name == "kotakneoapi" else "")
            + 'homepage = "https://private-host.test/private/path?token=private-token"\n'
            + 'notes = "private-note"\n'
            for name in BROKERS
        ),
        encoding="utf-8",
    )


def _install_metadata(monkeypatch, root: Path, *, missing=(), direct_url=None, versions=None) -> list[str]:
    distributions = {}
    for name in (*PACKAGES, *BROKERS):
        if name in missing:
            continue
        dist_info = root / f"{name}.dist-info"
        dist_info.mkdir()
        version = (versions or {}).get(name, "4.5.6")
        (dist_info / "METADATA").write_text(f"Name: {name}\nVersion: {version}\n", encoding="utf-8")
        if name == "kotakneoapi" and direct_url is not None:
            (dist_info / "direct_url.json").write_text(direct_url, encoding="utf-8")
        distributions[name] = metadata.PathDistribution(dist_info)
    requested = []

    def distribution(name):
        requested.append(name)
        if name not in distributions:
            raise metadata.PackageNotFoundError(name)
        return distributions[name]

    monkeypatch.setattr(metadata, "distribution", distribution)
    return requested


def _by_name(rows):
    return {row["name"]: row for row in rows}


def test_inventory_separates_runtime_installed_and_configured_metadata(tmp_path, monkeypatch):
    mod = _inventory_module()
    _write_manifests(tmp_path)
    requested = _install_metadata(
        monkeypatch, tmp_path,
        direct_url=json.dumps({
            "url": "https://private-user:private-token@private-host.test/private/path",
            "vcs_info": {"vcs": "git", "commit_id": INSTALLED_COMMIT, "requested_revision": "private-branch"},
        }),
    )
    monkeypatch.setattr(mod.platform, "python_version", lambda: "3.12.14")
    monkeypatch.setattr(mod.sqlite3, "sqlite_version", "3.46.1")
    result = mod.build_version_inventory(source_root=tmp_path)
    assert set(result) == {"app_version", "runtimes", "packages", "brokers"}
    assert result["app_version"] == mod.APP_VERSION
    assert result["runtimes"] == [{"name": "Python", "version": "3.12.14"}, {"name": "SQLite", "version": "3.46.1"}]
    assert result["packages"] == [{"name": name, "installed": "4.5.6", "configured": "1.2.3"} for name in PACKAGES]
    assert [row["name"] for row in result["brokers"]] == list(BROKERS)
    assert _by_name(result["brokers"])["kotakneoapi"] == {
        "name": "kotakneoapi", "installed": "4.5.6", "configured": "3.0.7",
        "source_commit": CONFIGURED_COMMIT, "installed_commit": INSTALLED_COMMIT,
    }
    assert set(requested) == set(PACKAGES + BROKERS)
    assert len(requested) == len(PACKAGES + BROKERS)
    assert "private-" not in json.dumps(result)


def test_missing_distributions_do_not_fall_back_to_configured_versions(tmp_path, monkeypatch):
    mod = _inventory_module()
    _write_manifests(tmp_path)
    _install_metadata(monkeypatch, tmp_path, missing=PACKAGES + BROKERS)
    result = mod.build_version_inventory(source_root=tmp_path)
    assert all(row["installed"] is None for row in result["packages"] + result["brokers"])
    assert all(row["configured"] is not None for row in result["packages"] + result["brokers"])
    assert all(row["installed_commit"] is None for row in result["brokers"])


@pytest.mark.parametrize("contents", [None, "not valid = [", 'package = "wrong"\nbroker = "wrong"', "package = [7]\nbroker = [7]"])
def test_missing_or_malformed_manifests_leave_configured_values_unavailable(tmp_path, monkeypatch, contents):
    mod = _inventory_module()
    _install_metadata(monkeypatch, tmp_path)
    if contents is not None:
        for filename in ("uv.lock", "brokers.lock"):
            (tmp_path / filename).write_text(contents, encoding="utf-8")
    result = mod.build_version_inventory(source_root=tmp_path)
    assert all(row["configured"] is None for row in result["packages"] + result["brokers"])
    assert all(row["source_commit"] is None for row in result["brokers"])
    assert all(row["installed"] == "4.5.6" for row in result["packages"] + result["brokers"])


@pytest.mark.parametrize("direct_url", [
    "invalid json", "[]", "null", '{"vcs_info": []}',
    json.dumps({"vcs_info": {"vcs": "git", "commit_id": "private-token"}}),
    json.dumps({"vcs_info": {"vcs": "git", "commit_id": "a" * 40 + "\n"}}),
    json.dumps({"vcs_info": {"vcs": "hg", "commit_id": INSTALLED_COMMIT}}),
    json.dumps({"vcs_info": {"vcs": "git", "requested_revision": INSTALLED_COMMIT}}),
    json.dumps({"url": "file:///private/path", "dir_info": {"editable": True}}),
])
def test_installed_provenance_only_exposes_full_git_commit_ids(tmp_path, monkeypatch, direct_url):
    mod = _inventory_module()
    _install_metadata(monkeypatch, tmp_path, direct_url=direct_url)
    result = mod.build_version_inventory(source_root=tmp_path)
    assert _by_name(result["brokers"])["kotakneoapi"]["installed_commit"] is None
    assert "private" not in json.dumps(result)


def test_invalid_versions_and_configured_commits_are_not_returned(tmp_path, monkeypatch):
    mod = _inventory_module()
    _install_metadata(monkeypatch, tmp_path, versions={"flask": "https://private-host.test/version"})
    (tmp_path / "uv.lock").write_text('[[package]]\nname = "flask"\nversion = "file:///private/path"\n', encoding="utf-8")
    (tmp_path / "brokers.lock").write_text(
        '[[broker]]\nname = "kotakneoapi"\nversion = "/private/path"\nsource_commit = "private-token"\n',
        encoding="utf-8",
    )
    result = mod.build_version_inventory(source_root=tmp_path)
    assert _by_name(result["packages"])["flask"] == {"name": "flask", "installed": None, "configured": None}
    assert _by_name(result["brokers"])["kotakneoapi"]["configured"] is None
    assert _by_name(result["brokers"])["kotakneoapi"]["source_commit"] is None
    assert "private" not in json.dumps(result)


def test_ambiguous_manifest_entries_are_unavailable(tmp_path, monkeypatch):
    mod = _inventory_module()
    _install_metadata(monkeypatch, tmp_path)
    for filename, table, name in (("uv.lock", "package", "flask"), ("brokers.lock", "broker", "kotakneoapi")):
        (tmp_path / filename).write_text(
            f'[[{table}]]\nname = "{name}"\nversion = "1.0"\n'
            f'[[{table}]]\nname = "{name}"\nversion = "2.0"\n',
            encoding="utf-8",
        )
    result = mod.build_version_inventory(source_root=tmp_path)
    assert _by_name(result["packages"])["flask"]["configured"] is None
    assert _by_name(result["brokers"])["kotakneoapi"]["configured"] is None


def test_unavailable_source_checkout_still_reports_installed_metadata(tmp_path, monkeypatch):
    mod = _inventory_module()
    _install_metadata(monkeypatch, tmp_path)

    def unavailable():
        raise mod.SourceRootError("private path is not a source checkout")

    monkeypatch.setattr(mod, "discover_source_root", unavailable)
    result = mod.build_version_inventory()
    assert all(row["configured"] is None for row in result["packages"] + result["brokers"])
    assert all(row["installed"] == "4.5.6" for row in result["packages"] + result["brokers"])
    assert "private" not in json.dumps(result)


def test_inventory_does_not_import_sdks_enumerate_packages_or_use_network(tmp_path, monkeypatch):
    mod = _inventory_module()
    _write_manifests(tmp_path)
    _install_metadata(monkeypatch, tmp_path)
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        assert name.split(".")[0] not in {"dhanhq", "upstox_client", "neo_api_client", "growwapi"}
        return original_import(name, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("Inventory must not enumerate distributions or use network")

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(metadata, "distributions", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    importlib.reload(mod)
    assert len(mod.build_version_inventory(source_root=tmp_path)["brokers"]) == 4


def test_versions_route_returns_metadata_and_stays_session_authenticated(tmp_path, monkeypatch):
    mod = _inventory_module()
    _write_manifests(tmp_path)
    _install_metadata(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "discover_source_root", lambda: tmp_path)
    from flinttrade_core.health_routes import health_bp
    from flinttrade_core.public_routes import is_public_route

    app = Flask(__name__)
    app.register_blueprint(health_bp)
    route = next((rule for rule in app.url_map.iter_rules() if rule.rule == "/api/v1/versions"), None)
    assert route is not None
    assert route.methods == {"GET", "HEAD", "OPTIONS"}
    assert not is_public_route("GET", route.rule)
    assert not is_public_route("HEAD", route.rule)
    response = app.test_client().get("/api/v1/versions")
    assert response.status_code == 200
    assert response.get_json() == mod.build_version_inventory(source_root=tmp_path)


def _bare_ollama_runtime(tmp_path, *, port=43123, target="v0.35.0"):
    """Seed state without running constructor recovery or touching a real install."""
    from flinttrade_core.ollama_runtime import OllamaRuntime

    runtime = object.__new__(OllamaRuntime)
    runtime.target_version = target
    runtime._port = port
    runtime.workspace_dir = tmp_path
    runtime.runtime_root = tmp_path / "runtime"
    runtime._operation = {"id": "sentinel-operation", "state": "running"}
    runtime._operations = [{"id": "earlier-operation", "state": "complete"}]
    runtime._operation_journal_observed = True
    runtime._operation_truth_error = "sentinel-state"
    runtime._operation_owner_lease = "sentinel-owner"
    runtime._active_version = "v0.34.0"
    runtime._phase = "installing"
    runtime._error = "sentinel-error"
    runtime._process = {"pid": "sentinel-owner"}
    (tmp_path / "operation.json").write_text('{"state":"running"}', encoding="utf-8")
    (tmp_path / "receipt.json").write_text('{"verified":true}', encoding="utf-8")
    (tmp_path / "owner.json").write_text('{"owner":"sentinel"}', encoding="utf-8")
    return runtime


def test_ollama_version_snapshot_preserves_operation_receipt_and_ownership(tmp_path, monkeypatch):
    import copy
    import flinttrade_core.ollama_runtime as ollama

    runtime = _bare_ollama_runtime(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("About must not call lifecycle, installation, ownership or custom probes")

    for name in (
        "_probe", "status", "_status_snapshot", "_refresh_operation_status", "_installation_status",
        "_verified_executable", "_listener_is_owned", "_read_process_owner_record", "start",
        "_load_runtime_state", "_load_operation_state",
    ):
        monkeypatch.setattr(runtime, name, forbidden, raising=False)
    before_state = copy.deepcopy(vars(runtime))
    def files_snapshot():
        return {
            path.relative_to(tmp_path).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in tmp_path.rglob("*") if path.is_file()
        }

    before_files = files_snapshot()
    owner_before = ollama._MANAGED_RUNTIME_OWNER
    body = b'{"version":"0.34.0"}'
    connection = _ProbeSocket([
        b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body,
    ])
    connections = []

    def connect(address, *, timeout):
        connections.append((address, timeout))
        return connection

    monkeypatch.setattr(ollama.socket, "create_connection", connect)
    monkeypatch.setattr(ollama.time, "monotonic", lambda: 100.0)
    result = runtime.version_snapshot()
    assert result == {"configured": "v0.35.0", "reported": "0.34.0", "status": "reported"}
    assert len(connections) == 1
    assert connections[0][0] == ("127.0.0.1", 43123)
    assert 0 < connections[0][1] <= 0.75
    assert all(0 < timeout <= 0.75 for timeout in connection.timeouts)
    assert len(connection.sent) == 1
    assert connection.sent[0].startswith(b"GET /api/version HTTP/1.1\r\nHost: 127.0.0.1:43123\r\n")
    assert vars(runtime) == before_state
    assert files_snapshot() == before_files
    assert ollama._MANAGED_RUNTIME_OWNER is owner_before


@pytest.mark.parametrize("port", [0, -1, 80, 65536, True, "43123", None])
def test_ollama_snapshot_without_managed_port_does_not_probe(tmp_path, monkeypatch, port):
    import flinttrade_core.ollama_runtime as ollama

    runtime = _bare_ollama_runtime(tmp_path, port=port)

    def forbidden(*args, **kwargs):
        raise AssertionError("A missing or invalid managed port must not be probed")

    monkeypatch.setattr(ollama.socket, "create_connection", forbidden)
    assert runtime.version_snapshot() == {"configured": "v0.35.0", "reported": None, "status": "unavailable"}


@pytest.mark.parametrize("reported", [None, "http://private-host/version", "/private/path", "private-host.test", {"secret": "private"}])
def test_ollama_snapshot_sanitises_version_values(tmp_path, monkeypatch, reported):
    import flinttrade_core.ollama_runtime as ollama

    runtime = _bare_ollama_runtime(tmp_path, target="file:///private/path")
    body = json.dumps({"version": reported}).encode()
    connection = _ProbeSocket([
        b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body,
    ])
    monkeypatch.setattr(ollama.socket, "create_connection", lambda *args, **kwargs: connection)
    assert runtime.version_snapshot() == {"configured": None, "reported": None, "status": "unavailable"}


class _ProbeSocket:
    """Deterministic raw HTTP transport to exercise redirect and deadline handling."""

    def __init__(self, responses, *, tick=None):
        self.responses = iter(responses)
        self.tick = tick
        self.sent = []
        self.timeouts = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, size):
        if self.tick is not None:
            self.tick()
        return next(self.responses, b"")


def test_ollama_snapshot_only_requests_version_and_never_follows_redirects(tmp_path, monkeypatch):
    import flinttrade_core.ollama_runtime as ollama

    runtime = _bare_ollama_runtime(tmp_path)
    connection = _ProbeSocket([
        b"HTTP/1.1 302 Found\r\nLocation: https://private-host.test/secret\r\nContent-Length: 0\r\n\r\n",
    ])
    connections = []

    def connect(address, *, timeout):
        connections.append((address, timeout))
        return connection

    monkeypatch.setattr(ollama.socket, "create_connection", connect)
    result = runtime.version_snapshot()
    assert result == {"configured": "v0.35.0", "reported": None, "status": "unavailable"}
    assert len(connections) == 1
    assert connections[0][0] == ("127.0.0.1", 43123)
    assert 0 < connections[0][1] <= 1.0
    assert len(connection.sent) == 1
    assert connection.sent[0].startswith(b"GET /api/version HTTP/1.1\r\nHost: 127.0.0.1:43123\r\n")
    assert "private" not in json.dumps(result)


def test_ollama_snapshot_uses_one_total_deadline_for_slow_reads(tmp_path, monkeypatch):
    import flinttrade_core.ollama_runtime as ollama

    runtime = _bare_ollama_runtime(tmp_path)
    now = [100.0]

    def tick():
        now[0] += 0.3

    connection = _ProbeSocket([
        b"HTTP/1.1 200 OK\r\nContent-Length: 999\r\n\r\n{",
        b'"version":', b'"0.35.0"}',
    ], tick=tick)
    monkeypatch.setattr(ollama.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(ollama.socket, "create_connection", lambda *args, **kwargs: connection)
    assert runtime.version_snapshot()["status"] == "not_responding"
    assert now[0] <= 101.0
    assert all(0 < timeout <= 0.75 for timeout in connection.timeouts)
    assert connection.timeouts[-1] < connection.timeouts[0]


@pytest.mark.parametrize("configured_runtime", [False, True])
def test_ollama_versions_route_is_authenticated_uncached_and_observational(tmp_path, monkeypatch, configured_runtime):
    import copy
    import flinttrade_core.ollama_runtime as ollama
    from flinttrade_core.health_routes import health_bp
    from flinttrade_core.public_routes import is_public_route

    app = Flask(__name__)
    app.register_blueprint(health_bp)
    runtime = _bare_ollama_runtime(tmp_path)
    before = copy.deepcopy(vars(runtime))
    if configured_runtime:
        app.config["OLLAMA_RUNTIME"] = runtime
    body = b'{"version":"0.35.0"}'
    connection = _ProbeSocket([
        b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body,
    ])

    def connect(address, *, timeout):
        assert configured_runtime, "An absent runtime must not be probed"
        assert address == ("127.0.0.1", 43123)
        assert 0 < timeout <= 0.75
        return connection

    monkeypatch.setattr(ollama.socket, "create_connection", connect)
    response = app.test_client().get("/api/v1/versions/ollama")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == (
        {"configured": "v0.35.0", "reported": "0.35.0", "status": "reported"}
        if configured_runtime else {"configured": None, "reported": None, "status": "unavailable"}
    )
    assert not is_public_route("GET", "/api/v1/versions/ollama")
    assert not is_public_route("HEAD", "/api/v1/versions/ollama")
    assert len(connection.sent) == (1 if configured_runtime else 0)
    if configured_runtime:
        assert connection.sent[0].startswith(b"GET /api/version HTTP/1.1\r\n")
    assert vars(runtime) == before


def test_backend_versions_route_prevents_caching(tmp_path, monkeypatch):
    mod = _inventory_module()
    from flinttrade_core.health_routes import health_bp

    monkeypatch.setattr(mod, "discover_source_root", lambda: tmp_path)
    _install_metadata(monkeypatch, tmp_path, missing=PACKAGES + BROKERS)
    app = Flask(__name__)
    app.register_blueprint(health_bp)
    def forbidden(*args, **kwargs):
        raise AssertionError("Backend metadata must never access the network")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    response = app.test_client().get("/api/v1/versions")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"


def test_packaged_layout_route_keeps_installed_metadata_without_checkout_pins(tmp_path, monkeypatch):
    """An installed wheel must not treat arbitrary nearby lockfiles as its repo."""
    import flinttrade_core.source_root as source_root
    from flinttrade_core.health_routes import health_bp

    wheel_package = tmp_path / "lib" / "python3.12" / "site-packages" / "flinttrade_core"
    wheel_package.mkdir(parents=True)
    module_file = wheel_package / "source_root.py"
    module_file.write_text("# installed package layout\n", encoding="utf-8")
    # These files exist, but the surrounding directory has no validated source
    # checkout contract. Neither their presence nor cwd makes them trusted pins.
    _write_manifests(tmp_path)
    _install_metadata(monkeypatch, tmp_path)
    monkeypatch.setattr(source_root, "__file__", str(module_file))
    monkeypatch.delenv("FLINTTRADE_SOURCE_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    app = Flask(__name__)
    app.register_blueprint(health_bp)
    response = app.test_client().get("/api/v1/versions")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    result = response.get_json()
    assert all(row["installed"] == "4.5.6" for row in result["packages"] + result["brokers"])
    assert all(row["configured"] is None for row in result["packages"] + result["brokers"])
    assert all(row["source_commit"] is None for row in result["brokers"])
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize("body", [
    b'{"version": 7}', b'{"version": true}', b'{"version": null}', b'{}',
    b'[]', b'null', b'not-json', b'{"version": "private-host.test"}', b'{"version": ""}',
])
def test_successful_ollama_response_without_a_string_version_is_unavailable(tmp_path, monkeypatch, body):
    import flinttrade_core.ollama_runtime as ollama

    runtime = _bare_ollama_runtime(tmp_path)
    connection = _ProbeSocket([
        b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body,
    ])
    monkeypatch.setattr(ollama.socket, "create_connection", lambda *args, **kwargs: connection)
    assert runtime.version_snapshot() == {"configured": "v0.35.0", "reported": None, "status": "unavailable"}
    assert len(connection.sent) == 1
    assert connection.sent[0].startswith(b"GET /api/version HTTP/1.1\r\n")


@pytest.mark.parametrize("exception", [ConnectionRefusedError("private endpoint"), TimeoutError("private endpoint")])
def test_ollama_transport_refusal_and_timeout_are_not_responding(tmp_path, monkeypatch, exception):
    import flinttrade_core.ollama_runtime as ollama

    runtime = _bare_ollama_runtime(tmp_path)

    def refuse(address, *, timeout):
        assert address == ("127.0.0.1", 43123)
        assert 0 < timeout <= 0.75
        raise exception

    monkeypatch.setattr(ollama.socket, "create_connection", refuse)
    assert runtime.version_snapshot() == {"configured": "v0.35.0", "reported": None, "status": "not_responding"}


def test_ollama_raw_response_reports_only_a_sanitised_string_version(tmp_path, monkeypatch):
    import flinttrade_core.ollama_runtime as ollama

    runtime = _bare_ollama_runtime(tmp_path)
    body = b'{"version":"0.34.0","hostname":"private-host","path":"/private/path"}'
    connection = _ProbeSocket([
        b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body,
    ])
    monkeypatch.setattr(ollama.socket, "create_connection", lambda *args, **kwargs: connection)
    assert runtime.version_snapshot() == {"configured": "v0.35.0", "reported": "0.34.0", "status": "reported"}


@pytest.mark.parametrize("release_version, expected_release", [
    ("3.0.7", "3.0.7"),
    ("file:///private/release", None),
])
def test_broker_runtime_and_release_versions_remain_separate(tmp_path, monkeypatch, release_version, expected_release):
    mod = _inventory_module()
    _install_metadata(
        monkeypatch, tmp_path,
        versions={"kotakneoapi": "3.0.8"},
        direct_url=json.dumps({"vcs_info": {"vcs": "git", "commit_id": INSTALLED_COMMIT}}),
    )
    (tmp_path / "brokers.lock").write_text(
        '[[broker]]\nname = "kotakneoapi"\nversion = "3.0.8"\n'
        f'release_version = "{release_version}"\nsource_commit = "{CONFIGURED_COMMIT}"\n',
        encoding="utf-8",
    )
    result = mod.build_version_inventory(source_root=tmp_path)
    assert _by_name(result["brokers"])["kotakneoapi"] == {
        "name": "kotakneoapi",
        "installed": "3.0.8",
        "configured": "3.0.8",
        "release_version": expected_release,
        "source_commit": CONFIGURED_COMMIT,
        "installed_commit": INSTALLED_COMMIT,
    }
    assert "release_version" not in _by_name(result["brokers"])["dhanhq"]
    assert "private" not in json.dumps(result)
