// Compile the cumulative accepted sources over the explicit R42/R39 closure.
// Server code/tests remain FSL-1.1-ALv2; see licenses/server/LICENSE.
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
const require=createRequire(import.meta.url);
const [output,compiler,nodeTypes,wsTypes,pngTypes]=process.argv.slice(2);
const ts=require(path.join(compiler,'lib/typescript.js'));
if(ts.version!=='6.0.3')throw Error('Pinned TypeScript compiler required');
const C=path.join(output,'node_modules');
const manifest=JSON.parse(fs.readFileSync(path.join(here,'qualification.json'),'utf8'));
const groups=new Map();
for(const name of Object.keys(manifest.sources).filter(n=>n.endsWith('.ts')&&!n.endsWith('.test.ts'))){
  const browser=name.startsWith('adapters/realm/browser/src/');
  const pkg=browser?'browser':name.split('/')[0];
  const rel=name.slice(browser?'adapters/realm/browser/src/'.length:(pkg+'/src/').length);
  const relative=rel.replace(/\.ts$/,'.js');
  const source=fs.readFileSync(path.join(here,'source',name),'utf8');
  const result=ts.transpileModule(source,{fileName:rel,reportDiagnostics:true,compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext,verbatimModuleSyntax:true,isolatedModules:true,removeComments:browser,sourceMap:true}});
  if(result.diagnostics?.length)throw Error('Source transpilation failed: '+name);
  const code=result.outputText.replace(/\/\/# sourceMappingURL=[^\n]*\n?/g,'').replace(/(['"])@\/([^'"\n]+)\1/g,(_,q,p)=>{let r=path.posix.relative(path.posix.dirname(relative),p);if(!r.startsWith('.'))r='./'+r;return q+r+q;});
  const map=JSON.parse(result.sourceMapText);map.sourcesContent=[source];
  const dest=path.join(C,'@reticlehq',pkg,'dist',relative);
  fs.mkdirSync(path.dirname(dest),{recursive:true});fs.writeFileSync(dest,code);fs.writeFileSync(dest+'.map',JSON.stringify(map));
  if(!groups.has(pkg))groups.set(pkg,[]);groups.get(pkg).push({name,rel});
}
fs.mkdirSync(C+'/@types',{recursive:true});
for(const [name,src] of [['node',nodeTypes],['ws',wsTypes],['pngjs',pngTypes]])fs.symlinkSync(src,C+'/@types/'+name);
const checks=[];
try{
 for(const pkg of ['core','browser','server']){
  const rows=groups.get(pkg);if(!rows)continue;
  const root=C+'/@reticlehq/'+pkg,check=root+'/check';fs.cpSync(root+'/dist',check,{recursive:true});
  const files=rows.map(({name,rel})=>{const d=check+'/'+rel;fs.mkdirSync(path.dirname(d),{recursive:true});fs.copyFileSync(path.join(here,'source',name),d);return d;});
  const opts={target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext,moduleResolution:ts.ModuleResolutionKind.Bundler,lib:['lib.es2023.d.ts',...(pkg==='browser'?['lib.dom.d.ts','lib.dom.iterable.d.ts']:[])],strict:true,noUncheckedIndexedAccess:true,exactOptionalPropertyTypes:true,noUnusedLocals:true,noUnusedParameters:true,noImplicitReturns:true,skipLibCheck:true,types:['node'],typeRoots:[C+'/@types'],verbatimModuleSyntax:true,isolatedModules:true,declaration:true,emitDeclarationOnly:true,declarationMap:true,rootDir:check,outDir:root+'/dist',paths:{'@/*':[check+'/*']}};
  const program=ts.createProgram(files,opts),diagnostics=ts.getPreEmitDiagnostics(program);
  checks.push({pkg,files,diagnostics:diagnostics.map(d=>({file:d.file?.fileName,code:d.code,message:ts.flattenDiagnosticMessageText(d.messageText,'\n')}))});
  if(diagnostics.length){console.log(ts.formatDiagnosticsWithColorAndContext(diagnostics,{getCurrentDirectory:()=>process.cwd(),getCanonicalFileName:f=>f,getNewLine:()=> '\n'}));throw Error('Strict source typecheck failed');}
  if(program.emit().emitSkipped)throw Error('No declarations emitted');
  for(const {rel} of rows){const dr=rel.replace(/\.ts$/,'.d.ts'),out=root+'/dist/'+dr;let s=fs.readFileSync(out,'utf8').replace(/(['"])@\/([^'"\n]+)\1/g,(_,q,p)=>{let r=path.posix.relative(path.posix.dirname(dr),p);if(!r.startsWith('.'))r='./'+r;return q+r+q;});fs.writeFileSync(out,s);}
  fs.rmSync(check,{recursive:true});
 }
}finally{
 fs.writeFileSync(path.join(path.dirname(output),'typecheck.json'),JSON.stringify(checks,null,2));
 for(const n of ['node','ws','pngjs'])fs.rmSync(C+'/@types/'+n);
 if(!fs.readdirSync(C+'/@types').length)fs.rmdirSync(C+'/@types');
}
console.log('CUMULATIVE_SOURCE_BUILD_OK',Object.values(checks).map(r=>[r.pkg,r.files.length]));
