"""Read-only audit of one already-completed deployment; never publishes."""
import hashlib
import io
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import PurePosixPath

base = 'e1a0888b2f4c050fb8110277da788e408cd29f80'
artifact = '/tmp/qa-pages.zip'
site = 'https://destrynielsen-maker.github.io/Idaho_Construction_Intelligence/'
expected_digest = 'bba307220bd4a78a26ae090dd0af9ef793d3b1c914a868d2b2c4da5c282fb777'
def sha(b): return hashlib.sha256(b).hexdigest()
with open(artifact, 'rb') as f:
    assert sha(f.read()) == expected_digest, 'Archive ZIP digest mismatch'
required = ['index.html', 'data/permits.json', 'data/builders.json', 'data/sources.json',
    'feeds/commercial.xml', 'feeds/multifamily.xml', 'feeds/new-construction.xml',
    'feeds/single-family.xml', 'feeds/top-opportunities.xml']
with zipfile.ZipFile(artifact) as z:
    files=[x for x in z.namelist() if x.endswith('.tar') or x.endswith('.tar.gz')]
    assert len(files)==1, files
    with tarfile.open(fileobj=io.BytesIO(z.read(files[0])),mode='r:*') as tar:
        members={str(PurePosixPath(m.name)):m for m in tar.getmembers() if m.isfile()}
        for name in required:
            a=tar.extractfile(members[name]).read()
            b=subprocess.check_output(['git','show',base+':public/'+name])
            assert a==b, 'Archive differs from generated main: '+name
            request=urllib.request.Request(site+name+'?audit=397-15177697808',headers={'Cache-Control':'no-cache','User-Agent':'Idaho-public-snapshot-verifier/1.0'})
            with urllib.request.urlopen(request,timeout=45) as response:
                live=response.read()
            assert live==a, 'Served snapshot mismatch: '+name
            print(name,sha(a),flush=True)
print('PASS: all nine actual served files match the exact production artifact and generated main')
