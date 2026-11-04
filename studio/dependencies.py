"""First-run setup using only the bundled Python standard library."""
import importlib
import importlib.util
import json
import msvcrt
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
MODULES=('flask','PIL','mutagen','torch','numpy','scipy','soundfile','rosu_pp_py','yt_dlp','yt_dlp_ejs')


def check(quiet=False):
    failed=[]
    for name in MODULES:
        try:importlib.import_module(name)
        except (ImportError,OSError) as exc:failed.append(f'{name}: {exc}')
    if failed and not quiet:
        print('Dependencies need setup:\n'+'\n'.join(failed),flush=True)
    return not failed


def run(*args):
    subprocess.run([sys.executable,*args],cwd=ROOT,check=True)


def install():
    folder=ROOT/'workspace/setup';folder.mkdir(parents=True,exist_ok=True)
    with (folder/'install.lock').open('a+b') as lock:
        lock.write(b'0');lock.flush();lock.seek(0)
        announced=False
        while True:
            try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);break
            except OSError:
                if not announced:print('Another setup is running. Waiting...',flush=True);announced=True
                time.sleep(1)
        try:
            # Re-check in a fresh interpreter; failed imports should not poison
            # this process after pip finishes installing native extensions.
            if subprocess.run([sys.executable,'-m','studio.dependencies','check','--quiet'],cwd=ROOT).returncode==0:
                print('Dependencies are already installed.',flush=True);return
            print('First-time setup: downloading Python packages. Internet access and several GB of free space are required.',flush=True)
            if importlib.util.find_spec('pip') is None:
                print('Installing pip...',flush=True)
                bootstrap=folder/'get-pip.py'
                with urllib.request.urlopen('https://bootstrap.pypa.io/get-pip.py',timeout=60) as response:
                    bootstrap.write_bytes(response.read())
                run(str(bootstrap),'--no-warn-script-location','--disable-pip-version-check')
            run('-m','pip','--isolated','install','--disable-pip-version-check','--no-warn-script-location',
                '--only-binary=:all:','torch==2.8.0','--index-url','https://download.pytorch.org/whl/cu126')
            run('-m','pip','--isolated','install','--disable-pip-version-check','--no-warn-script-location',
                '--only-binary=:all:','--index-url','https://pypi.org/simple','-r',str(ROOT/'requirements.txt'))
            run('-m','studio.dependencies','check')
            (folder/'installed.json').write_text(json.dumps(dict(python=sys.version,executable=sys.executable,
                completed_at=time.time()),indent=2),encoding='utf-8')
            print('Setup complete. Starting Mania Studio...',flush=True)
        finally:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)


if __name__=='__main__':
    try:
        if len(sys.argv)>1 and sys.argv[1]=='install':install()
        else:raise SystemExit(0 if check('--quiet' in sys.argv) else 1)
    except (OSError,subprocess.CalledProcessError) as exc:
        print(f'Setup did not finish: {exc}\nCheck your connection and free disk space, then open Start.cmd again to retry.',flush=True)
        raise SystemExit(1)
