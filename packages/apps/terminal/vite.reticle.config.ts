import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import base from './vite.config.ts';
const app=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../..');
const here=path.join(app,'tools/reticle');
const candidate=path.join(here,'runtime/package');
const profile={name:'qualified-owned-observation-profile',enforce:'post' as const,transform(code:string,id:string){
 if(id!=='/@reticle-connect')return null;
 const needle='reticle.connect(';
 if(code.split(needle).length!==2)throw Error('unexpected published connect module; refusing overlay');
 const begin=code.indexOf(needle)+needle.length,end=code.indexOf(');',begin);
 const args=JSON.parse(code.slice(begin,end));
 const metadata=JSON.parse(fs.readFileSync(candidate+'/node_modules/@reticlehq/react/package.json','utf8'));
 if(metadata.version!=='3.6.0')throw Error('unknown aliased SDK package identity');
 const changed=code.slice(0,begin)+JSON.stringify({...args,sdkVersion:metadata.version,observationProfile:{domMaxPerBatch:256}})+code.slice(end);
 fs.writeFileSync('/run/test/artifacts/connect-before.js',code);fs.writeFileSync('/run/test/artifacts/connect-after.js',changed);
 return {code:changed,map:null};
}};
export default {...base,plugins:[...(base.plugins??[]),profile],cacheDir:'/run/test/cache/qualified-vite',server:{...base.server,watch:{...base.server?.watch,usePolling:true,interval:100},fs:{...base.server?.fs,allow:[app,candidate,...(process.env['FLINTTRADE_E2E_DEPENDENCY_ROOT']?[process.env['FLINTTRADE_E2E_DEPENDENCY_ROOT']]:[])]}},resolve:{...base.resolve,alias:[...Object.entries(base.resolve?.alias??{}).map(([find,replacement])=>({find,replacement})),
{find:/^@reticlehq\/react$/,replacement:candidate+'/node_modules/@reticlehq/react/dist/index.js'},
{find:/^@reticlehq\/browser$/,replacement:candidate+'/node_modules/@reticlehq/browser/dist/index.js'},
{find:/^@reticlehq\/core$/,replacement:candidate+'/node_modules/@reticlehq/core/dist/index.js'}]}};
