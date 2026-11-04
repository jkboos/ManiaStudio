import json
from pathlib import Path
import subprocess
import sys
import pytest
from studio import domain
from studio.youtube import AudioImports


def test_transient_replace_denial_retries_without_truncating(tmp_path,monkeypatch):
    path=tmp_path/'import.json';path.write_text('{"old":true}',encoding='utf-8')
    original=domain.os.replace;attempts=[]
    def replace(source,destination):
        attempts.append(Path(source))
        if len(attempts)<3:
            assert json.loads(path.read_text())=={'old':True}
            raise PermissionError(13,'simulated Windows sharing conflict')
        original(source,destination)
    monkeypatch.setattr(domain.os,'replace',replace)
    monkeypatch.setattr(domain.time,'sleep',lambda _:None)
    domain.write_json(path,{'completed':True})
    assert len(attempts)==3 and attempts[0].name!='import.tmp'
    assert json.loads(path.read_text())=={'completed':True}
    assert not list(tmp_path.glob('*.tmp'))


def test_persistent_denial_is_bounded_and_preserves_original(tmp_path,monkeypatch):
    path=tmp_path/'import.json';path.write_text('{"old":true}',encoding='utf-8')
    attempts=[]
    def denied(*args):
        attempts.append(1);raise PermissionError(13,'denied')
    monkeypatch.setattr(domain.os,'replace',denied)
    monkeypatch.setattr(domain.time,'sleep',lambda _:None)
    with pytest.raises(PermissionError):domain.write_json(path,{'new':True})
    assert len(attempts)==9 and json.loads(path.read_text())=={'old':True}
    assert not list(tmp_path.glob('*.tmp'))


def test_concurrent_writers_use_distinct_temp_files(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    path=tmp_path/'state.json'
    def write(i):domain.write_json(path,{'index':i,'values':[i]*200})
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(write,range(20)))
    result=json.loads(path.read_text())
    assert result['values']==[result['index']]*200
    assert not list(tmp_path.glob('*.tmp'))


def test_progress_write_failure_does_not_interrupt_import(tmp_path,monkeypatch):
    import studio.youtube as youtube
    app=Path(__file__).resolve().parents[1]
    manager=AudioImports(app,tmp_path,run_worker=False)
    item=manager.submit('https://youtu.be/jNQXAC9IVRw',True)
    result=manager.root/item['id']/'result.json'
    original_popen=subprocess.Popen
    worker="import json,sys,time; from pathlib import Path; print(json.dumps({'import_stage':'video_downloading','progress':70}),flush=True); time.sleep(.1); Path(sys.argv[1]).write_text(json.dumps({'asset':{'id':'completed-media'}})); print(json.dumps({'import_stage':'video_packaging'}),flush=True)"
    monkeypatch.setattr(youtube.subprocess,'Popen',lambda args,**kwargs:original_popen([sys.executable,'-u','-c',worker,str(result)],**kwargs))
    original_write=youtube.write_json
    def write(path,data):
        if path.name=='import.json' and data.get('stage')=='video_downloading':
            raise PermissionError(13,'simulated progress-file denial')
        return original_write(path,data)
    monkeypatch.setattr(youtube,'write_json',write)
    manager.run(item['id'])
    final=manager.get(item['id'])
    assert final['status']=='completed' and final['asset']['id']=='completed-media'
    assert json.loads((result.parent/'import.json').read_text())['status']=='completed'
    assert 'Progress snapshot deferred' in (result.parent/'worker.log').read_text()
    assert not manager.inflight and not manager.processes
