import path from 'node:path';
import {fileURLToPath} from 'node:url';
import base from './playwright.order-flow.config.ts';
const terminal=path.dirname(fileURLToPath(import.meta.url));
const quote=(s:string)=>"'"+s.replaceAll("'","'\\''")+"'";
export default {
 ...base,testIgnore:[],testDir:path.join(terminal,'e2e'),testMatch:path.join(terminal,'e2e/shared-core-integrated.spec.ts'),
 fullyParallel:false,workers:1,retries:0,timeout:90000,
 outputDir:'/run/test/artifacts/playwright',
 reporter:[['list'],['json',{outputFile:'/run/test/artifacts/results.json'}],['junit',{outputFile:'/run/test/artifacts/results.xml'}]],
 use:{...base.use,baseURL:'http://127.0.0.1:5173',serviceWorkers:'block',trace:'on',screenshot:'on',actionTimeout:8000},
 webServer:{cwd:terminal,command:'pnpm exec vite --config '+quote(path.join(terminal,'vite.reticle.config.ts'))+' --configLoader runner --host 127.0.0.1 --port 5173 --strictPort',port:5173,reuseExistingServer:false,timeout:60000,env:{...process.env,RETICLE_CONNECT:'1',RETICLE_TELEMETRY:'0',CHOKIDAR_USEPOLLING:'1'}}
};
