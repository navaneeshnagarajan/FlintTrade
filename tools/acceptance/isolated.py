"""Linux CI launcher: explicit tool paths, read-only source, fresh offline state.

Based on the reviewed legacy constructor (SHA-256
46c500ee881a082f883bdf3cfbf65755f50052a371295446d08dc40e963ec5ab).
No fallback, privilege escalation, writable source or dependency acquisition.
The explicit python-tests prerequisite profile shares the full-mode boundary.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

GUARD = (
    "import errno, json, os, pathlib, subprocess, sys\n"
    "expected=json.loads(sys.argv[1]); host_ns=json.loads(sys.argv[2]); hidden=json.loads(sys.argv[3]); boundary="
    "json.loads(sys.argv[4]); command=sys.argv[5:]\n"
    "assert not sys.flags.optimize\n"
    "assert dict(os.environ)==expected, (set(os.environ)-set(expected),set(expected)-set(os.environ))\n"
    "assert expected['FLINTTRADE_SANDBOX_PROFILE']==boundary['profile'] and boundary['profile'] in ('full',"
    "'python-tests')\n"
    "assert all(not pathlib.Path(p).exists() for p in hidden)\n"
    "assert not pathlib.Path('.local/specs').exists()\n"
    "assert pathlib.Path('.venv/bin/python').exists()\n"
    "ns={k:os.readlink('/proc/self/ns/'+k) for k in host_ns}\n"
    "assert all(ns[k]!=host_ns[k] for k in ns)\n"
    "assert subprocess.check_output(['/usr/bin/readlink','/proc/self/ns/net'],text=True).strip()==ns['net']\n"
    "interfaces=json.loads(subprocess.check_output(['/usr/sbin/ip','-j','address','show'],text=True))\n"
    "assert [x['ifname'] for x in interfaces]==['lo'] and 'UP' in interfaces[0]['flags']\n"
    "for version in ([],['-6']):\n"
    " routes=json.loads(subprocess.check_output(['/usr/sbin/ip','-j',*version,'route','show','table','all'],text="
    "True))\n"
    " assert not any(r.get('dst')=='default' for r in routes)\n"
    "status=dict(line.split(':',1) for line in pathlib.Path('/proc/self/status').read_text().splitlines() if ':' in"
    " line)\n"
    "assert int(status['CapEff'].strip(),16)==0 and status['NoNewPrivs'].strip()=='1'\n"
    "assert all(int(status[k].strip(),16)==0 for k in ('CapInh','CapPrm','CapEff','CapBnd','CapAmb'))\n"
    "assert os.getuid()!=0\n"
    "assert not any(r.get('dev')!='lo' for version in ([],['-6']) for r in json.loads(subprocess.check_output(["
    "'/usr/sbin/ip','-j',*version,'route','show','table','all'],text=True)))\n"
    "for path in boundary['readonly']:\n"
    " assert os.statvfs(path).f_flag & os.ST_RDONLY, ('writable input',path)\n"
    "try:\n"
    " fd=os.open('pyproject.toml',os.O_WRONLY)\n"
    "except OSError as exc:\n"
    " assert exc.errno==errno.EROFS, exc\n"
    "else:\n"
    " os.close(fd); raise RuntimeError('Writable source refused before command')\n"
    "record={'namespaces':ns,'host_namespaces':host_ns,'hidden':hidden,'environment':expected,'boundary':boundary,"
    "'supplementary_groups':os.getgroups(),'status':status}\n"
    "pathlib.Path('/run/test/artifacts/isolation.json').write_text(json.dumps(record,indent=2))\n"
    "print('ISOLATION_VERIFIED '+json.dumps({'namespaces':ns,'hidden_operator_state':True,'environment_keys':sorted"
    "(expected),'network':'private loopback only','cap_effective':0,'capabilities':{k:status[k].strip() for k in ("
    "'CapInh','CapPrm','CapEff','CapBnd','CapAmb')},'supplementary_groups':os.getgroups(),'no_new_privileges':True,"
    "'profile':boundary['profile'],'readonly':boundary['readonly']}),flush=True)\n"
    "os.execvp(command[0],command)\n"
)


def closed_tree(root: Path, allowed: list[Path]) -> None:
    """Refuse special files and links escaping the explicit read-only closure.

    Args:
        root: Input directory to inspect without following directory links.
        allowed: Canonical roots already authorised for read-only exposure.

    Raises:
        RuntimeError: An input is special or resolves outside the closure.
    """
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if path.is_symlink():
                target = path.resolve(strict=True)
                if not any(target.is_relative_to(base) for base in allowed):
                    raise RuntimeError(f"Escaping input symlink: {path}")
            elif not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise RuntimeError(f"Special input file refused: {path}")


def dedicated_root(path: Path, source: Path, state: Path) -> None:
    """Reject broad runtime mounts, including source/state/operator ancestors.

    Args:
        path: Canonical interpreter distribution root.
        source: Canonical source-only checkout.
        state: Explicit disposable state root.

    Raises:
        RuntimeError: The proposed mount exposes a broad or private root.
    """
    if path == Path("/usr"):
        return
    hidden = [Path.home() / name for name in (".ssh", ".config", ".flinttrade", ".npm")]
    if (
        len(path.parts) < 4
        or any(path.is_relative_to(root) for root in hidden)
        or path == Path.home()
        or Path.home().is_relative_to(path)
        or source.is_relative_to(path)
        or state.is_relative_to(path)
        or path.is_relative_to(state)
    ):
        raise RuntimeError(f"Dedicated runtime root required: {path}")


def main() -> int:
    """Validate explicit inputs and run the command in a fresh offline namespace."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--profile", choices=["full", "python-tests"], default="full")
    for name in ["source", "state-root", "uv"]:
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ["assets", "node-root", "pnpm", "pnpm-root", "python-root"]:
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--timeout", type=int, default=480)
    parser.add_argument("--browsers", type=Path, help="Dedicated acquired browser directory; mounted read-only.")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if sys.flags.optimize:
        parser.error("Python optimisation refused before sandbox construction")
    full = args.profile == "full"
    extras = [args.assets, args.node_root, args.pnpm, args.pnpm_root]
    if full and (not all(extras) or args.python_root is not None):
        parser.error("Full profile requires assets, node-root, pnpm and pnpm-root; python-root is Python-only")
    if not full and (any(extras) or args.browsers is not None or args.python_root is None):
        parser.error("Python profile requires python-root and refuses Node/assets/pnpm/browser inputs")
    REPO = args.source.resolve(strict=True)
    SCRATCH = args.state_root.resolve(strict=True)
    BUILD = args.assets.resolve(strict=True) if full else None
    NODE = args.node_root.resolve(strict=True) if full else None
    PNPM = args.pnpm.resolve(strict=True) if full else None
    PNPM_ROOT = args.pnpm_root.resolve(strict=True) if full else None
    UV = args.uv.resolve(strict=True)
    if full and not PNPM.is_relative_to(PNPM_ROOT):
        parser.error("pnpm executable must belong to the explicit pnpm root")
    if any((REPO / part).exists() or (REPO / part).is_symlink() for part in [".git", ".local", "graphify-out"]):
        parser.error("Source-only input required: no Git credentials or private task storage")
    if SCRATCH.is_relative_to(REPO):
        parser.error("Writable runtime state must be outside the read-only source")
    hidden = [str(Path.home() / name) for name in [".flinttrade", ".config", ".ssh", ".npm"]]
    hidden += ["/root", "/run/user"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", args.label):
        parser.error("Invalid evidence label")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("An explicit command is required")
    if not 1 <= args.timeout <= 1800:
        parser.error("Timeout must be 1..1800 seconds")
    if not (REPO / "pyproject.toml").is_file():
        raise RuntimeError(f"Wrong worktree derivation: {REPO}")
    py_base = (REPO / ".venv/bin/python").resolve().parent.parent
    required_paths = [py_base, REPO / ".venv/bin/python", UV]
    if full:
        required_paths += [NODE, PNPM, REPO / "node_modules", REPO / "packages/apps/terminal/node_modules"]
    for required in required_paths:
        if not required.exists():
            raise RuntimeError(f"Missing prerequisite: {required}")
    for tool in ["/usr/bin/bwrap", "/usr/sbin/ip", "/usr/bin/readlink", "/etc/ld.so.cache"]:
        if not Path(tool).is_file():
            raise RuntimeError(f"Missing sandbox prerequisite: {tool}; no automatic installation")
    if not full:
        if args.python_root.is_symlink() or args.source.is_symlink():
            parser.error("Symlink source/runtime root refused; use the explicit closed input")
        declared = args.python_root.resolve(strict=True)
        if py_base != declared:
            parser.error("Selected interpreter escapes the declared Python runtime root")
        dedicated_root(declared, REPO, SCRATCH)
        closed_tree(declared, [declared, Path("/usr")])
        closed_tree(REPO, [REPO, declared, Path("/usr")])
        config = REPO / ".venv/pyvenv.cfg"
        if not config.is_file() or "include-system-site-packages = false" not in config.read_text().lower():
            parser.error("Python profile requires a genuine sterile venv")
        for site in (REPO / ".venv").glob("lib/python*/site-packages"):
            if any(site.iterdir()):
                parser.error("Python profile refuses installed site-packages; prepare a --without-pip venv")
        private = {".git", ".local", "graphify-out", ".ssh", ".config", ".flinttrade", ".netrc", ".env"}
        for directory, dirs, files in os.walk(REPO):
            if private.intersection(dirs + files):
                parser.error("Source-only input required: private or checkout metadata found")
        if command[0] not in (str(REPO / ".venv/bin/python"), "python"):
            parser.error("Python profile requires the selected Python command; no browser/Node fallback")
    if args.browsers:
        args.browsers = args.browsers.resolve(strict=True)
        allowed = BUILD
        if not args.browsers.is_relative_to(allowed) or not args.browsers.is_dir():
            parser.error("Browsers must be within the dedicated assets directory, never an operator cache")
    run = Path(tempfile.mkdtemp(prefix=f"flinttrade-{args.label}-", dir=SCRATCH))
    os.chmod(run, 0o700)
    for part in ("home", "cache", "config", "data", "state", "runtime", "tmp", "artifacts", "repo-local", "browsers"):
        (run / part).mkdir(mode=0o700)
    (run / "hosts").write_text("127.0.0.1 localhost\n::1 localhost\n")
    (run / "nsswitch.conf").write_text("hosts: files\npasswd: files\ngroup: files\n")
    env = {
        "PATH": f"{REPO}/.venv/bin:/tools/bin:" + (f"{NODE}/bin:" if full else "") + "/usr/bin:/bin:/usr/sbin",
        "FLINTTRADE_SANDBOX_PROFILE": args.profile,
        "HOME": "/run/test/home",
        "TMPDIR": "/tmp",
        "TEMP": "/tmp",
        "TMP": "/tmp",
        "XDG_CACHE_HOME": "/run/test/cache",
        "XDG_CONFIG_HOME": "/run/test/config",
        "XDG_DATA_HOME": "/run/test/data",
        "XDG_STATE_HOME": "/run/test/state",
        "XDG_RUNTIME_DIR": "/run/test/runtime",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "CI": "true",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "UV_OFFLINE": "1",
        "UV_NO_SYNC": "1",
        "UV_PYTHON_DOWNLOADS": "never",
        "UV_CACHE_DIR": "/run/test/cache/uv",
        "npm_config_offline": "true",
        "npm_config_cache": "/run/test/cache/npm",
        "CARGO_NET_OFFLINE": "true",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "VITEST_MAX_WORKERS": "1",
        "VITEST_HEAP_MB": "4096",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "VECLIB_MAXIMUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "PLAYWRIGHT_BROWSERS_PATH": "/run/test/browsers",
        "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
        "RETICLE_CONNECT": "0",
        "RETICLE_TELEMETRY": "0",
        "DO_NOT_TRACK": "1",
        "RUFF_CACHE_DIR": "/run/test/cache/ruff",
        "PWD": str(REPO),
    }
    host_ns = {k: os.readlink("/proc/self/ns/" + k) for k in ("user", "net", "mnt", "pid")}
    cmd = ["/usr/bin/bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv"]
    cmd += [
        "--ro-bind",
        "/usr",
        "/usr",
        "--symlink",
        "usr/bin",
        "/bin",
        "--symlink",
        "usr/sbin",
        "/sbin",
        "--symlink",
        "usr/lib",
        "/lib",
        "--symlink",
        "usr/lib64",
        "/lib64",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/run",
        "--bind",
        str(run),
        "/run/test",
        "--bind",
        str(run / "tmp"),
        "/tmp",
        "--symlink",
        "/tmp",
        "/var/tmp",
        "--dir",
        "/etc",
        "--ro-bind",
        str(run / "hosts"),
        "/etc/hosts",
        "--ro-bind",
        str(run / "nsswitch.conf"),
        "/etc/nsswitch.conf",
        "--ro-bind",
        "/etc/ld.so.cache",
        "/etc/ld.so.cache",
        "--ro-bind",
        str(py_base),
        str(py_base),
        "--ro-bind",
        str(UV),
        "/tools/bin/uv",
        "--ro-bind",
        str(REPO),
        str(REPO),
    ]
    readonly = [str(REPO), str(py_base), "/usr", "/tools/bin/uv"]
    if full:
        cmd += [
            "--ro-bind",
            "/etc/fonts",
            "/etc/fonts",
            "--ro-bind",
            str(NODE),
            str(NODE),
            "--ro-bind",
            str(PNPM_ROOT),
            str(PNPM_ROOT),
            "--symlink",
            str(PNPM),
            "/tools/bin/pnpm",
        ]
        readonly += [str(NODE), str(PNPM_ROOT)]
    if args.browsers:
        cmd += ["--ro-bind", str(args.browsers), "/run/test/browsers"]
        readonly.append("/run/test/browsers")
    for key, value in env.items():
        cmd += ["--setenv", key, value]
    cmd += [
        "--chdir",
        str(REPO),
        "--",
        str(REPO / ".venv/bin/python"),
        "-I",
        "-S",
        "-c",
        GUARD,
        json.dumps(env),
        json.dumps(host_ns),
        json.dumps(hidden),
        json.dumps({"profile": args.profile, "readonly": readonly}),
        *command,
    ]
    evidence = SCRATCH / "runs"
    evidence.mkdir(exist_ok=True)
    token = f"{args.label}-{uuid.uuid4().hex[:10]}"
    log = evidence / (token + ".log")
    receipt = evidence / (token + ".json")
    start = time.time()
    error = None
    code = 1
    with contextlib.ExitStack() as stack:
        stream = stack.enter_context(log.open("w"))
        try:
            result = subprocess.run(
                cmd,
                cwd=REPO,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=subprocess.STDOUT,
                timeout=args.timeout,
                check=False,
            )
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
            error = "Owned sandbox timed out; no retry or weaker isolation was applied."
            stream.write("\n" + error + "\n")
    text = log.read_text(errors="replace")
    record = {
        "label": args.label,
        "profile": args.profile,
        "command": command,
        "sandbox_argv": cmd,
        "timeout_seconds": args.timeout,
        "exit_code": code,
        "elapsed_seconds": round(time.time() - start, 3),
        "isolation_guard_passed": "ISOLATION_VERIFIED " in text,
        "run_directory": str(run),
        "log": str(log),
        "receipt": str(receipt),
        "node_cache_lock": False,
        "error": error,
    }
    receipt.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2), flush=True)
    print(text[-18000:], flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
