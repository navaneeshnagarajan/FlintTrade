# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — freeze the FlintTrade backend into a desktop sidecar.

Produces a single self-contained executable (``flinttrade-backend``) that the
Tauri desktop shell ships as a bundled sidecar and launches on startup. The
binary embeds:

* every ``flinttrade_*`` package (collected whole, because the codebase
  lazy-imports submodules inside functions — a pattern PyInstaller's static
  analysis cannot follow on its own), and
* the built React terminal (``frontend/``), which the backend serves on its
  loopback port.

Heavy *optional* ML/automation dependencies (numba, TA-Lib, chromadb,
python-telegram-bot, plotly, matplotlib, …) are deliberately left out. The
serving path never imports them at module load; the blueprints that expose
those features lazy-import and degrade gracefully when the dependency is
absent. Keeping them out of the freeze is what makes the binary small enough
to ship and robust enough to always boot.

Invoked indirectly via ``packaging/build-backend.sh`` — that script sets the
working directory to the repo root and runs:

    pyinstaller packaging/flinttrade-backend.spec --noconfirm --clean
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

# ---------------------------------------------------------------------------
# Repo layout — ``SPECPATH`` is the directory holding this spec (``packaging/``);
# the repo root is its parent. Deriving from SPECPATH (rather than the CWD)
# keeps path resolution stable regardless of where PyInstaller is invoked.
# ---------------------------------------------------------------------------
REPO_ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - SPECPATH injected by PyInstaller
ENTRY_SCRIPT = str(Path(SPECPATH) / "desktop_backend.py")  # noqa: F821

# Source roots for every workspace Python package, mirroring the sys.path wiring
# in flinttrade_core.app. PyInstaller needs these on its analysis path so the
# flinttrade_* packages resolve at freeze time.
PACKAGE_SRC_DIRS = [
    "packages/core/core/src",
    "packages/core/data/src",
    "packages/core/historical/src",
    "packages/core/indicators/src",
    "packages/core/ticks/python",
    "packages/services/engine/src",
    "packages/services/screener/src",
    "packages/services/backtest/src",
    "packages/services/ai/src",
    "packages/services/ditto/src",
    "packages/services/automation/src",
    "packages/services/journal/src",
    "packages/integrations/gateway/src",
    "packages/integrations/webhooks/src",
]
pathex = [str(REPO_ROOT / p) for p in PACKAGE_SRC_DIRS]
for p in pathex:
    if p not in sys.path:
        sys.path.insert(0, p)

# The first-party packages that must be collected whole (submodules + any
# package data). Missing optional packages are skipped rather than failing the
# build, so a stripped checkout still produces a working core binary.
FLINTTRADE_PACKAGES = [
    "flinttrade_core",
    "flinttrade_data",
    "flinttrade_historical",
    "flinttrade_indicators",
    "flinttrade_engine",
    "flinttrade_screener",
    "flinttrade_backtest",
    "flinttrade_ai",
    "flinttrade_ditto",
    "flinttrade_automation",
    "flinttrade_journal",
    "flinttrade_gateway",
    "flinttrade_webhooks",
]

# Third-party packages whose submodules are reached via lazy/dynamic imports
# and so are invisible to PyInstaller's static analysis. waitress + flask_limiter
# in particular load strategy/storage backends by string name.
THIRD_PARTY_COLLECT = [
    "waitress",
    "flask",
    "flask_cors",
    "flask_limiter",
    "limits",
    "structlog",
    "sentry_sdk",
    "jwt",
    "argon2",
    "pyotp",
    "qrcode",
]

hiddenimports: list[str] = []
datas: list[tuple[str, str]] = []
binaries: list[tuple[str, str]] = []


def _safe_collect_all(name: str) -> None:
    """collect_all(name), tolerating packages absent from this checkout."""
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(name)
    except Exception as exc:  # noqa: BLE001 - log + skip, never fail the build
        print(f"[spec] skipping {name!r}: {exc}")
        return
    datas.extend(pkg_datas)
    binaries.extend(pkg_binaries)
    hiddenimports.extend(pkg_hidden)


for _pkg in FLINTTRADE_PACKAGES:
    _safe_collect_all(_pkg)

for _pkg in THIRD_PARTY_COLLECT:
    try:
        hiddenimports.extend(collect_submodules(_pkg))
    except Exception as exc:  # noqa: BLE001
        print(f"[spec] submodule scan skipped for {_pkg!r}: {exc}")

# duckdb ships a compiled extension; collect its data + binaries explicitly so
# the native lib travels with the freeze.
_safe_collect_all("duckdb")

# ---------------------------------------------------------------------------
# Embed the built React terminal. build-backend.sh guarantees the dist exists.
# It lands under ``frontend/`` in the bundle; flinttrade_core.app resolves it
# from ``sys._MEIPASS/frontend`` when frozen.
# ---------------------------------------------------------------------------
_dist = REPO_ROOT / "packages" / "apps" / "terminal" / "dist"
if (_dist / "index.html").exists():
    datas.append((str(_dist), "frontend"))
else:
    print(f"[spec] WARNING: frontend dist missing at {_dist} — binary will be API-only")

# Heavy / GUI / optional deps to exclude. The serving path reaches all of these
# ONLY through lazy ``import`` statements inside functions (the pervasive
# ``# noqa: PLC0415`` pattern). PyInstaller's bytecode scan would otherwise pull
# them in unconditionally — including multi-gigabyte ML stacks — even though the
# core terminal (trading, charts, screener, positions) never touches them.
# Excluding them keeps the installer to a few hundred MB; the AI/RAG and ML
# signal features that use them surface a clear "not available in the desktop
# build" error at call time instead of bloating every install.
#
# NB: ``scipy`` is deliberately NOT excluded — ``portfolio_optimiser`` imports
# it at module load, so the backtest blueprint needs it present to register.
EXCLUDES = [
    # GUI toolkits — never used by a headless loopback server.
    "tkinter",
    "matplotlib",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    # Dev / notebook / test tooling.
    "IPython",
    "ipykernel",
    "notebook",
    "jupyter",
    "pytest",
    # Heavy ML / DL stacks (lazy-only; AI-RAG + ML-signal features).
    "numba",
    "llvmlite",
    "chromadb",
    "onnxruntime",
    "torch",
    "torchvision",
    "tensorflow",
    "sklearn",
    "scikit_learn",
    "transformers",
    "sentence_transformers",
    # Charting / backtest extras reached lazily.
    "plotly",
    "vectorbt",
    # Telegram bot (automation loop — not started by the desktop sidecar).
    "telegram",
    # Kotak Neo SDK: licence is operator-cleared for personal-use self-hosting
    # only (LicenseRef-operator-cleared-broker-sdk, no upstream LICENSE file) —
    # bundling it in published installers would redistribute all-rights-reserved
    # code. The adapter already fails closed to dormant when the SDK is missing,
    # and desktop operators can install it locally under their own clearance.
    # dhanhq / upstox-python-sdk / growwapi are MIT and stay bundled.
    "neo_api_client",
]

block_cipher = None

a = Analysis(
    [ENTRY_SCRIPT],
    pathex=pathex,
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="flinttrade-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,            # headless server — no GUI; stdout carries the handshake
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,        # native arch; cross-arch handled per-runner in CI
    codesign_identity=None,  # signing happens on the Tauri bundle, not the sidecar
    entitlements_file=None,
)
