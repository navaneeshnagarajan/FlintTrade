"""Maintained source-only policy and Paper acceptance in authorised isolation.

No dependency installation, cached application snapshot or provider I/O. A
separately labelled diagnostic mode can exercise plumbing on another interpreter;
it never qualifies the final runtime and is not the maintained acceptance gate.
"""
from collections import Counter
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess

from guard import guard, python_environment, HERE, ROOT, RETICLE

OUT = Path('/run/test/artifacts')
TERM = ROOT/'packages/apps/terminal'
PAPER_CASES = [
    ('text','text-matrix.py',[]), ('static','static.py',[]),
    ('listener','lifetime-controls.py',['listener']), ('client','lifetime-controls.py',['client']),
    ('health','run.py',['health-only']), ('qty2','run.py',['quantity2']),
    ('missing-pin','run.py',['missing-pin']), ('wrong-pin','run.py',['wrong-pin']),
    ('malformed-health','run.py',['malformed-health']), ('down','run.py',['health-down']),
    *[(name,'owned.py',[name]) for name in ['wrong-acl','bad-quote','bad-history','bad-instrument','empty-chat','malformed-chat']],
    ('admission-control','admission-control.py',[]), ('required-positive','owned.py',['positive']),
    ('down-after-entry','owned.py',['down-after-entry']), ('probe','probe-matrix.py',[]),
    *[(name,'boundaries.py',[name]) for name in ['read-expiry','grant-expiry','read-budget','grant-retirement']],
    ('foreign-position','foreign-position.py',[]),
]

def load_validator():
    spec=importlib.util.spec_from_file_location('acceptance_results',RETICLE/'validate_results.py')
    if spec is None or spec.loader is None:
        raise RuntimeError('Public result validator missing')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['collect','infra','default','policy','paper','diagnostic-default','diagnostic-policy','diagnostic-paper'])
    parser.add_argument('--python',type=Path,default=os.environ.get('FLINTTRADE_E2E_PYTHON'))
    parser.add_argument('--case',help='One named Paper diagnostic or the CSP diagnostic; refused by maintained gates')
    args=parser.parse_args()
    guard()
    diagnostic=args.mode.startswith('diagnostic-')
    if args.case is not None and args.mode not in {'diagnostic-paper','diagnostic-default'}:
        parser.error('--case is not permitted by a maintained full-union gate')
    if args.mode=='diagnostic-default' and args.case not in {None,'csp'}:
        parser.error('Only the original CSP union is a selectable default diagnostic')
    env=dict(os.environ)
    if args.mode not in {'collect','infra'}:
        env=python_environment(args.python,diagnostic)
    env.update(FLINTTRADE_E2E_CORE_STATE='/run/test/bootstrap.json',
        FLINTTRADE_E2E_DISCOVERY_PROBE=str(RETICLE/'harness/discovery-probe.mjs'),
        R24_STAGE='browser', R24_CORE_PORT='5173')
    commands=[];code=1
    def execute(argv,name,timeout=1200,child_env=None):
        with (OUT/(name+'.log')).open('w') as log:
            result=subprocess.run(list(map(str,argv)),cwd=ROOT,env=child_env or env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
        commands.append({'name':name,'argv':list(map(str,argv)),'exit':result.returncode})
        print(name,result.returncode,flush=True)
        return result.returncode
    cleanup={}
    try:
        if args.mode=='infra':
            code=execute(['pnpm','--dir',TERM,'run','e2e:infra:typecheck'],'typecheck',180)
            if code==0:code=execute(['pnpm','--dir',TERM,'run','e2e:infra:lint'],'lint',180)
            if code==0:code=execute(['pnpm','--dir',TERM,'exec','eslint','playwright.policy.config.ts','--max-warnings=0'],'policy-config-lint',180)
            return code
        if args.mode.endswith('default'):
            from csp import run as run_default
            env['CI']='true'  # Never reuse a developer listener in the Vite phase.
            code=run_default(env,execute,args.case)
        elif args.mode.endswith('paper'):
            selected=PAPER_CASES
            if args.case:
                selected=[row for row in selected if row[0]==args.case]
                if len(selected)!=1:raise RuntimeError('Unknown exact diagnostic case')
            for name,script,argv in selected:
                directory=OUT/'paper'/name;directory.mkdir(parents=True,exist_ok=False)
                workspace=Path('/run/test/home/paper')/name;workspace.parent.mkdir(parents=True,exist_ok=True)
                child_env=dict(env,FLINTTRADE_ACCEPTANCE_ARTIFACTS=str(directory),FLINTTRADE_ACCEPTANCE_WORKSPACE=str(workspace))
                result=execute([env['FLINTTRADE_E2E_PYTHON'],HERE/'paper'/script,*argv],'paper-'+name,180,child_env)
                if result:
                    raise RuntimeError('Paper case failed: '+name)
                if name not in {'text','static','probe'}:
                    drain=json.loads((directory/'drain.json').read_text())
                    if drain.get('clean') is not True or drain.get('remaining_threads')!=[]:
                        raise RuntimeError('Paper owner did not cleanly drain: '+name)
                for port in [5100,5177,5178]:
                    with socket.socket() as listener:
                        if listener.connect_ex(('127.0.0.1',port))==0:
                            raise RuntimeError('Paper listener remains after '+name)
            code=0
        else:
            config=TERM/'playwright.policy.config.ts'
            cmd=['pnpm','--dir',TERM,'exec','playwright','test','--config='+str(config),'--project=chromium','--workers=1','--retries=0']
            expected=json.loads((HERE/'policy/cases.json').read_text())['cases']
            if args.mode=='collect':
                code=execute([*cmd,'--list','--reporter=list'],'policy-collection',90)
                text=(OUT/'policy-collection.log').read_text()
                names=re.findall(r'\[chromium\] › ([^:]+):\d+:\d+ › (.+)',text)
                if Counter(names)!=Counter((row['file'],row['name']) for row in expected):
                    raise RuntimeError('Exact policy/remaining collection identities differ')
                (OUT/'policy-collected.json').write_text(json.dumps({'cases':names,'count':len(names)},indent=2))
                from csp import collect as collect_default
                collect_default(env,execute)
            else:
                for port in [5100,5173,4400]:
                    with socket.socket() as listener:listener.bind(('127.0.0.1',port))
                if execute(['pnpm','--dir',TERM,'exec','vite','build','--configLoader','runner','--outDir',OUT/'installed-dist'],'installed-build',240):
                    raise RuntimeError('Normal installed build failed')
                code=execute(cmd,'policy',1400)
                # Run original byte/lifetime/geometry reconciliation even on a
                # failed browser union; no passing process count can hide errors.
                accounting=execute([env['FLINTTRADE_E2E_PYTHON'],HERE/'policy/reconcile.py'],'policy-accounting',60)
                if code or accounting:raise RuntimeError('Policy browser/accounting gate failed')
                load_validator().validate_cases(OUT/'results.xml',[(row['file'],row['name']) for row in expected])
                dirs=[p for p in (OUT/'playwright').iterdir() if p.is_dir() and (p/'normal-core').exists()]
                if len(dirs)!=len(expected):raise RuntimeError('Missing per-case normal factory')
                for directory in dirs:
                    for name in ['registry-counts.json','query-cache-final.json','browser-completed-bodies.json','browser-console.json','discovery-observation.json','network-capture-closed.json','core-relay-ledger.json']:
                        if not (directory/name).is_file():raise RuntimeError('Missing mandatory per-case artifact: '+str(directory/name))
                code=0
    finally:

        for port in [4400,5173,5100,5177,5178]:
            with socket.socket() as listener:
                cleanup[str(port)+'_refused']=listener.connect_ex(('127.0.0.1',port))!=0
        (OUT/'acceptance-execution.json').write_text(json.dumps({'mode':args.mode,'commands':commands,'cleanup':cleanup,'diagnostic_only':diagnostic,'required_interpreter_version_selected':not diagnostic and args.mode not in {'collect','infra'},'final_stack_acceptance':False,'full_parent_joins_still_required':True},indent=2))
    return int(code!=0 or not all(v for k,v in cleanup.items() if k.endswith('_refused')))

if __name__=='__main__':
    raise SystemExit(main())
