// Test source: GNU AGPL v3, as licensed in the repository LICENSE.
import assert from 'node:assert/strict';
import { spawn, type ChildProcess } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { createWriteStream } from 'node:fs';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { test } from '@playwright/test';

declare global {
  interface Window {
    incidentNotices: {title: string; options: NotificationOptions}[];
    incidentProbeKey: string;
  }
}

// Only fixture-owned processes are signalled. Neither an existing server nor a
// user's environment/credential configuration is borrowed by this probe.
test('normal factory browser incident delivery and reload at-most-once', async ({page}, testInfo) => {
  const terminal = path.resolve(import.meta.dirname, '../..');
  const root = path.resolve(terminal, '../../..');
  const temporary = await mkdtemp(path.join(tmpdir(), 'flinttrade-incident-browser-'));
  const python = process.env.FLINTTRADE_TEST_PYTHON ?? path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const key = randomUUID();
  const env = Object.fromEntries(Object.entries(process.env).filter(([name]) => [
    'PATH', 'HOME', 'TMPDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL', 'TZ', 'CI',
    'SYSTEMROOT', 'SystemRoot', 'WINDIR', 'PYTHONNOUSERSITE', 'PYTHONDONTWRITEBYTECODE',
    'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
  ].includes(name)));
  const children: {name: string; child: ChildProcess; exited: Promise<void>; log: ReturnType<typeof createWriteStream>}[] = [];
  async function start(name: string, command: string, args: string[], cwd: string, url: string) {
    const log = createWriteStream(testInfo.outputPath(`${name}.log`));
    const child = spawn(command, args, {cwd, env: {...env, INCIDENT_PROBE_API_KEY: key,
      INCIDENT_PROBE_CACHE: process.env.INCIDENT_PROBE_CACHE ?? path.join(temporary, 'vite-cache'),
      CHOKIDAR_USEPOLLING: '1', RETICLE_CONNECT: '0', RETICLE_TELEMETRY: '0'}, stdio: ['ignore', 'pipe', 'pipe']});
    child.stdout!.pipe(log, {end: false});
    child.stderr!.pipe(log, {end: false});
    let spawnError: Error | undefined;
    child.on('error', error => {spawnError = error;});
    const exited = new Promise<void>(resolve => child.once('close', () => resolve()));
    children.push({name, child, exited, log});
    const deadline = Date.now() + 30_000;
    while (Date.now() < deadline) {
      if (spawnError) throw spawnError;
      if (child.exitCode !== null || child.signalCode !== null) throw new Error(`${name} exited before readiness`);
      try {
        const response = await fetch(url, {signal: AbortSignal.timeout(1000)});
        if (response.status === 200) return;
      } catch { /* A refused owned listener is not ready yet. */ }
      await delay(100);
    }
    throw new Error(`${name} readiness deadline exceeded`);
  }
  try {
    await start('core', python, [path.join(root, 'tests/incident_probe.py'), '--port', '5100'], root, 'http://127.0.0.1:5100/healthz');
    const require = createRequire(import.meta.url);
    const vite = path.resolve(path.dirname(require.resolve('vite/package.json')), 'bin/vite.js');
    await start('vite', process.execPath, [vite, '--config', 'e2e/incidents/vite.config.ts', '--configLoader', 'runner', '--host', '127.0.0.1', '--port', '5173', '--strictPort'], terminal, 'http://127.0.0.1:5173/e2e/incidents/index.html');
    const requests: string[] = [], errors: string[] = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', r => { if (r.url().includes('/ft-api/')) requests.push(`${r.method()} ${new URL(r.url()).pathname}`); });
    await page.addInitScript(apiKey => {
      window.incidentProbeKey = apiKey;
      window.incidentNotices = [];
      // Replace only the external OS notification transport, never the store,
      // mounted query, request decoder, delivery claim or receipt implementation.
      Object.defineProperty(window, 'Notification', {value: class {
        static permission = 'granted';
        constructor(title: string, options: NotificationOptions) { window.incidentNotices.push({title, options}); }
      }});
    }, key);
    const seed = await page.request.get('http://127.0.0.1:5100/synthetic-incident-failure', {headers: {'X-API-Key': key}});
    assert.equal(seed.status(),503);
    const correlation=seed.headers()['x-diagnostic-request-id'];
    await page.goto('http://127.0.0.1:5173/e2e/incidents/index.html');
    await page.getByRole('region',{name:'Incident timeline'}).waitFor();
    await page.getByText('Submitted; user delivery unobserved',{exact:true}).waitFor();
    assert.equal(await page.getByText(`Correlation: ${correlation}`,{exact:true}).count(),1);
    const notices=await page.evaluate(()=>window.incidentNotices);
    assert.equal(notices.length,1);
    assert.equal(notices[0].title,'FlintTrade critical incident');
    assert.ok(notices[0].options.body!.includes('Root cause unconfirmed'));
    const data=await page.request.get('http://127.0.0.1:5100/api/v1/system/incidents',{headers:{'X-API-Key':key}});
    const timeline=await data.json();
    assert.equal(timeline.incidents.length,1);
    assert.equal(timeline.incidents[0].correlation_id,correlation);
    assert.equal(timeline.incidents[0].deliveries.find((d: {channel: string})=>d.channel==='desktop').state,'submitted_unobserved');
    assert.equal(requests.filter(r=>r.endsWith('/diagnostics')).length,2);
    assert.equal(requests.filter(r=>r.endsWith('/claim')).length,1);
    assert.equal(requests.filter(r=>r.endsWith('/receipt')).length,1);
    assert.equal(requests.length,4);
    assert.deepEqual(errors,[]);
    await page.reload();
    await page.getByText('Submitted; user delivery unobserved',{exact:true}).waitFor();
    assert.equal((await page.evaluate(()=>window.incidentNotices)).length,0);
    assert.equal(requests.filter(r=>r.endsWith('/claim')).length,1);
    await writeFile(testInfo.outputPath('browser.json'),JSON.stringify({passed:true,requests,incident:timeline.incidents[0],errors},null,2));
    console.log(JSON.stringify({passed:true,requests,alerts_before_reload:1,alerts_after_reload:0,errors}));
  } finally {
    await page.close();
    const cleanup = [];
    for (const {name, child, exited, log} of children.reverse()) {
      const requestedStop = child.exitCode === null && child.signalCode === null;
      if (requestedStop) child.kill('SIGTERM');
      const done = await Promise.race([exited.then(() => true), delay(15_000).then(() => false)]);
      if (!done) { child.kill('SIGKILL'); await exited; }
      await new Promise<void>(resolve => log.end(resolve));
      cleanup.push({name, done, requestedStop, exitCode: child.exitCode, signalCode: child.signalCode});
    }
    await writeFile(testInfo.outputPath('cleanup.json'), JSON.stringify(cleanup, null, 2));
    console.log(JSON.stringify({cleanup}));
    await rm(temporary, {recursive: true, force: true});
    for (const child of cleanup) {
      assert.ok(child.done, 'owned fixture did not stop within its deadline');
      // Vite's SIGTERM handler awaits server.close() and exits 128 + SIGTERM.
      const viteTerminated = child.name === 'vite' && child.requestedStop && child.exitCode === 143;
      assert.ok(child.exitCode === 0 || child.signalCode === 'SIGTERM' || viteTerminated, 'owned fixture cleanup failed');
    }
  }
});
