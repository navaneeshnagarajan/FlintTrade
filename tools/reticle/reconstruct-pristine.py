"""Reconstruct the inherited public npm closure, not an application snapshot.

Obtain each pristine-archives.json URL under its recorded archive filename using
an acquisition-only downloader, or supply an explicitly selected npm cache.
No network calls or npm lifecycle scripts run here. Every archive is SRI-checked,
and the complete resulting file/link map must match reconstruction.json.
"""
from pathlib import Path
import argparse
import base64
import hashlib
import importlib.util
import json
import os

ROOT=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--archive-dir',type=Path)
    source.add_argument('--npm-cache',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    spec=importlib.util.spec_from_file_location('carrier_setup',ROOT/'setup.py')
    if spec is None or spec.loader is None:raise RuntimeError('Owned setup module missing')
    setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)
    setup.guard()
    if args.output.exists() or args.output.is_symlink():raise RuntimeError('Fresh pristine destination required')
    rows=json.loads((ROOT/'pristine-archives.json').read_text())
    expected=json.loads((ROOT/'reconstruction.json').read_text())['pristine_files']
    verified=[]
    # Validate every archive before constructing the output closure.
    for row in rows:
        algorithm,encoded=row['integrity'].split('-',1)
        if algorithm not in {'sha512','sha256','sha1'}:raise RuntimeError('Unsupported pinned digest')
        digest=base64.b64decode(encoded,validate=True)
        hex_digest=digest.hex()
        archive=(args.archive_dir/row['archive'] if args.archive_dir else args.npm_cache/'_cacache/content-v2'/algorithm/hex_digest[:2]/hex_digest[2:4]/hex_digest[4:])
        if hashlib.new(algorithm,archive.read_bytes()).digest()!=digest:raise RuntimeError('Archive integrity mismatch: '+row['url'])
        path=Path(row['path'])
        if path.is_absolute() or '..' in path.parts:raise RuntimeError('Unsafe package target')
        verified.append((archive,args.output/path))
    args.output.mkdir(parents=True)
    for archive,target in verified:
        target.mkdir(parents=True,exist_ok=True)
        setup.extract(archive,target)
    (args.output/'.package-lock.json').write_bytes((ROOT/'pristine-lock.json').read_bytes())
    for name,entry in expected.items():
        if 'link' not in entry:continue
        dest=args.output/name
        if Path(name).is_absolute() or '..' in Path(name).parts:raise RuntimeError('Unsafe link pathname')
        target=dest.parent/entry['link']
        if not target.resolve().is_relative_to(args.output.resolve()):raise RuntimeError('External dependency link refused')
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists() or dest.is_symlink():raise RuntimeError('Archive unexpectedly supplied generated bin link')
        os.symlink(entry['link'],dest)
    actual=setup.inventory(args.output)
    if actual!=expected:
        changed=[name for name in actual.keys()|expected.keys() if actual.get(name)!=expected.get(name)]
        raise RuntimeError('Pristine closure mismatch: '+json.dumps(changed))
    print(json.dumps({'public_archives':len(rows),'verified_entries':len(actual),'pristine_map_sha256':setup.digest_map(actual),'no_lifecycle_scripts':True,'no_network':True}))

if __name__=='__main__':main()
