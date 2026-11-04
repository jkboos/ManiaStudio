"""Extract the shipping archive elsewhere and generate a real 7K chart."""
from pathlib import Path
import json
import os
import subprocess
import sys
import zipfile
import soundfile as sf

APP=Path(__file__).resolve().parents[1]
QA=APP/'workspace/qa'
target=QA/'relocated_bundle'
with zipfile.ZipFile(APP/'dist/mania-studio.zip') as archive:
    assert not any('/workspace/' in name or '/.venv/' in name for name in archive.namelist())
    archive.extractall(target)
copied=target/'mania_studio'
job=copied/'workspace/portable_job'
job.mkdir(parents=True,exist_ok=True)
audio=next(APP.parent.glob('*Jack-in-the-VOX.mp3'))
with sf.SoundFile(audio) as f:
    f.seek(30*f.samplerate)
    samples=f.read(24*f.samplerate)
    sf.write(job/'sample.wav',samples,f.samplerate)
request=dict(audio_id='a'*32,background_id=None,keys=7,stars=3.0,techniques=[],reduce_jacks=False,
             metadata=dict(title='Portable 7K',artist='Test',title_romanized='',artist_romanized='',
                           creator='Mania Studio',version='7K - 3.0 stars',source='',tags=''))
(job/'request.json').write_text(json.dumps(dict(request=request,audio_path=str(job/'sample.wav'),background_path=None)),encoding='utf-8')
env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8',OMP_NUM_THREADS='4')
with (QA/'portable.log').open('w',encoding='utf-8') as log:
    completed=subprocess.run([sys.executable,'-u',str(copied/'runtime/portable_generate.py'),str(job)],
                             cwd=QA,env=env,stdout=log,stderr=subprocess.STDOUT)
assert completed.returncode==0,(QA/'portable.log').read_text(encoding='utf-8')[-6000:]
result=json.loads((job/'export/result.json').read_text(encoding='utf-8'))
assert result['keys']==7 and result['validated'] and result['background_file'] is None
with zipfile.ZipFile(job/'export/beatmap.osz') as archive:
    assert len(archive.namelist())==2
print(json.dumps({key:result[key] for key in ['keys','actual_stars','taps','holds','validated']}))
