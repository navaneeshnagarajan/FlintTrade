// Relocate only imports while preserving the accepted capture algorithm.
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
const require=createRequire(import.meta.url);
const [compiler,out,packages]=process.argv.slice(2);
const ts=require(path.join(compiler,'lib/typescript.js'));
fs.mkdirSync(out,{recursive:false});
let relative=path.relative(out,path.join(packages,'node_modules')).split(path.sep).join('/');
if(!relative.startsWith('.'))relative='./'+relative;
for(const file of fs.readdirSync(here+'/consumer-source').sort()){
 const source=fs.readFileSync(here+'/consumer-source/'+file,'utf8').replaceAll('../node_modules/',relative+'/');
 const result=ts.transpileModule(source,{fileName:file,reportDiagnostics:true,compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext,verbatimModuleSyntax:true,isolatedModules:true}});
 if(result.diagnostics?.length)throw Error('Consumer transpile failed '+file);
 fs.writeFileSync(path.join(out,file.replace(/\.ts$/,'.mjs')),result.outputText);
}
