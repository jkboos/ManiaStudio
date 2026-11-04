"""Package only the selected control pipeline and the local web application."""
import ast
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RHYTHM = 'runs/full_epoch_large/epoch_complete.pt'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runtime_dependencies():
    """Include local imports plus the adapter's hash-checked source sidecar.

    The entry wrapper is added separately: its inactive legacy branch must not
    pull an entire alternative generation pipeline into a control-only bundle.
    """
    pending = ['control_generate', 'prepare_dataset', 'technique_adapter_data']
    found = set()
    while pending:
        module = pending.pop()
        if module in found:
            continue
        path = ROOT/'runtime'/(module+'.py')
        found.add(module)
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            names = ([node.module] if isinstance(node,ast.ImportFrom) and node.module else
                     [n.name for n in node.names] if isinstance(node,ast.Import) else [])
            for name in names:
                name = name.split('.')[0]
                if (ROOT/'runtime'/(name+'.py')).is_file() and name not in found:
                    pending.append(name)
    return {'runtime/'+name+'.py' for name in found} | {'runtime/portable_generate.py'}


def bundle_files():
    control = json.loads((ROOT/'control_backend.json').read_text(encoding='utf-8'))
    files = {'Start.cmd','Start.ps1','Setup.ps1','server.py','launcher.py','requirements.txt',
             'control_backend.json','frozen_backend.json','download_dependencies.json','runtime_policy.json'}
    files |= runtime_dependencies()
    files |= {'runtime/'+control['checkpoint'], 'runtime/'+RHYTHM,
              'runtime/data/features/normalization.json',
              'runtime/data/techniques_v1/config.json','runtime/data/techniques_v1/ready.json',
              'bin/node.exe','bin/ffmpeg.exe','bin/ffprobe.exe'}
    for folder,extensions in [('studio',{'.py'}),('web',{'.html','.css','.js','.svg'}),('licenses',{'.txt'})]:
        files |= {p.relative_to(ROOT).as_posix() for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in extensions}
    sources = {name:ROOT/name for name in files}
    python_manifest=json.loads((ROOT/'python_runtime.json').read_text(encoding='utf-8'))
    sources['python_runtime.json']=ROOT/'python_runtime.json'
    for name,expected in python_manifest['files'].items():
        path=ROOT/'python'/name
        if sha(path)!=expected:raise ValueError(f'Bundled Python changed: {name}')
        sources['python/'+name]=path
    sources['README.md'] = ROOT/'PACKAGE.md'
    return sources

def main():
    manifest = json.loads((ROOT/'frozen_backend.json').read_text(encoding='utf-8'))
    sources = bundle_files()
    policy = json.loads((ROOT/'runtime_policy.json').read_text(encoding='utf-8'))
    if policy['decoder'] != 'control':
        raise ValueError('This bundle supports the control policy only')
    for path in sources.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    for group in ('models','python_snapshot'):
        for name,expected in manifest[group].items():
            if 'runtime/'+name in sources and sha(ROOT/'runtime'/name) != expected:
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
    destination = ROOT/'dist/ManiaStudio-control-portable.zip'
    destination.parent.mkdir(exist_ok=True)
    models = sorted(name for name in sources if name.endswith('.pt'))
    assert models == sorted(['runtime/'+control['checkpoint'],'runtime/'+RHYTHM])
    details = dict(version='ManiaStudio-control-portable',policy=policy['version'],
                   python_bundled=True,third_party_python_packages_bundled=False,dependencies_install_on_first_launch=True,
                   model_roles={models[0]:'control key placement and LN generation' if 'control_v1' in models[0] else 'required audio onset model',
                                models[1]:'control key placement and LN generation' if 'control_v1' in models[1] else 'required audio onset model'},
                   files={name:dict(bytes=p.stat().st_size,sha256=sha(p)) for name,p in sorted(sources.items())})
    temporary = destination.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,path in sorted(sources.items()):
            assert '/site-packages/' not in name
            archive.write(path,'mania_studio/'+name)
        archive.writestr('mania_studio/bundle_manifest.json',json.dumps(details,indent=2))
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip() is not None:
            raise ValueError('Package integrity check failed')
        for name,info in details['files'].items():
            if hashlib.sha256(archive.read('mania_studio/'+name)).hexdigest()!=info['sha256']:
                raise ValueError(f'Packaged file changed: {name}')
    temporary.replace(destination)
    destination.with_suffix('.zip.sha256').write_text(sha(destination)+'  '+destination.name+'\n',encoding='ascii')
    print(f'{destination} ({destination.stat().st_size/1048576:.1f} MB)')
    print(json.dumps(dict(models=models,files=len(sources)+1)))

if __name__ == '__main__':
    main()
