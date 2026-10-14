"""Linux CI launcher: explicit tool paths, read-only source, fresh offline state.

Path-only derivative of the reviewed legacy constructor (SHA-256
46c500ee881a082f883bdf3cfbf65755f50052a371295446d08dc40e963ec5ab).
No fallback, privilege escalation, writable source or dependency acquisition.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

GUARD = """import json, os, pathlib, subprocess, sys
expected=json.loads(sys.argv[1]); host_ns=json.loads(sys.argv[2]); hidden=json.loads(sys.argv[3]); command=sys.argv[4:]
assert dict(os.environ)==expected, (set(os.environ)-set(expected),set(expected)-set(os.environ))
assert all(not pathlib.Path(p).exists() for p in hidden)
assert not pathlib.Path('.local/specs').exists()
assert pathlib.Path('.venv/bin/python').exists()
ns={k:os.readlink('/proc/self/ns/'+k) for k in host_ns}
assert all(ns[k]!=host_ns[k] for k in ns)
assert subprocess.check_output(['/usr/bin/readlink','/proc/self/ns/net'],text=True).strip()==ns['net']
interfaces=json.loads(subprocess.check_output(['/usr/sbin/ip','-j','address','show'],text=True))
assert [x['ifname'] for x in interfaces]==['lo'] and 'UP' in interfaces[0]['flags']
for version in ([],['-6']):
 routes=json.loads(subprocess.check_output(['/usr/sbin/ip','-j',*version,'route','show','table','all'],text=True))
 assert not any(r.get('dst')=='default' for r in routes)
status=dict(line.split(':',1) for line in pathlib.Path('/proc/self/status').read_text().splitlines() if ':' in line)
assert int(status['CapEff'].strip(),16)==0 and status['NoNewPrivs'].strip()=='1'
print('ISOLATION_VERIFIED '+json.dumps({'namespaces':ns,'hidden_operator_state':True,'environment_keys':sorted(expected),'network':'private loopback only','cap_effective':0,'no_new_privileges':True}),flush=True)
os.execvp(command[0],command)
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    for name in ["source", "state-root", "assets", "node-root", "pnpm", "pnpm-root", "uv"]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=480)
    parser.add_argument("--browsers", type=Path, help="Dedicated acquired browser directory; mounted read-only.")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    REPO = args.source.resolve(strict=True)
    SCRATCH = args.state_root.resolve(strict=True)
    BUILD = args.assets.resolve(strict=True)
    NODE = args.node_root.resolve(strict=True)
    PNPM = args.pnpm.resolve(strict=True)
    PNPM_ROOT = args.pnpm_root.resolve(strict=True)
    UV = args.uv.resolve(strict=True)
    if not PNPM.is_relative_to(PNPM_ROOT):
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
    for required in (py_base, NODE, PNPM, REPO / "node_modules", REPO / "packages/apps/terminal/node_modules"):
        if not required.exists():
            raise RuntimeError(f"Missing prerequisite: {required}")
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
        "PATH": f"{REPO}/.venv/bin:/tools/bin:{NODE}/bin:/usr/bin:/bin:/usr/sbin",
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
        "/etc/fonts",
        "/etc/fonts",
        "--ro-bind",
        str(py_base),
        str(py_base),
        "--ro-bind",
        str(NODE),
        str(NODE),
        "--ro-bind",
        str(PNPM_ROOT),
        str(PNPM_ROOT),
        "--symlink",
        str(PNPM),
        "/tools/bin/pnpm",
        "--ro-bind",
        str(UV),
        "/tools/bin/uv",
        "--ro-bind",
        str(REPO),
        str(REPO),
    ]
    if args.browsers:
        cmd += ["--ro-bind", str(args.browsers), "/run/test/browsers"]
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
        "command": command,
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
