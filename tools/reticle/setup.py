"""Offline, exact-input Reticle correction carrier. Run in the authorised sandbox.

No installer, network fetch, namespace constructor, application snapshot or global
cache mutation is performed here. All inherited public inputs are explicit paths.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parent
EXPECTED = '43d63a9f647032663d6f190fcfa61afaa594792a16079a3008ec82b9fef18b5e'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def inventory(root):
    return {str(p.relative_to(root)): {'link': os.readlink(p)} if p.is_symlink() else {'sha256': sha(p)}
            for p in sorted(root.rglob('*')) if p.is_file() or p.is_symlink()}

def digest_map(value):
    return hashlib.sha256((json.dumps(value, indent=2) + '\n').encode()).hexdigest()

def check(condition, message):
    if not condition:
        raise RuntimeError(message)

def guard():
    check(not sys.flags.optimize, 'Python optimisation refused before preparation')
    check(os.environ.get('HOME') == '/run/test/home', 'Authorised isolated runner required')
    check(os.environ.get('npm_config_offline') == 'true', 'Offline environment required')
    check(os.getuid() != 0, 'Ordinary UID required')
    status = dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    check(int(status['CapEff'].strip(), 16) == 0 and status['NoNewPrivs'].strip() == '1', 'Capability boundary required')

def verify_runtime(root):
    check(digest_map(inventory(root)) == EXPECTED, 'Qualified package output mismatch')

def extract(archive, target):
    with tarfile.open(archive) as tar:
        seen = set()
        for member in tar:
            parts = Path(member.name).parts
            check(parts and parts[0] == 'package' and '..' not in parts, 'Unsafe tar member')
            check(member.isfile() or member.isdir(), 'Archive links/special files refused')
            out = target.joinpath(*parts[1:])
            check(out not in seen, 'Duplicate tar entry')
            seen.add(out)
            if member.isdir():
                out.mkdir(parents=True, exist_ok=True)
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                stream = tar.extractfile(member)
                if stream is None:
                    raise RuntimeError('Missing archive bytes')
                out.write_bytes(stream.read())
                out.chmod(0o755 if member.mode & 0o111 else 0o644)

def prepare(args):
    guard()
    manifest = json.loads((ROOT / 'qualification.json').read_text())
    reconstruction = json.loads((ROOT / 'reconstruction.json').read_text())
    check(manifest['qualified_output_sha256'] == EXPECTED, 'Wrong declared output')
    check(not args.output.exists() and not args.output.is_symlink(), 'Fresh output required')
    for name, digest in manifest['sources'].items():
        check(sha(ROOT/'source'/name) == digest, 'Source drift: ' + name)
    for name in ['typescript', 'node', 'ws', 'pngjs']:
        check(inventory(getattr(args, name)) == manifest['build_inputs'][name], 'Build input drift: ' + name)
    check(inventory(args.pristine) == reconstruction['pristine_files'], 'R39 pristine public closure mismatch')
    # Preserve exactly the established package reconstruction before compilation.
    modules = args.output/'node_modules'
    shutil.copytree(args.pristine, modules, symlinks=True)
    (modules/'.package-lock.json').unlink(missing_ok=True)
    for package in reconstruction['packages']:
        archive = args.archives/package['file']
        check(sha(archive) == package['sha256'], 'Public tarball mismatch: ' + package['file'])
        target = modules/package['name']
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        extract(archive, target)
        metadata = json.loads((target/'package.json').read_text())
        check((metadata['name'],metadata['version']) == (package['name'],package['version']), 'Package identity mismatch')
    for edit in json.loads((ROOT/'hydration.patch.json').read_text())['edits']:
        target = modules/edit['path']
        check(sha(target) == edit['input_sha256'], 'R42 hydration before-image mismatch')
        text = target.read_text()
        for replacement in edit['replacements']:
            check(text.count(replacement['old']) == 1, 'Hydration context not unique')
            text = text.replace(replacement['old'],replacement['new'],1)
        check(hashlib.sha256(text.encode()).hexdigest() == edit['output_sha256'], 'Hydration output mismatch')
        target.write_text(text)
    check(digest_map(inventory(modules)) == manifest['hydration_output_sha256'], 'R42/R39 closure mismatch')
    subprocess.run(['node', str(ROOT/'build.mjs'), str(args.output), str(args.typescript), str(args.node), str(args.ws), str(args.pngjs)], check=True)
    verify_runtime(args.output)
    check(inventory(args.pristine) == reconstruction['pristine_files'], 'Pristine input changed')
    # Consumers are generated outside the hash-qualified package root.
    consumer = args.output.parent/'consumer'
    check(not consumer.exists(), 'Fresh consumer destination required')
    subprocess.run(['node', str(ROOT/'emit-consumers.mjs'), str(args.typescript), str(consumer), str(args.output)], check=True)
    record = {'candidate_id':manifest['candidate_id'], 'output_sha256':EXPECTED,
              'upstream_source_commit':manifest['source_commit'], 'consumer':str(consumer),
              'application_acceptance':False, 'build_inputs_verified':True,
              'hydration_dependency_verified':True, 'package_closure_unchanged_after_build':True}
    (args.output.parent/'setup-receipt.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pristine',type=Path,required=True)
    parser.add_argument('--archives',type=Path,required=True)
    parser.add_argument('--typescript',type=Path,required=True)
    parser.add_argument('--node',type=Path,required=True)
    parser.add_argument('--ws',type=Path,required=True)
    parser.add_argument('--pngjs',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'runtime/package')
    prepare(parser.parse_args())
