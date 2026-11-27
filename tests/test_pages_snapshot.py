import importlib.util
import pathlib
import tarfile
import tempfile
import unittest
from io import BytesIO

path = pathlib.Path(__file__).resolve().parents[1] / 'scripts/check_pages_snapshot.py'
spec = importlib.util.spec_from_file_location('check_pages_snapshot', path)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

class SnapshotTest(unittest.TestCase):
    def setUp(self):
        d=tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root=pathlib.Path(d.name)
        self.public=self.root/'public'
        self.bundle=self.root/'artifact.tar'
        self.files={k:k.encode() for k in gate.REQUIRED}
        for k,b in self.files.items():
            p=self.public/k
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_bytes(b)

    def bundle_with(self, pairs):
        with tarfile.open(self.bundle,'w') as t:
            for k,b in pairs:
                i=tarfile.TarInfo('./'+k)
                i.size=len(b)
                t.addfile(i,BytesIO(b))

    def test_verified_archive(self):
        self.bundle_with(self.files.items())
        self.assertEqual(gate.verify_archive(self.bundle,self.public)['assets']['index.html'],
                         gate.sha(b'index.html'))

    def test_tampered_archive(self):
        self.bundle_with((k,b if k!='index.html' else b'old') for k,b in self.files.items())
        with self.assertRaisesRegex(ValueError,'exactly match'):
            gate.verify_archive(self.bundle,self.public)

    def test_duplicate_and_extra_members(self):
        for extra in [('index.html',b'index.html'),('extra.html',b'extra'),('../escape',b'extra')]:
            with self.subTest(extra=extra):
                self.bundle_with([*self.files.items(),extra])
                with self.assertRaises(ValueError):
                    gate.verify_archive(self.bundle,self.public)

    def test_missing_required_asset(self):
        (self.public/'index.html').unlink()
        self.bundle_with(self.files.items())
        with self.assertRaisesRegex(ValueError,'Missing required'):
            gate.verify_archive(self.bundle,self.public)

    def test_live_payload_retry_and_wrong_site(self):
        from urllib.parse import urlsplit
        expected='https://test.invalid/repo/'
        reqs=[]
        def fetch(req, timeout):
            reqs.append(req.full_url)
            parsed=urlsplit(req.full_url)
            body=b'old' if parsed.query.endswith('-0') else pathlib.Path(parsed.path).name.encode()
            class Response(BytesIO):
                def geturl(self): return req.full_url
            return Response(body)
        data={'assets':{'index.html':gate.sha(b'index.html')}}
        gate.verify_live(data,expected,expected,'run',attempts=2,delay=0,fetch=fetch)
        self.assertEqual(len(reqs),2)
        with self.assertRaisesRegex(ValueError,'did not match'):
            gate.verify_live(data,expected,expected,'run',attempts=1,delay=0,fetch=fetch)
        with self.assertRaisesRegex(ValueError,'Unexpected live'):
            gate.verify_live(data,'https://elsewhere.invalid/',expected,'run',fetch=fetch)
