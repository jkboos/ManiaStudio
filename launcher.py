"""Keep the local server alive only while this launch window is open."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import webbrowser
from studio.process_tree import ProcessTree, launcher_mutex, kernel

ROOT=Path(__file__).resolve().parent


def health(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health',timeout=.5) as response:
            return json.load(response).get('app')=='mania-studio'
    except (OSError,ValueError,urllib.error.URLError):return False


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--workspace',type=Path,default=ROOT/'workspace')
    args=parser.parse_args();workspace=args.workspace.resolve();workspace.mkdir(parents=True,exist_ok=True)
    url=f'http://localhost:{args.port}'
    if health(args.port):
        print('Mania Studio 已在執行，請使用原本的啟動視窗停止服務。',flush=True)
        if not args.no_browser:webbrowser.open(url)
        return 0
    name='Local\\ManiaStudio_'+hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]+'_'+str(args.port)
    mutex,owner=launcher_mutex(name)
    if not owner:
        kernel.CloseHandle(mutex)
        print('另一個啟動視窗正在準備 Mania Studio。',flush=True)
        return 0
    tree=None;child=None
    pid_file=workspace/'server.pid'
    try:
        tree=ProcessTree()
        env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
        with (workspace/'server.stdout.log').open('w',encoding='utf-8') as out, (workspace/'server.stderr.log').open('w',encoding='utf-8') as err:
            print('正在啟動 Mania Studio…',flush=True)
            child=tree.start(ROOT/'server.py',['--port',args.port,'--workspace',workspace],cwd=ROOT,env=env,stdout=out,stderr=err)
            pid_file.write_text(str(child.pid),encoding='ascii')
            deadline=time.monotonic()+30
            while not health(args.port):
                if child.poll() is not None or time.monotonic()>deadline:
                    raise RuntimeError('啟動失敗，請查看 workspace/server.stderr.log。')
                time.sleep(.25)
            if child.poll() is not None:raise RuntimeError('服務未能啟動，連接埠可能已被使用。')
            print(f'\nMania Studio 已啟動：{url}\n\n保留此視窗即可使用。\n關閉此視窗或按 Ctrl+C，將停止服務及進行中的下載／生成。\n',flush=True)
            if not args.no_browser:webbrowser.open(url)
            return child.wait()
    except KeyboardInterrupt:
        print('\n正在停止 Mania Studio…',flush=True)
        if child:
            try:child.wait(timeout=3)
            except (subprocess.TimeoutExpired,KeyboardInterrupt):pass
        return 0
    except Exception as exc:
        print(str(exc),flush=True);return 1
    finally:
        if tree:tree.close()
        if child:
            child.wait()
            if pid_file.exists() and pid_file.read_text().strip()==str(child.pid):pid_file.unlink()
        kernel.CloseHandle(mutex)


if __name__=='__main__':raise SystemExit(main())
