"""Two real per-case backend processes, with proven stop before replacement."""

import sys
if sys.flags.optimize:
    raise RuntimeError('Acceptance assertions require non-optimised Python')
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, choices=(5100, 5173), required=True)
parser.add_argument('--case-key', required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
assert str(Path.home()) == '/run/test/home'
assert args.output.is_relative_to('/run/test/artifacts/playwright')
receipts = []


def start(output, key):
    child = subprocess.Popen([sys.executable, str(Path(__file__).with_name('core-server.py')), '--port', str(args.port),
        '--case-key', key, '--output', str(output)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, env=dict(os.environ))
    ready = threading.Event()
    def copy():
        for line in child.stdout:
            if line.strip() == 'R24_CORE_READY':
                ready.set()
            print(line, end='', flush=True)
    thread = threading.Thread(target=copy, name='r62-owned-child-output')
    thread.start()
    if not ready.wait(30):
        raise RuntimeError('Real replacement factory did not become ready')
    return child, thread, output


def stop(current):
    child, thread, output = current
    child.stdin.write('STOP\n')
    child.stdin.flush()
    child.stdin.close()
    code = child.wait(timeout=40)
    thread.join(timeout=2)
    assert code == 0 and not thread.is_alive(), code
    shutdown = json.loads((output / 'shutdown.json').read_text())
    assert shutdown['admission_drained'] and shutdown['listener_stopped'] and shutdown['listener_closed_probe']
    assert shutdown['remaining_threads'] == [] and all(v['closed'] for v in shutdown['owners'].values())
    with socket.socket() as connection:
        assert connection.connect_ex(('127.0.0.1', args.port)) != 0
    receipts.append({'pid': child.pid, 'output': str(output), 'exit': code, 'shutdown': shutdown})


current = start(args.output, args.case_key)
try:
    assert sys.stdin.readline().strip() == 'REPLACE'
    stop(current)
    current = None
    replacement = args.output.parent / 'replacement-core'
    current = start(replacement, hashlib.sha256((args.case_key + ':replacement').encode()).hexdigest())
    print('R62_REPLACEMENT_READY', flush=True)
    assert sys.stdin.readline().strip() == 'STOP'
finally:
    if current is not None and current[0].poll() is None:
        stop(current)
    (args.output.parent / 'backend-replacement-lifetimes.json').write_text(json.dumps(receipts, indent=2))
assert len(receipts) == 2 and receipts[0]['pid'] != receipts[1]['pid']
