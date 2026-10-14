"""Qualify exact denial under syscall observation in fresh child processes."""

import sys
from pathlib import Path
from paths import artifacts
if sys.flags.optimize:
    raise RuntimeError('Acceptance assertions require non-optimised Python')
import json
import re
import subprocess

cases=['positive','unused','wrong-caller','wrong-family','wrong-type','wrong-protocol','wrong-address',
       'wrong-port','wrong-shape','spoof-filename','repeat','reload','latched','connect','dns','listen','accept']
rows=[]
for case in cases:
    trace=artifacts()/('syscalls-'+case+'.log')
    cmd=['/usr/bin/strace','-f','-qq','-e','trace=network','-o',str(trace),sys.executable,
         str(Path(__file__).with_name('probe-controls.py')),case]
    result=subprocess.run(cmd,capture_output=True,text=True,check=False)
    Path('/run/test/artifacts/control-'+case+'.log').write_text(result.stdout+result.stderr)
    text=trace.read_text()
    forbidden=re.findall(r'\b(?:bind|connect|listen|accept|accept4)\(',text)
    rows.append({'case':case,'exit_code':result.returncode,'forbidden_syscalls':forbidden,'command':cmd})
(artifacts() / 'probe-matrix.json').write_text(json.dumps(rows,indent=2))
print(json.dumps(rows,indent=2))
assert len(rows)==len(cases) and all(r['exit_code']==0 and not r['forbidden_syscalls'] for r in rows)
