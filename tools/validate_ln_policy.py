"""Full export checks for the same three songs and 7K under the active policy."""
from pathlib import Path
import json
import subprocess
import sys

APP=Path(__file__).resolve().parents[1]
ROOT=APP/'workspace/qa/ln_policy_final'
ROOT.mkdir(exist_ok=True)
cases=[('start',next(APP.parent.glob('Star-t*.mp3')),4,2),
       ('demon',next(APP.parent.glob('*DEMON*mp3')),4,4),
       ('jack',next(APP.parent.glob('*Jack-in-the-VOX.mp3')),4,6),
       ('jack7k',next(APP.parent.glob('*Jack-in-the-VOX.mp3')),7,4)]
results=[]
for name,audio,keys,stars in cases:
    folder=ROOT/name;folder.mkdir()
    request=dict(audio_id='a'*32,background_id=None,keys=keys,stars=stars,
                 techniques=['tech','stream','LN'],reduce_jacks=True,
                 metadata=dict(title=audio.stem,artist='Unknown',title_romanized='',artist_romanized='',
                               creator='ManiaModel',version=f'{keys}K target {stars}',source='',tags=''))
    (folder/'request.json').write_text(json.dumps(dict(request=request,audio_path=str(audio),background_path=None)),encoding='utf-8')
    with (folder/'worker.log').open('w',encoding='utf-8') as log:
        p=subprocess.run([sys.executable,'-u',str(APP/'runtime/portable_generate.py'),str(folder)],stdout=log,stderr=subprocess.STDOUT)
    if p.returncode:raise RuntimeError((folder/'worker.log').read_text(encoding='utf-8')[-4000:])
    result=json.loads((folder/'export/result.json').read_text(encoding='utf-8'))
    assert result['validated'] and abs(result['actual_stars']-stars)<=.5
    fractions=[s['ln_fraction'] for s in result['ln_plan']['sections'] if s['notes']>=10]
    row=dict(song=name,keys=keys,target=stars,actual=result['actual_stars'],ln_fraction=result['ln_fraction'],
             section_min=min(fractions),section_max=max(fractions),backend=result['backend_version'])
    results.append(row);print(json.dumps(row),flush=True)
(ROOT/'summary.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
