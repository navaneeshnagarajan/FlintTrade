"""Shared public input selection; no historical application environment fallback."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
RETICLE=ROOT/'tools/reticle'

def guard():
    # Reuse the approved public carrier's isolation prerequisites.
    spec=importlib.util.spec_from_file_location('acceptance_reticle_setup', RETICLE/'setup.py')
    if spec is None or spec.loader is None:
        raise RuntimeError('Public Reticle carrier prerequisite missing')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.guard()
    if (ROOT/'.local').exists() or (ROOT/'graphify-out').exists():
        raise RuntimeError('Acceptance needs a source-only checkout without private inputs')
    return module

def python_environment(python, diagnostic=False):
    if sys.flags.optimize:
        raise RuntimeError('Acceptance assertions require non-optimised Python')
    if python is None:
        raise RuntimeError('Explicit Python 3.14.8 interpreter required; no ambient fallback')
    python=Path(python).absolute()
    version=subprocess.check_output([str(python),'-I','-S','-c','import platform;print(platform.python_version())'],text=True).strip()
    if version!='3.14.8' and not diagnostic:
        raise RuntimeError('Current acceptance requires Python 3.14.8; received '+version)
    paths=[ROOT]+[p for p in (ROOT/'packages').rglob('src') if p.is_dir() and 'node_modules' not in p.parts and any(x.name.startswith('flinttrade_') for x in p.iterdir())]
    env=dict(os.environ, FLINTTRADE_E2E_PYTHON=str(python), FLINTTRADE_E2E_SOURCE_ROOT=str(ROOT), PYTHONPATH=os.pathsep.join(map(str,paths)))
    Path('/run/test/artifacts/python-selection.json').write_text(json.dumps({'python':str(python),'version':version,'diagnostic_only':diagnostic,'current_source_paths':list(map(str,paths))},indent=2))
    return env
