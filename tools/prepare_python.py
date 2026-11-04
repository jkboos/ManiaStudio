"""Fetch the official app-local CPython runtime, without third-party packages."""
from pathlib import Path
import hashlib
import json
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
VERSION='3.11.9'
URL=f'https://www.python.org/ftp/python/{VERSION}/python-{VERSION}-embed-amd64.zip'
# Published on the Python.org release page; SHA-256 is recorded after download.
PUBLISHED_MD5='6d9aa08531d48fcc261ba667e2df17c4'


def main():
    cache=ROOT/'workspace/build_cache';cache.mkdir(parents=True,exist_ok=True)
    archive=cache/f'python-{VERSION}-embed-amd64.zip'
    if not archive.exists():
        print('Downloading official embedded Python...',flush=True)
        with urllib.request.urlopen(URL,timeout=60) as response:
            archive.write_bytes(response.read())
    content=archive.read_bytes()
    if hashlib.md5(content).hexdigest()!=PUBLISHED_MD5:
        raise ValueError('Python archive differs from the published release checksum')
    destination=(ROOT/'python').resolve();destination.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        for name in names:
            if not (destination/name).resolve().is_relative_to(destination):raise ValueError('Unsafe archive path')
        z.extractall(destination)
    # Explicit application paths: do not depend on a system Python, PATH,
    # PYTHONPATH, registry settings, or a developer's virtual environment.
    (destination/'python311._pth').write_text('python311.zip\n.\nLib/site-packages\n..\n../runtime\n',encoding='ascii')
    manifest=dict(version=VERSION,architecture='amd64',source=URL,
                  archive_sha256=hashlib.sha256(content).hexdigest(),third_party_packages_bundled=False,
                  files={name:hashlib.sha256((destination/name).read_bytes()).hexdigest() for name in names if (destination/name).is_file()})
    (ROOT/'python_runtime.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(f'Prepared Python {VERSION}; application dependencies will install on first launch.',flush=True)


if __name__=='__main__':main()
