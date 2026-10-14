// Test source: GNU AGPL v3, as licensed in the repository LICENSE.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { it } from 'vitest';
import { GuardianProtocol } from './guardian-protocol';
import { createNativeNotificationRelay } from './notifications';

it('parses fresh normal-factory wire and preserves unobserved delivery for all inert native outcomes', async () => {
  const root = path.resolve(import.meta.dirname, '../../../..');
  const temporary = await mkdtemp(path.join(tmpdir(), 'flinttrade-incident-native-'));
  const wireFile = path.join(temporary, 'native-wire.json');
  const python = process.env.FLINTTRADE_TEST_PYTHON ?? path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => [
    'PATH', 'HOME', 'TMPDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL', 'TZ',
    'SYSTEMROOT', 'SystemRoot', 'WINDIR', 'PYTHONNOUSERSITE', 'PYTHONDONTWRITEBYTECODE',
    'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
  ].includes(key)));
  try {
    const producer = spawnSync(python, [path.join(root, 'tests/incident_probe.py'), '--native-wire', wireFile], { cwd: root, env, encoding: 'utf8', timeout: 30_000 });
    assert.equal(producer.status, 0, producer.stderr + producer.stdout);
    const captured = JSON.parse(await readFile(wireFile, 'utf8'));
    assert.equal(captured.receipt.state,'submitted_unobserved');
    const protocol=new GuardianProtocol();
    const parsed=protocol.feed(Buffer.from(captured.wire));
    assert.equal(parsed.length,1);
    assert.deepEqual(protocol.end(),[]);
    const submitted: {body: string; title: string}[]=[];
    const supported=createNativeNotificationRelay({isSupported:()=>true,show:notice=>submitted.push(notice)});
    assert.equal(supported.publish(parsed[0]),true);
    assert.equal(submitted.length,1);
    assert.equal(submitted[0]!.title,'FlintTrade critical incident');
    const unsupported=createNativeNotificationRelay({isSupported:()=>false,show:()=>{throw Error('must not show');}});
    assert.equal(unsupported.publish(parsed[0]),false);
    const failed: string[]=[];
    const failure=createNativeNotificationRelay({isSupported:()=>true,show:()=>{throw Error('inert OS failure');},onFailure:e=>failed.push(e.message)});
    assert.equal(failure.publish(parsed[0]),false);
    assert.deepEqual(failed,['inert OS failure']);
    // The one-way bridge cannot establish that a user received the notice.
    assert.equal(captured.receipt.state,'submitted_unobserved');
    console.log(JSON.stringify({native_wire_from_normal_factory:true,parsed:parsed.length,submitted:submitted.length,unsupported:false,failed:false,receipt:'submitted_unobserved',captured}));
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});
