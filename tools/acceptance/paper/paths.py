"""Per-process generated state, confined to the disposable runner namespace."""
import os
from pathlib import Path
import sys

def artifacts():
    if sys.flags.optimize or os.environ.get('HOME') != '/run/test/home':
        raise RuntimeError('Authorised non-optimised isolated runner required')
    result = Path(os.environ['FLINTTRADE_ACCEPTANCE_ARTIFACTS']).resolve()
    if not result.is_relative_to('/run/test/artifacts') or not result.is_dir():
        raise RuntimeError('Owned artifact directory required')
    return result

def workspace_root():
    result = Path(os.environ['FLINTTRADE_ACCEPTANCE_WORKSPACE']).resolve()
    if not result.is_relative_to('/run/test/home'):
        raise RuntimeError('Owned empty workspace required')
    return result
