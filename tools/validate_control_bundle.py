"""Generate with the shipping bundle from an unrelated working directory."""
from pathlib import Path
import json
import os
import subprocess
import sys
import uuid
import zipfile

APP = Path(__file__).resolve().parents[1]
QA = APP/'workspace/qa/control_migration'


def main():
    destination = QA/('relocated_'+uuid.uuid4().hex[:8])
    destination.mkdir()
    with zipfile.ZipFile(APP/'dist/mania-studio.zip') as archive:
        assert not any('/workspace/' in n or '/.venv/' in n for n in archive.namelist())
        archive.extractall(destination)
    copied = destination/'mania_studio'
    previous = json.loads((QA/'api_validation.json').read_text())[0]
    source = QA/'api_check/jobs'/previous['id']
    job = destination/'job'
    job.mkdir()
    # Inputs may live anywhere; implementation/checkpoints must come from bundle.
    (job/'request.json').write_bytes((source/'request.json').read_bytes())
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8', OMP_NUM_THREADS='4')
    print('Generating full 4K song from extracted bundle...', flush=True)
    with (job/'worker.log').open('w',encoding='utf-8') as log:
        run = subprocess.run([sys.executable,'-u',str(copied/'runtime/portable_generate.py'),str(job)],
                             cwd=destination, env=env, stdout=log, stderr=subprocess.STDOUT)
    assert run.returncode==0, (job/'worker.log').read_text(encoding='utf-8')[-5000:]
    result = json.loads((job/'export/result.json').read_text(encoding='utf-8'))
    assert result['backend_version']=='studio-control-1'
    assert result['validated'] and abs(result['actual_stars']-6)<=.5
    assert (job/'export/beatmap.osu').read_bytes()==(source/'export/beatmap.osu').read_bytes()
    report = dict(relocated_root=str(copied), actual_stars=result['actual_stars'],
                  matches_original_export_byte_for_byte=True, full_song=True, runtime_self_contained=True)
    (QA/'bundle_validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    main()
