// Portable real-browser regression; invoked by test_service_oauth_browser.py.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import {execFileSync} from 'node:child_process';
const terminal = fileURLToPath(new URL('../', import.meta.url));
const require = createRequire(path.join(terminal,'package.json'));
const esbuild = createRequire(path.join(terminal,'../desktop/package.json'))('esbuild');
const output = process.argv[3];
if (process.argv[2] === 'build') {
 esbuild.buildSync({entryPoints:[path.join(terminal,'e2e/service-oauth-handoff.entry.ts')],outfile:path.join(output,'fixture.js'),bundle:true,format:'iife',jsx:'automatic',alias:{'@':path.join(terminal,'src'),'react':path.dirname(require.resolve('react/package.json')),'react-dom':path.dirname(require.resolve('react-dom/package.json'))},define:{'import.meta.env':'{"DEV":false,"MODE":"test"}'}});
 esbuild.buildSync({entryPoints:[path.join(terminal,'../desktop/electron/hardening.ts')],outfile:path.join(output,'hardening.cjs'),bundle:true,platform:'node',format:'cjs'});
} else {
 const {chromium} = require('@playwright/test');
 const {hardenWebContents} = require(path.join(output,'hardening.cjs'));
 const origin = process.argv[2];
 const failures=[];const providers=[];const bridge=[];
 // The no-egress namespace cannot resolve a real HTTPS redirect. A narrowly
 // admitted loopback CONNECT proxy supplies only the inert provider HTTP peer.
 execFileSync('openssl',['req','-config','/dev/null','-x509','-newkey','rsa:2048','-noenc','-subj','/CN=auth.openai.com','-keyout',path.join(output,'key.pem'),'-out',path.join(output,'cert.pem'),'-days','1'],{stdio:'ignore'});
 const provider=https.createServer({key:fs.readFileSync(path.join(output,'key.pem')),cert:fs.readFileSync(path.join(output,'cert.pem'))},async(req,res)=>{
  try {
   const url=new URL(req.url,'https://auth.openai.com');
   assert.equal(req.headers.host,'auth.openai.com');
   assert.equal(url.pathname,'/api/accounts/authorize');providers.push(url.pathname);
   const update=await fetch(origin+'/_test/provider',{method:'POST',headers:{'Content-Type':'application/json','X-API-Key':'test-key'},body:JSON.stringify({nonce:url.searchParams.get('nonce'),challenge:url.searchParams.get('code_challenge')})});
   assert.equal(update.status,204);
   const callback=new URL(url.searchParams.get('redirect_uri'));assert.equal(callback.origin,origin);
   callback.searchParams.set('state',url.searchParams.get('state'));callback.searchParams.set('code','synthetic-code');callback.searchParams.set('client_id','oaiapp_test');
   res.writeHead(302,{location:callback.href});res.end();
  } catch {failures.push('inert provider contract failed');res.writeHead(500);res.end();}
 });
 await new Promise(resolve=>provider.listen(0,'127.0.0.1',resolve));
 const sockets=new Set();
 const proxy=http.createServer((_req,res)=>{res.writeHead(403);res.end();});
 proxy.on('connect',(req,socket)=>{
  sockets.add(socket);socket.on('close',()=>sockets.delete(socket));
  if(req.url!=='auth.openai.com:443'){socket.end('HTTP/1.1 403 Forbidden\r\n\r\n');return;}
  const peer=net.connect(provider.address().port,'127.0.0.1',()=>{socket.write('HTTP/1.1 200 Connection Established\r\n\r\n');socket.pipe(peer);peer.pipe(socket);});
  sockets.add(peer);peer.on('close',()=>sockets.delete(peer));peer.on('error',()=>socket.destroy());socket.on('error',()=>peer.destroy());
 });
 await new Promise(resolve=>proxy.listen(0,'127.0.0.1',resolve));
 const browser = await chromium.launch({headless:true});
 const renderer = await browser.newContext({extraHTTPHeaders:{'X-API-Key':'test-key'}});
 const external = await browser.newContext({ignoreHTTPSErrors:true,proxy:{server:`http://127.0.0.1:${proxy.address().port}`,bypass:'127.0.0.1,localhost'}});
 try {
  const page=await renderer.newPage();
  const externalPage=await external.newPage();
  let opener;
  let pending;
  hardenWebContents({closeDevTools(){},getURL:()=>page.url(),on(){},setWindowOpenHandler(handler){opener=handler;}},{development:false,originPolicy:{terminalOrigin:origin,splashUrl:'file:///splash'},openExternal(url){bridge.push(new URL(url).pathname);pending=externalPage.goto(url);}});
  // Electron invokes this exact window-open handler before child navigation.
  // Only the OS shell adapter is replaced, opening our second Chromium context.
  await page.exposeFunction('nativeOpen',url=>{assert.deepEqual(opener({url}),{action:'deny'});});
  await page.addInitScript(()=>document.addEventListener('click',event=>{const target=event.target.closest('a[target="_blank"]');if(target){event.preventDefault();void window.nativeOpen(target.href);}},true));
  page.on('pageerror',error=>failures.push(error.message));
  await page.goto(origin+'/_test/renderer');
  await page.getByRole('button',{name:'Enable local/OSS provider sign-in',exact:true}).click();
  assert.equal(providers.length,0);
  await page.getByRole('button',{name:'Confirm local/OSS activation',exact:true}).click();
  await page.getByText(/Local\/OSS activation read back/).waitFor();
  await page.getByRole('button',{name:'Continue with ChatGPT',exact:true}).click();
  const link=page.getByRole('link',{name:'Open provider sign-in',exact:true});
  await link.waitFor();
  const launch=await link.getAttribute('href');
  assert.equal(new URL(launch).origin,origin);
  await link.click();
  await externalPage.getByText(/Provider response received/).waitFor();
  await pending;
  const rc=(await renderer.cookies()).filter(c=>c.name==='flinttrade_service_oauth');
  const ec=(await external.cookies()).filter(c=>c.name==='flinttrade_service_oauth');
  assert.equal(rc.length,0);assert.equal(ec.length,1);assert.equal(ec[0].httpOnly,true);assert.equal(ec[0].sameSite,'Lax');
  const unauth=await externalPage.request.post(origin+'/v1/services/connections/'+process.argv[4]+'/oauth/complete',{data:{transaction_id:'00000000-0000-4000-8000-000000000001'}});
  assert.equal(unauth.status(),401);
  await page.getByRole('button',{name:'Complete sign-in',exact:true}).click();
  await page.getByText(/Provider grant connected and read back/).waitFor();
  const replay=await externalPage.request.get(launch,{maxRedirects:0});assert.equal(replay.status(),409);
  assert.deepEqual(failures,[]);assert.equal(providers.length,1);assert.deepEqual(bridge,['/v1/services/connections/oauth/launch']);
  await page.screenshot({path:path.join(output,'browser.png')});
  fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify({rendererCookies:rc.length,externalCookies:ec.length,httpOnly:true,sameSite:'Lax',providerNavigations:providers.length,bootstrapReplay:replay.status(),externalComplete:unauth.status(),mountedCompletion:true,bridge:'production hardening; test OS-shell adapter',pageErrors:failures},null,2));
 } finally {await browser.close();for(const socket of sockets)socket.destroy();proxy.close();provider.close();}
}
