"""Exercise real Windows process ownership without touching the user's server."""
import ctypes
from ctypes import wintypes as W
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from studio.process_tree import kernel

APP=Path(__file__).resolve().parents[1]
kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
kernel.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];kernel.WaitForSingleObject.restype=W.DWORD


def test_launcher_death_kills_server_and_detached_descendant(tmp_path):
    script=tmp_path/'worker.py';marker=tmp_path/'pids.json'
    script.write_text("import json,os,subprocess,sys,time\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],creationflags=subprocess.CREATE_NO_WINDOW)\nPath(sys.argv[1]).write_text(json.dumps([os.getpid(),p.pid]))\ntime.sleep(60)\n")
    code="from studio.process_tree import ProcessTree; import sys,time; tree=ProcessTree(); p=tree.start(sys.argv[1],[sys.argv[2]]); p.wait()"
    parent=subprocess.Popen([sys.executable,'-c',code,str(script),str(marker)],cwd=APP,creationflags=subprocess.CREATE_NO_WINDOW)
    handles=[]
    try:
        deadline=time.monotonic()+10
        while not marker.exists() and time.monotonic()<deadline:time.sleep(.05)
        assert marker.exists()
        for pid in json.loads(marker.read_text()):
            handle=kernel.OpenProcess(0x100000,False,pid) # SYNCHRONIZE
            assert handle;handles.append(handle)
            assert kernel.WaitForSingleObject(handle,0)==258
        parent.kill();parent.wait(timeout=5)
        assert all(kernel.WaitForSingleObject(h,5000)==0 for h in handles)
    finally:
        if parent.poll() is None:parent.kill();parent.wait()
        for handle in handles:kernel.CloseHandle(handle)


def test_managed_server_and_duplicate_launch(tmp_path):
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    args=[sys.executable,'-u',str(APP/'launcher.py'),'--no-browser','--port',str(port),'--workspace',str(tmp_path)]
    process=subprocess.Popen(args,cwd=APP,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    def ready():
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health',timeout=.2) as response:return json.load(response)['app']=='mania-studio'
        except OSError:return False
    try:
        deadline=time.monotonic()+15
        while not ready() and time.monotonic()<deadline:time.sleep(.1)
        assert ready()
        server_pid=(tmp_path/'server.pid').read_text()
        second=subprocess.run(args,cwd=APP,capture_output=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
        assert second.returncode==0 and process.poll() is None
        assert (tmp_path/'server.pid').read_text()==server_pid
        process.kill();process.wait(timeout=5)
        deadline=time.monotonic()+5
        while ready() and time.monotonic()<deadline:time.sleep(.05)
        assert not ready()
    finally:
        if process.poll() is None:process.kill();process.wait()
