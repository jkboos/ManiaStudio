"""Create a portable source/model bundle, excluding uploaded music and results."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def main():
    manifest = json.loads((ROOT/'frozen_backend.json').read_text(encoding='utf-8'))
    for group in ('models', 'python_snapshot'):
        for name, expected in manifest[group].items():
            path = ROOT/'runtime'/name
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f'Frozen backend changed: {name}')
    if hashlib.sha256((ROOT/'bin/node.exe').read_bytes()).hexdigest() != manifest['node_sha256']:
        raise ValueError('Bundled Node changed')
    control = json.loads((ROOT/'control_backend.json').read_text(encoding='utf-8'))
    for name, expected in ((control['checkpoint'], control['checkpoint_sha256']),
                           (control['decoder'], control['decoder_sha256'])):
        if hashlib.sha256((ROOT/'runtime'/name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'Control backend changed: {name}')
    dependencies = json.loads((ROOT/'download_dependencies.json').read_text(encoding='utf-8'))
    for name, expected in dependencies['binaries'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'Download dependency changed: {name}')
    destination = ROOT/'dist/mania-studio.zip'
    destination.parent.mkdir(exist_ok=True)
    excluded = {'.git', '.venv', 'workspace', '__pycache__', '.pytest_cache', 'dist', 'tests'}
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob('*')):
            relative = path.relative_to(ROOT)
            if relative.parts[0]=='tools' and path.name!='package.py':
                continue # Local experiment runners reference developer fixtures.
            if path.is_file() and not any(part in excluded for part in relative.parts):
                archive.write(path, Path('mania_studio')/relative)
    print(f'{destination} ({destination.stat().st_size/1048576:.1f} MB)')

if __name__ == '__main__':
    main()
