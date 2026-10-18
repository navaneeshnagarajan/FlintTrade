"""Run only the maintained current-app harness, inside the existing sandbox."""
from pathlib import Path
import argparse
import importlib.util
import json
import os
import socket
import subprocess
import sys
from validate_results import validate_original

HERE = Path(__file__).resolve().parent
APP = HERE.parents[1]
OUT = Path('/run/test/artifacts')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['controls','collect','original','infra'])
    parser.add_argument('--python',type=Path,help='Explicit parent-qualified Python 3.14.8 environment')
    args=parser.parse_args()
    spec=importlib.util.spec_from_file_location('reticle_setup',HERE/'setup.py')
    if spec is None or spec.loader is None:raise RuntimeError('Missing owned setup module')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.guard();module.verify_runtime(HERE/'runtime/package')
    env={**os.environ,'FLINTTRADE_E2E_SOURCE_ROOT':str(APP),'RETICLE_TEST_ROOT':str(HERE/'runtime/package/node_modules')}
    env.update(R24_STAGE='reticle',R24_CORE_PORT='5100',FLINTTRADE_E2E_CORE_STATE='/run/test/bootstrap.json',
               FLINTTRADE_E2E_CORE_SERVER=str(HERE/'harness/core-server.py'),
               FLINTTRADE_E2E_DISCOVERY_PROBE=str(HERE/'harness/discovery-probe.mjs'),
               FLINTTRADE_E2E_RETICLE_CLIENT=str(HERE/'harness/client.mjs'),
               FLINTTRADE_E2E_RETICLE_WITNESS=str(HERE/'runtime/consumer/witness.mjs'),
               FLINTTRADE_E2E_RETICLE_PRESENTER=str(HERE/'runtime/consumer/presenter.mjs'))
    if args.mode=='original':
        if args.python is None:raise RuntimeError('Parent must supply the qualified Python 3.14.8 environment; no 3.14.7 fallback')
        version=subprocess.check_output([str(args.python),'-I','-S','-c','import platform;print(platform.python_version())'],text=True).strip()
        if version!='3.14.8':raise RuntimeError('Current epoch requires Python 3.14.8; received '+version)
        env['FLINTTRADE_E2E_PYTHON']=str(args.python)
        paths=[APP]+[p for p in (APP/'packages').rglob('src') if p.is_dir() and any(x.name.startswith('flinttrade_') for x in p.iterdir())]
        env['PYTHONPATH']=os.pathsep.join(map(str,paths))
        (OUT/'python-selection.json').write_text(json.dumps({'python':str(args.python),'version':version,'pythonpath':list(map(str,paths))},indent=2))
    commands=[]
    def run(cmd,name,timeout=900):
        # Toolkit controls historically run outside app project registration.
        # Explicit --dir/config select the current app for its actual journeys.
        with (OUT/(name+'.log')).open('w') as log:
            result=subprocess.run(cmd,cwd='/run/test',env=env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
        commands.append({'name':name,'argv':list(map(str,cmd)),'exit':result.returncode})
        print(name,result.returncode,flush=True)
        return result.returncode
    cli=['node',str(HERE/'runtime/package/node_modules/@reticlehq/server/bin/reticle.js')]
    terminal=APP/'packages/apps/terminal'
    started=False;cleanup={};code=1
    try:
        if args.mode=='controls':
            code=run(['node','--test','--test-concurrency=1','--test-timeout=25000',*[str(HERE/'tests'/n) for n in ['contracts.test.mjs','wire.test.mjs','lifetime.test.mjs']]],'controls',180)
        elif args.mode=='infra':
            code=run(['pnpm','--dir',str(terminal),'run','e2e:infra:typecheck'],'typecheck',180)
            if code==0:code=run(['pnpm','--dir',str(terminal),'run','e2e:infra:lint'],'lint',180)
            if code==0:code=run(['pnpm','--dir',str(terminal),'exec','eslint','playwright.reticle.config.ts','vite.reticle.config.ts','--max-warnings=0'],'carrier-config-lint',180)
        else:
            cmd=['pnpm','--dir',str(terminal),'exec','playwright','test','--config='+str(terminal/'playwright.reticle.config.ts'),'--project=chromium','--workers=1','--retries=0']
            if args.mode=='collect':
                code=run(cmd+['--list'],'collect',90)
            else:
                for port in [4400,5173,5100]:
                    with socket.socket() as listener:listener.bind(('127.0.0.1',port))
                env.update(RETICLE_CAPTURE_RETENTION=json.dumps({'maxEvents':10000,'maxAgeMs':120000,'maxBytes':33554432}),RETICLE_JOURNAL='1',CHOKIDAR_USEPOLLING='1')
                started=True
                if run(cli+['serve','--port','4400'],'serve',45):raise RuntimeError('Owned Reticle daemon failed')
                code=run(cmd,'original',900)
                if code==0:
                    validate_original(OUT)
    finally:
        if started:cleanup['stop']=run(cli+['stop'],'stop',45)
        for port in [4400,5173,5100]:
            with socket.socket() as listener:
                listener.settimeout(2);cleanup[str(port)+'_refused']=listener.connect_ex(('127.0.0.1',port))!=0
        module.verify_runtime(HERE/'runtime/package')
        (OUT/'qualification-execution.json').write_text(json.dumps({'mode':args.mode,'commands':commands,'cleanup':cleanup,'final_stack_acceptance':False,'requires_parent_body_geometry_scope_reconciliation':True},indent=2))
    return int(code!=0 or cleanup.get('stop',0)!=0 or not all(v for k,v in cleanup.items() if k.endswith('_refused')))

if __name__=='__main__':raise SystemExit(main())
