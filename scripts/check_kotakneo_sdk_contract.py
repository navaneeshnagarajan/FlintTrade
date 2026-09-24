#!/usr/bin/env python3
"""Verify FlintTrade against the exact Kotak Neo v3 main and release commits.

The gate builds one disposable environment per immutable upstream revision. It
installs only locked dependencies before the selected Git SDK, installs the
four FlintTrade packages needed by the adapter without dependency resolution,
then executes an offline import/API probe. No broker credentials are read and
no broker endpoint is contacted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]
IS_WINDOWS = os.name == "nt"
_KOTAK_NAME = "kotakneoapi"
_KOTAK_HOMEPAGE = "https://github.com/Kotak-Neo/kotak-neo-python"
_FULL_GIT_HASH = re.compile(r"[0-9a-f]{40}")


class ContractError(RuntimeError):
    """Raised when provenance, compatibility, or migration evidence is incomplete."""


@dataclass(frozen=True)
class ContractConfig:
    """Authoritative dual-track pins loaded from ``brokers.lock``."""

    repo_url: str
    version: str
    runtime_main_commit: str
    release_tag: str
    release_commit: str


def load_contract_config(repo: Path = REPO) -> ContractConfig:
    """Load and validate the single Kotak Neo attestation record."""

    lock_path = repo / "brokers.lock"
    try:
        data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ContractError(f"cannot read authoritative broker lock: {lock_path}") from exc
    broker_rows = data.get("broker")
    if not isinstance(broker_rows, list) or not all(isinstance(entry, dict) for entry in broker_rows):
        raise ContractError("brokers.lock broker inventory is malformed")
    entries = [entry for entry in broker_rows if entry.get("name") == _KOTAK_NAME]
    if len(entries) != 1:
        raise ContractError("brokers.lock must contain exactly one kotakneoapi record")
    entry = entries[0]
    homepage = entry.get("homepage")
    version = entry.get("version")
    runtime_main_commit = entry.get("source_commit")
    release_tag = entry.get("release_tag")
    release_commit = entry.get("release_commit")
    if homepage != _KOTAK_HOMEPAGE:
        raise ContractError("brokers.lock Kotak Neo homepage is not the official upstream")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ContractError("brokers.lock Kotak Neo version is malformed")
    if release_tag != f"v{version}":
        raise ContractError("brokers.lock Kotak Neo release tag does not match its version")
    for label, value in (
        ("runtime main commit", runtime_main_commit),
        ("release commit", release_commit),
    ):
        if not isinstance(value, str) or _FULL_GIT_HASH.fullmatch(value) is None:
            raise ContractError(f"brokers.lock Kotak Neo {label} is not a full Git hash")
    return ContractConfig(
        repo_url=f"{homepage}.git",
        version=version,
        runtime_main_commit=runtime_main_commit,
        release_tag=release_tag,
        release_commit=release_commit,
    )


@dataclass(frozen=True)
class SdkTrack:
    """One immutable upstream contract target."""

    name: str
    revision: str
    version: str
    repo_url: str
    release_tag: str | None = None


def build_tracks(config: ContractConfig) -> tuple[SdkTrack, SdkTrack]:
    """Build the runtime-main and stable-release tracks from one lock record."""

    return (
        SdkTrack("runtime-main", config.runtime_main_commit, config.version, config.repo_url),
        SdkTrack(
            f"release-{config.release_tag}",
            config.release_commit,
            config.version,
            config.repo_url,
            config.release_tag,
        ),
    )


# Compatibility aliases for the unit-test surface. These values are derived
# from the authoritative lock rather than maintained as a second pin set.
_DEFAULT_CONFIG = load_contract_config()
KOTAK_REPO = _DEFAULT_CONFIG.repo_url
KOTAK_VERSION = _DEFAULT_CONFIG.version
RUNTIME_MAIN_COMMIT = _DEFAULT_CONFIG.runtime_main_commit
RELEASE_TAG = _DEFAULT_CONFIG.release_tag
RELEASE_COMMIT = _DEFAULT_CONFIG.release_commit
TRACKS = build_tracks(_DEFAULT_CONFIG)

SCANNER_TARGETS = (
    "packages/integrations/gateway/src/flinttrade_gateway/brokers/kotakneo.py",
    "packages/integrations/gateway/src/flinttrade_gateway/brokers/kotakneo_sdk.py",
    "packages/integrations/gateway/src/flinttrade_gateway/brokers/kotakneo_streaming.py",
    "packages/integrations/gateway/src/flinttrade_gateway/native_login.py",
    "packages/integrations/gateway/src/flinttrade_gateway/monday_read_smoke.py",
    "scripts/probe_native_broker_live.py",
    "scripts/probe_kotakneo_live.py",
)

Run = Callable[..., subprocess.CompletedProcess[str]]


def host_python(repo: Path = REPO) -> Path:
    """Return the repository-managed interpreter required by the local gate."""

    candidate = repo / ".venv" / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
    if not candidate.is_file():
        raise ContractError(f"repository-managed Python is missing: {candidate}")
    return candidate


def environment_python(environment: Path) -> Path:
    """Return the interpreter path inside a disposable uv environment."""

    return environment / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


_PASSTHROUGH_ENVIRONMENT = frozenset(
    {
        "ALL_PROXY",
        "COMSPEC",
        "CURL_CA_BUNDLE",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "LANG",
        "LC_ALL",
        "NO_PROXY",
        "PATH",
        "PATHEXT",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "SYSTEMROOT",
        "WINDIR",
        "all_proxy",
        "https_proxy",
        "http_proxy",
        "no_proxy",
    }
)


def build_subprocess_environment(
    workspace: Path,
    *,
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a minimal child environment with isolated home/cache paths.

    Installation needs the host PATH, platform runtime variables, certificate
    paths, and (where configured) a network proxy. Broker, cloud, API, Python,
    Git, and package-index credentials are deliberately not inherited.
    """

    parent = os.environ if source is None else source
    environment = {
        key: value
        for key, value in parent.items()
        if key in _PASSTHROUGH_ENVIRONMENT and isinstance(value, str)
    }
    environment.setdefault("PATH", os.defpath)
    home = workspace / "home"
    cache = workspace / "cache"
    temporary = workspace / "tmp"
    for path in (home, cache, temporary):
        path.mkdir(parents=True, exist_ok=True)
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "HOME": str(home),
            "PIP_CONFIG_FILE": os.devnull,
            "PYTHONNOUSERSITE": "1",
            "PYTHONUTF8": "1",
            "TEMP": str(temporary),
            "TMP": str(temporary),
            "TMPDIR": str(temporary),
            "USERPROFILE": str(home),
            "UV_CACHE_DIR": str(cache / "uv"),
            "XDG_CACHE_HOME": str(cache / "xdg"),
        }
    )
    return environment


def build_export_command(requirements: Path, *, repo: Path = REPO) -> list[str]:
    """Build the frozen export command for the gateway's non-workspace base."""

    del repo  # The caller supplies the repository as the command cwd.
    return [
        "uv",
        "export",
        "--frozen",
        "--package",
        "flinttrade-gateway",
        "--no-dev",
        "--no-emit-workspace",
        "--no-emit-package",
        "kotakneoapi",
        "--output-file",
        str(requirements),
    ]


def build_track_commands(
    track: SdkTrack,
    environment: Path,
    requirements: Path,
    *,
    repo: Path = REPO,
) -> list[list[str]]:
    """Build the ordered installation/check commands for one SDK track."""

    python = environment_python(environment)
    editable_paths = (
        repo / "packages/core/core",
        repo / "packages/core/data",
        repo / "packages/services/engine",
        repo / "packages/integrations/gateway",
    )
    editable_args: list[str] = []
    for path in editable_paths:
        editable_args.extend(("--editable", str(path)))
    return [
        ["uv", "venv", str(environment), "--python", str(host_python(repo))],
        ["uv", "pip", "install", "--python", str(python), "--require-hashes", "-r", str(requirements)],
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--require-hashes",
            "--only-binary=:all:",
            "--no-deps",
            "-r",
            str(repo / "broker-sdk-build.lock"),
        ],
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--no-build-isolation",
            "--no-deps",
            f"git+{track.repo_url}@{track.revision}",
        ],
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--no-deps",
            *editable_args,
        ],
        ["uv", "pip", "check", "--python", str(python)],
    ]


def _normalise_distribution(name: object) -> str:
    return re.sub(r"[-_.]+", "-", str(name).strip().lower())


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"Kotak Neo {label} is missing or malformed")
    return value


def validate_probe_result(result: Mapping[str, Any], track: SdkTrack) -> None:
    """Validate exact distribution, namespace, import, and offline probe evidence."""

    distributions = _require_mapping(result.get("distributions"), "distribution inventory")
    if "neo-api-client" in distributions:
        raise ContractError("forbidden neo-api-client v2 distribution is installed")
    installed = _require_mapping(distributions.get("kotakneoapi"), "kotakneoapi distribution")
    if installed.get("version") != track.version:
        raise ContractError(f"Kotak Neo version must be exactly {track.version}")

    counts = result.get("distribution_counts")
    if not isinstance(counts, Mapping) or counts.get("kotakneoapi") != 1:
        raise ContractError("kotakneoapi distribution inventory is ambiguous")

    owners = result.get("namespace_owners")
    if owners != ["kotakneoapi"]:
        raise ContractError("neo_api_client namespace must have exactly one kotakneoapi owner")

    direct = _require_mapping(installed.get("direct_url"), "Git provenance")
    raw_url = direct.get("url")
    try:
        parsed = urlsplit(raw_url if isinstance(raw_url, str) else "")
        exact_origin = (
            parsed.scheme == "https"
            and parsed.hostname == "github.com"
            and f"{parsed.scheme}://{parsed.hostname}{parsed.path}" == track.repo_url
            and parsed.username is None
            and parsed.password is None
            and parsed.port is None
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError as exc:
        raise ContractError("Kotak Neo Git origin is malformed") from exc
    if not exact_origin:
        raise ContractError("Kotak Neo Git origin must be the exact HTTPS upstream")

    vcs = _require_mapping(direct.get("vcs_info"), "VCS provenance")
    commit = vcs.get("commit_id")
    if vcs.get("vcs") != "git" or not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ContractError("Kotak Neo provenance must contain a full Git commit")
    if commit != track.revision:
        raise ContractError(f"Kotak Neo commit does not match {track.name}")
    if vcs.get("requested_revision") != track.revision:
        raise ContractError(f"Kotak Neo requested revision does not match {track.name}")

    module_path = result.get("module_path")
    environment_root = result.get("environment_root")
    if not isinstance(module_path, str) or not isinstance(environment_root, str):
        raise ContractError("target-environment import evidence is missing")
    try:
        imported_from_environment = Path(module_path).resolve().is_relative_to(Path(environment_root).resolve())
    except (OSError, RuntimeError, ValueError):
        imported_from_environment = False
    if not imported_from_environment:
        raise ContractError("neo_api_client was not imported from the target environment")

    cwd_files = result.get("cwd_files")
    if cwd_files != []:
        raise ContractError("Kotak Neo SDK created a log or another file in the probe working directory")
    if result.get("contract_ok") is not True:
        raise ContractError("Kotak Neo offline API contract probe did not complete")


def parse_probe_output(stdout: str) -> dict[str, Any]:
    """Parse a probe's single JSON object, rejecting banners or partial output."""

    try:
        value = json.loads(stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ContractError("Kotak Neo probe did not return one JSON object") from exc
    if not isinstance(value, dict):
        raise ContractError("Kotak Neo probe JSON must be an object")
    return value


_PROBE_SCRIPT = r"""
from __future__ import annotations

import importlib.metadata as md
import inspect
import json
import os
import re
import socket
import sys
from pathlib import Path


def denied(*_args, **_kwargs):
    raise AssertionError("network access is forbidden during the Kotak Neo contract probe")


def deny_network_and_process(event, _args):
    if event.startswith("socket.") or event in {
        "subprocess.Popen",
        "os.system",
        "os.posix_spawn",
        "os.spawn",
        "os.exec",
        "os.fork",
        "os.forkpty",
        "pty.spawn",
    }:
        denied()


sys.addaudithook(deny_network_and_process)
socket.socket.connect = denied
socket.socket.connect_ex = denied
socket.create_connection = denied

# Fail closed if this interpreter does not emit the socket-construction audit
# event. This also proves the guard before any third-party module is imported.
try:
    socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
except AssertionError:
    pass
else:
    raise AssertionError("network audit guard is not active")

import httpx
import neo_api_client
import neo_api_client.neo_api as neo_module
from neo_api_client import NeoAPI
from neo_api_client.websocket.feed import (
    SFeedIndex,
    SFeedScrip,
    SFeedScripLite,
    SFeedWebSocket,
    WsToken,
)
from neo_api_client.websocket.orderfeed import OrderFeedWebSocket, OrderUpdate, PositionUpdate

from flinttrade_gateway.brokers import kotakneo_streaming
from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession, validate_read_envelope


def canonical(name):
    return re.sub(r"[-_.]+", "-", str(name).strip().lower())


distributions = {}
counts = {}
owners = []
for distribution in md.distributions():
    name = canonical(distribution.metadata.get("Name", ""))
    if name in {"kotakneoapi", "neo-api-client"}:
        direct_text = distribution.read_text("direct_url.json")
        try:
            direct = json.loads(direct_text) if direct_text else None
        except (TypeError, ValueError):
            direct = None
        distributions[name] = {"version": distribution.version, "direct_url": direct}
        counts[name] = counts.get(name, 0) + 1
    top_level = (distribution.read_text("top_level.txt") or "").splitlines()
    record_owns = any(
        str(file).replace("\\", "/").split("/")[0] == "neo_api_client"
        for file in (distribution.files or ())
    )
    if "neo_api_client" in top_level or record_owns:
        owners.append(name)

expected = {
    "totp_login": ("mobile_number", "ucc", "totp"),
    "totp_validate": ("mpin",),
    "place_order": (
        "exchange_segment", "product", "price", "order_type", "quantity", "validity",
        "trading_symbol", "transaction_type", "amo", "disclosed_quantity", "trigger_price", "tag",
    ),
    "modify_order": (
        "order_id", "price", "order_type", "quantity", "validity", "trigger_price",
        "disclosed_quantity", "amo",
    ),
    "cancel_order": ("order_id", "amo", "isVerify"),
    "margin_required": (
        "exchange_segment", "price", "order_type", "product", "quantity", "instrument_token",
        "transaction_type", "trigger_price", "broker_name", "branch_id", "stop_loss_type",
        "stop_loss_value", "square_off_type", "square_off_value", "trailing_stop_loss",
        "trailing_sl_value",
    ),
    "create_websocket": ("url", "kwargs"),
    "create_order_feed": ("kwargs",),
    "whatsmyip": (),
    "order_report": ("order_id",),
    "order_history": ("order_id",),
    "trade_report": (),
    "positions": (),
    "holdings": (),
    "limits": (),
    "quotes": ("instrument_tokens", "quote_type"),
    "scrip_master": ("exchange_segment",),
    "search_scrip": (
        "exchange_segment", "symbol", "expiry", "option_type", "strike_price", "ignore_50multiple",
    ),
    "expiries": ("exchange", "underlying", "instrument_type"),
    "option_chain": ("exchange", "underlying", "expiry", "instrument_type", "count"),
    "historical_data": ("neosymbol", "interval", "from_date", "to_date"),
    "logout": (),
}
for name, parameters in expected.items():
    assert tuple(inspect.signature(getattr(NeoAPI, name)).parameters)[1:] == parameters, name
assert tuple(inspect.signature(NeoAPI).parameters) == (
    "consumer_key", "environment", "access_token", "neo_fin_key", "transport", "limits", "http2", "timeout",
)
assert tuple(inspect.signature(WsToken).parameters) == ("exchange_segment", "instrument_token")

feed_signatures = {
    SFeedWebSocket: {
        "connect": ("self",),
        "close": ("self",),
        "subscribe_scrips": ("self", "tokens"),
        "unsubscribe_scrips": ("self", "tokens"),
        "subscribe_depth": ("self", "tokens"),
        "unsubscribe_depth": ("self", "tokens"),
        "subscribe_index": ("self", "tokens"),
        "unsubscribe_index": ("self", "tokens"),
        "__aiter__": ("self",),
    },
    OrderFeedWebSocket: {
        "connect": ("self",),
        "close": ("self",),
        "__aiter__": ("self",),
    },
}
for feed_class, methods in feed_signatures.items():
    for name, parameters in methods.items():
        assert tuple(inspect.signature(getattr(feed_class, name)).parameters) == parameters, (
            feed_class.__name__, name
        )

for removed in ("NeoWebSocket", "HSWebSocket", "HSIWebSocket"):
    assert not hasattr(neo_api_client, removed), removed
for method, args in (
    ("subscribe", ([{"instrument_token": "11536", "exchange_segment": "nse_cm"}],)),
    ("un_subscribe", ([{"instrument_token": "11536", "exchange_segment": "nse_cm"}],)),
    ("subscribe_to_orderfeed", ()),
):
    instance = NeoAPI.__new__(NeoAPI)
    try:
        getattr(instance, method)(*args)
    except NotImplementedError:
        pass
    else:
        raise AssertionError(f"legacy {method} unexpectedly remains active")


class FakeTotp:
    def __init__(self, _api_client):
        pass

    def totp_login(self, **_kwargs):
        return {"data": {"status": "success", "token": "view", "sid": "view-sid", "ucc": "SYNTHETIC", "kType": "View"}}

    def totp_validate(self, **_kwargs):
        return {"data": {"status": "success", "token": "trade", "sid": "trade-sid", "baseUrl": "https://example.invalid", "kType": "Trade"}}


class FakeOrder:
    def __init__(self, _api_client):
        pass

    def order_placing(self, **_kwargs):
        return {"stat": "Ok", "nOrdNo": "SYNTHETIC"}

    def order_cancelling(self, **_kwargs):
        return {"stat": "Ok", "nOrdNo": "SYNTHETIC"}


class FakeOrders:
    def __init__(self, _api_client):
        pass

    def ordered_books(self):
        return {"stat": "Ok", "stCode": 200, "data": []}


neo_module.TotpAPI = FakeTotp
neo_module.OrderAPI = FakeOrder
neo_module.OrderReportAPI = FakeOrders
neo = NeoAPI(
    consumer_key="synthetic",
    environment="prod",
    access_token=None,
    transport=httpx.MockTransport(lambda _request: denied()),
)
view = neo.totp_login(mobile_number="+910000000000", ucc="SYNTHETIC", totp="000000")
trade = neo.totp_validate(mpin="000000")
assert view["data"]["kType"] == "View"
assert trade["data"]["kType"] == "Trade"
neo.configuration.edit_token = "synthetic-trade-token"
neo.configuration.edit_sid = "synthetic-trade-sid"
neo.configuration.ucc = "SYNTHETIC"
neo.configuration.base_url = "https://example.invalid"
assert neo.order_report()["data"] == []
assert neo.place_order(
    exchange_segment="nse_cm",
    product="MIS",
    price="0",
    order_type="MKT",
    quantity="1",
    validity="DAY",
    trading_symbol="SYNTHETIC-EQ",
    transaction_type="B",
)["nOrdNo"] == "SYNTHETIC"

token = WsToken("nse_cm", "11536")
assert hash(token)
assert all(inspect.isclass(model) for model in (SFeedScrip, SFeedScripLite, SFeedIndex, OrderUpdate, PositionUpdate))

facade = KotakNeoSdkSession.__new__(KotakNeoSdkSession)
facade._neo = neo
facade._closed = False
market_feed = facade.create_websocket(
    max_reconnect_attempts=0,
    max_connect_retries=0,
    max_subscriptions=3000,
)
order_feed = facade.create_order_feed(
    max_reconnect_attempts=0,
    max_connect_retries=0,
)
assert isinstance(market_feed, SFeedWebSocket)
assert market_feed.max_reconnect_attempts == 0
assert market_feed.max_connect_retries == 0
assert market_feed.max_subscriptions == 3000
assert isinstance(order_feed, OrderFeedWebSocket)
assert order_feed.max_reconnect_attempts == 0
assert order_feed.max_connect_retries == 0
for method in (
    "connect", "close", "subscribe_scrips", "unsubscribe_scrips", "subscribe_depth",
    "unsubscribe_depth", "subscribe_index", "unsubscribe_index",
):
    assert callable(getattr(market_feed, method))
assert callable(facade.logout_sdk)
assert callable(facade.close_rest)
for legacy in ("subscribe", "un_subscribe", "subscribe_to_orderfeed"):
    assert not hasattr(KotakNeoSdkSession, legacy), legacy

main_envelope = {"stat": "Ok", "stCode": 200, "data": [], "rateLimit": {"remaining": 2}}
release_envelope = {"data": {
    "common_data": {
        "mktLot": "65", "multiplier": "1", "unlSymbol": "NIFTY",
        "exSeg": "nse_fo", "expiryDt": "2026-09-24",
    },
    "call": [{"instrument": {"neoSymbol": "nse_fo|71472"}}],
    "put": [],
}}
assert validate_read_envelope(main_envelope, operation="order_report") is main_envelope
assert validate_read_envelope(release_envelope, operation="option_chain") is release_envelope

# Importing the runtime module above is part of the contract. Keep a concrete
# reference so optimisers and static rewrites cannot erase it as unused.
assert kotakneo_streaming.__name__.endswith("kotakneo_streaming")
neo.api_client.rest_client.close()

cwd = Path.cwd()
cwd_files = sorted(str(path.relative_to(cwd)) for path in cwd.rglob("*") if path.is_file())
print(json.dumps({
    "distributions": distributions,
    "distribution_counts": counts,
    "namespace_owners": sorted(owners),
    "module_path": str(Path(neo_api_client.__file__).resolve()),
    "environment_root": str(Path(os.environ["KOTAK_CONTRACT_ENV"]).resolve()),
    "cwd_files": cwd_files,
    "contract_ok": True,
}, sort_keys=True))
"""


def _run_checked(
    args: Sequence[str | Path],
    *,
    run: Run,
    cwd: Path,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = list(map(str, args))
    result = run(command, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "command failed without output").strip()
        raise ContractError(f"command failed ({' '.join(command[:4])}): {detail}")
    return result


def resolve_scanner_targets(repo: Path = REPO) -> list[Path]:
    """Resolve exactly the seven migration-scan inputs and require each file."""

    if len(SCANNER_TARGETS) != 7 or len(set(SCANNER_TARGETS)) != 7:
        raise ContractError("Kotak Neo migration scanner target inventory must contain exactly seven unique paths")
    targets = [repo / relative for relative in SCANNER_TARGETS]
    missing = [str(path) for path in targets if not path.is_file()]
    if missing:
        raise ContractError(f"Kotak Neo migration scanner target is missing: {', '.join(missing)}")
    return targets


def materialise_scanner(
    workspace: Path,
    *,
    config: ContractConfig = _DEFAULT_CONFIG,
    run: Run = subprocess.run,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Read the official migration scanner from the exact runtime commit."""

    bare = workspace / "kotak-upstream.git"
    _run_checked(["git", "init", "--bare", bare], run=run, cwd=workspace, env=env)
    _run_checked(
        [
            "git",
            f"--git-dir={bare}",
            "fetch",
            "--depth=1",
            config.repo_url,
            config.runtime_main_commit,
        ],
        run=run,
        cwd=workspace,
        env=env,
    )
    shown = _run_checked(
        [
            "git",
            f"--git-dir={bare}",
            "show",
            f"{config.runtime_main_commit}:docs/scripts/migrate_from_v2.py",
        ],
        run=run,
        cwd=workspace,
        env=env,
    )
    scanner = workspace / "migrate_from_v2.py"
    scanner.write_text(shown.stdout, encoding="utf-8")
    return scanner


_SCANNER_SUMMARY = re.compile(
    r"(?m)^(?P<errors>\d+) error\(s\), (?P<warnings>\d+) warning\(s\) across (?P<files>\d+) file\(s\)\.$"
)


def validate_scanner_result(result: subprocess.CompletedProcess[str], *, expected_files: int) -> None:
    """Require a parsed zero-error/zero-warning summary for every target."""

    matches = list(_SCANNER_SUMMARY.finditer(result.stdout or ""))
    if len(matches) != 1:
        raise ContractError("official Kotak Neo migration scanner must emit exactly one auditable summary")
    match = matches[0]
    errors = int(match.group("errors"))
    warnings = int(match.group("warnings"))
    files = int(match.group("files"))
    if files != expected_files:
        raise ContractError(f"official Kotak Neo migration scanner covered {files}, expected {expected_files}")
    if errors or warnings:
        raise ContractError(f"official Kotak Neo migration scanner found {errors} error(s) and {warnings} warning(s)")
    if result.returncode != 0:
        raise ContractError(f"official Kotak Neo migration scanner exited {result.returncode}")


def _probe_track(
    track: SdkTrack,
    environment: Path,
    workspace: Path,
    *,
    run: Run,
    repo: Path,
    base_env: Mapping[str, str],
) -> None:
    requirements = workspace / "base-requirements.txt"
    for command in build_track_commands(track, environment, requirements, repo=repo):
        _run_checked(command, run=run, cwd=workspace, env=base_env)

    probe_cwd = workspace / f"probe-{track.name}"
    probe_cwd.mkdir()
    probe_env = build_subprocess_environment(probe_cwd / "process", source=base_env)
    probe_env.update(
        {
            "KOTAK_CONTRACT_ENV": str(environment),
            "NEO_LOG_FILE_ENABLED": "false",
            "NEO_LOG_LEVEL": "CRITICAL",
            "NO_PROXY": "*",
            "no_proxy": "*",
        }
    )
    result = _run_checked(
        [environment_python(environment), "-I", "-c", _PROBE_SCRIPT],
        run=run,
        cwd=probe_cwd,
        env=probe_env,
    )
    validate_probe_result(parse_probe_output(result.stdout), track)


def run_contract(
    *,
    repo: Path = REPO,
    run: Run = subprocess.run,
    temporary_parent: Path | None = None,
) -> ContractConfig:
    """Run both disposable SDK tracks and the exact official migration scan."""

    config = load_contract_config(repo)
    tracks = build_tracks(config)
    parent = str(temporary_parent) if temporary_parent is not None else None
    with tempfile.TemporaryDirectory(prefix="kotakneo-contract-", dir=parent) as temporary:
        workspace = Path(temporary)
        base_env = build_subprocess_environment(workspace / "process")
        requirements = workspace / "base-requirements.txt"
        _run_checked(
            build_export_command(requirements, repo=repo),
            run=run,
            cwd=repo,
            env=base_env,
        )

        for track in tracks:
            _probe_track(
                track,
                workspace / track.name,
                workspace,
                run=run,
                repo=repo,
                base_env=base_env,
            )

        scanner = materialise_scanner(workspace, config=config, run=run, env=base_env)
        targets = resolve_scanner_targets(repo)
        result = run(
            [str(host_python(repo)), str(scanner), *map(str, targets)],
            cwd=repo,
            env=base_env,
            capture_output=True,
            text=True,
            check=False,
        )
        validate_scanner_result(result, expected_files=len(targets))
    return config


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO, help="FlintTrade checkout to verify")
    args = parser.parse_args(argv)
    try:
        repo = args.repo.resolve()
        config = run_contract(repo=repo)
    except ContractError as exc:
        print(f"Kotak Neo SDK contract: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "Kotak Neo SDK contract: PASS "
        f"(runtime main {config.runtime_main_commit}; "
        f"{config.release_tag} {config.release_commit}; migration scan clean)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
