"""Check the exact candidate archive before deployment and served bytes afterward."""
import argparse
import hashlib
import json
import tarfile
import time
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

REQUIRED = {'index.html', 'data/permits.json', 'data/sources.json', 'data/builders.json',
            'feeds/commercial.xml', 'feeds/multifamily.xml', 'feeds/new-construction.xml',
            'feeds/single-family.xml', 'feeds/top-opportunities.xml'}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def verify_archive(archive, public):
    expected = {p.relative_to(public).as_posix(): sha(p.read_bytes())
                for p in public.rglob('*') if p.is_file()}
    if not REQUIRED <= expected.keys():
        raise ValueError('Missing required generated Pages assets')
    observed = {}
    with tarfile.open(archive, 'r:') as bundle:
        for member in bundle:
            p = PurePosixPath(member.name)
            if p.is_absolute() or '..' in p.parts:
                raise ValueError('Unsafe artifact path')
            if member.isdir():
                continue
            key = p.as_posix()
            if not member.isfile() or key not in expected or key in observed:
                raise ValueError(f'Unexpected, nonregular or repeated Pages member: {key}')
            observed[key] = sha(bundle.extractfile(member).read())
    if observed != expected:
        raise ValueError('Archive does not exactly match generated Pages assets')
    return {'tar_sha256': sha(archive.read_bytes()), 'assets': expected}

def verify_live(manifest, url, expected_url, stamp, attempts=6, delay=8, fetch=urlopen):
    base = url.rstrip('/') + '/'
    if base != expected_url.rstrip('/')+'/' or urlsplit(base).scheme != 'https':
        raise ValueError('Unexpected live Pages URL')
    remaining = dict(manifest['assets'])
    for attempt in range(attempts):
        for key, expected in list(remaining.items()):
            target = base+quote(key,safe='/')+'?scout_accept='+quote(stamp,safe='')+'-'+str(attempt)
            try:
                with fetch(Request(target,headers={'Cache-Control':'no-cache'}), timeout=8) as r:
                    if r.geturl() != target:
                        continue
                    if sha(r.read()) == expected:
                        remaining.pop(key)
            except OSError:
                continue
        if not remaining:
            return
        if attempt+1<attempts:
            time.sleep(delay)
    raise ValueError('Live Pages did not match verified artifact: '+', '.join(sorted(remaining)))

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--manifest',type=Path,required=True)
    cmds=p.add_subparsers(dest='kind',required=True)
    a=cmds.add_parser('archive')
    a.add_argument('tar',type=Path)
    a.add_argument('public',type=Path)
    a=cmds.add_parser('live')
    a.add_argument('page_url')
    a.add_argument('expected_url')
    a.add_argument('stamp')
    a=p.parse_args()
    if a.kind=='archive':
        manifest=verify_archive(a.tar,a.public)
        a.manifest.write_text(json.dumps(manifest,sort_keys=True)+'\n')
        print('Verified artifact:',manifest['tar_sha256'],len(manifest['assets']),'files')
    else:
        manifest=json.loads(a.manifest.read_text())
        verify_live(manifest,a.page_url,a.expected_url,a.stamp)
        print('Live Pages matches verified artifact:',len(manifest['assets']),'files')

if __name__=='__main__':
    main()
