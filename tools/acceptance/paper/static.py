"""Retained helper and adjacent admission source lint gates."""
from pathlib import Path
import subprocess
import sys
from paths import artifacts

artifacts()
paths=[str(p) for p in sorted(Path(__file__).parent.glob('*.py'))]
result=subprocess.call([sys.executable,'-m','ruff','check','--select','F,E9',*paths])
if result==0:
    result=subprocess.call([sys.executable,'-m','ruff','check',
        'packages/core/core/src/flinttrade_core/practice_agent_adapter.py',
        'packages/core/core/tests/test_practice_agent_admission_scope.py',
        'packages/services/engine/src/flinttrade_engine/safety.py',
        'packages/services/engine/tests/test_paper_write_admission_scope.py'])
raise SystemExit(result)
