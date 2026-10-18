"""Source-bound PR runtime selection; never install or choose an ambient Python."""

from __future__ import annotations

import argparse
import errno
import hashlib
import importlib
import importlib.machinery
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def versions() -> dict[str, str]:
    bootstrap = ROOT / "packages/apps/desktop/resources/bootstrap"
    manifest = json.loads((bootstrap / "tool-manifest.json").read_text())
    shell = (bootstrap / "flinttrade-bootstrap.sh").read_text()
    python = re.findall(r"^export UV_PYTHON=(\d+\.\d+\.\d+)$", shell, re.MULTILINE)
    if len(python) != 1:
        raise ValueError("One exact managed bootstrap Python selector required")
    package = json.loads((ROOT / "package.json").read_text())
    pnpm = package["packageManager"].split("@", 1)[1].split("+", 1)[0]
    if pnpm != manifest["pnpm"]["version"]:
        raise ValueError("pnpm bootstrap/packageManager mismatch")
    selected = {
        "python-current": python[0],
        "node-current": manifest["node"]["version"],
        "uv-current": manifest["uv"]["version"],
        "pnpm-current": pnpm,
    }
    if not all(re.fullmatch(r"\d+\.\d+\.\d+", value) for value in selected.values()):
        raise ValueError("Exact stable runtime versions required")
    return selected


def verify(tool: str, expected: str, output: Path | None) -> int:
    if not re.fullmatch(r"\d+(?:\.\d+){0,2}", expected):
        raise ValueError("A numeric version or support-floor prefix is required")
    executable = sys.executable if tool == "python" else shutil.which(tool)
    if executable is None:
        raise RuntimeError("Selected tool is unavailable: " + tool)
    command = (
        [executable, "-I", "-S", "-c", "import platform;print(platform.python_version())"]
        if tool == "python"
        else [executable, "--version"]
    )
    observed = subprocess.check_output(command, text=True).strip()
    uv_release = re.fullmatch(r"uv (\d+\.\d+\.\d+)(?: \([^()\r\n]+\))?", observed) if tool == "uv" else None
    actual = uv_release.group(1) if uv_release else observed.removeprefix("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+", actual):
        raise ValueError("Unrecognised stable tool version: " + observed)
    matches = actual.split(".")[: len(expected.split("."))] == expected.split(".")
    receipt = {"tool": tool, "executable": executable, "actual": actual, "reported": observed, "expected": expected, "matches": matches}
    text = json.dumps(receipt, sort_keys=True)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n")
    print(text, flush=True)
    return 0 if matches else 1


def native_inputs() -> dict:
    crate = ROOT / "packages/core/ticks"
    paths = [crate / name for name in ["Cargo.toml", "Cargo.lock", "pyproject.toml"]]
    paths += sorted((crate / "src").rglob("*.rs"))
    paths += sorted((crate / "python").rglob("*.py"))
    return {"files": {p.relative_to(crate).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
            "uv_lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
            "builder_constraint_sha256": hashlib.sha256((ROOT / "tools/acceptance/native-build.txt").read_bytes()).hexdigest()}


def native_admission(inputs: Path, wheel: Path) -> None:
    """Require the existing qualified boundary before loading extension code."""
    if sys.flags.optimize:
        raise RuntimeError("Python optimisation refused before native acceptance")
    if os.environ.get("HOME") != "/run/test/home":
        raise RuntimeError("Authorised isolated runner required")
    paths = [ROOT / "scripts/ci_runtime.py",
             *[ROOT / "packages/core/ticks" / name for name in native_inputs()["files"]],
             ROOT / "uv.lock", ROOT / "tools/acceptance/native-build.txt",
             ROOT / ".venv/pyvenv.cfg", inputs, wheel]
    for path in paths:
        if not path.resolve().is_relative_to(ROOT):
            raise RuntimeError("Native inputs must belong to the source-only input")
        # Do not truncate or write: permissions alone are not a read-only mount.
        try:
            descriptor = os.open(path, os.O_WRONLY)
        except OSError as error:
            if error.errno != errno.EROFS:
                raise RuntimeError("Read-only native input required") from error
        else:
            os.close(descriptor)
            raise RuntimeError("Read-only native input required")
    spec = importlib.util.spec_from_file_location("native_acceptance_guard", ROOT / "tools/acceptance/guard.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Existing acceptance guard missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.guard()
    if Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
        raise RuntimeError("Native acceptance must use the prepared source environment")


def native(expected: str, inputs: Path, wheel: Path, output: Path | None) -> int:
    if verify("python", expected, None):
        return 1
    if json.loads(inputs.read_text()) != native_inputs():
        raise RuntimeError("Native source changed during build")
    native_admission(inputs, wheel)
    metadata = tomllib.loads((ROOT / "packages/core/ticks/pyproject.toml").read_text())
    name = metadata["tool"]["maturin"]["module-name"]
    package = importlib.import_module(name)
    extension = importlib.import_module(name + "." + name)
    if not isinstance(extension.__loader__, importlib.machinery.ExtensionFileLoader) or extension.__file__ is None or package.__file__ is None:
        raise RuntimeError("An actual native extension loader is required")
    origin = Path(extension.__file__).resolve(strict=True)
    if not origin.is_relative_to(Path(sys.prefix).resolve()) or not any(str(origin).endswith(s) for s in importlib.machinery.EXTENSION_SUFFIXES):
        raise RuntimeError("Native extension must load from the selected environment")
    version = importlib.metadata.version(metadata["project"]["name"])
    if version != metadata["project"]["version"]:
        raise RuntimeError("Native distribution version mismatch")
    with zipfile.ZipFile(wheel) as archive:
        member = name + "/" + origin.name
        if archive.read(member) != origin.read_bytes():
            raise RuntimeError("Imported native bytes differ from the freshly built wheel")
        if archive.read(name + "/__init__.py") != Path(package.__file__).read_bytes():
            raise RuntimeError("Native Python wrapper differs from the freshly built wheel")
    # A real extension call, not merely Cargo tests or an optional import/skip.
    config = package.SpreadConfig(initial_capital=1000.0, fees=0.0)
    config.add_leg(package.LegConfig(package.OptionType.Call, strike=100.0, quantity=-1, lot_size=1))
    result = package.SpreadBacktest("CI", config).run([1, 2], [[10.0, 8.0]], [True, False], [False, True])
    if result.total_pnl != 2.0:
        raise RuntimeError("Native extension functional check failed")
    receipt = {"python": platform.python_version(), "executable": sys.executable,
               "module": name, "extension": str(origin), "version": version,
               "extension_sha256": hashlib.sha256(origin.read_bytes()).hexdigest(),
               "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
               "inputs": native_inputs(), "functional_pnl": result.total_pnl}
    text = json.dumps(receipt, sort_keys=True)
    if output is not None:
        output.write_text(text + "\n")
    print(text)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["versions", "verify", "native-inputs", "native"])
    parser.add_argument("--github-output", action="store_true")
    parser.add_argument("--tool", choices=["python", "node", "pnpm", "uv"])
    parser.add_argument("--expected")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--wheel", type=Path)
    args = parser.parse_args()
    if args.mode == "native-inputs":
        if args.output is None:
            parser.error("native-inputs requires --output")
        args.output.write_text(json.dumps(native_inputs(), sort_keys=True) + "\n")
        return 0
    if args.mode == "native":
        if args.expected is None or args.inputs is None or args.wheel is None:
            parser.error("native requires --expected, --inputs and --wheel")
        return native(args.expected, args.inputs, args.wheel, args.output)
    if args.mode == "verify":
        if args.tool is None or args.expected is None:
            parser.error("verify requires --tool and --expected")
        return verify(args.tool, args.expected, args.output)
    selected = versions()
    if args.github_output:
        print("\n".join(f"{key}={value}" for key, value in selected.items()))
    else:
        print(json.dumps(selected, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
