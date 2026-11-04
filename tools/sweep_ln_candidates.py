"""Compare candidate sampling/conditioning at identical rhythm and LN plans."""
import os
from pathlib import Path
import sys
import json
import numpy as np
import torch
APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP/'runtime'));os.chdir(APP/'runtime')
from style_decode import decode_batch
from technique_output_adapter import load_adapter
from chart_pressure import head_events, local_pressure_summary
from osu_export import serialize_osu, calculated_stars

torch.set_num_threads(4)
cache=np.load(APP/'workspace/qa/altitude_requests.npz',allow_pickle=False)
metadata=json.loads(str(cache['metadata']))
original=json.loads((APP/'workspace/jobs/3fa3b10319ea461592c5c83903b185af/generated/generation_report.json').read_text())
requests=[];labels=[]
for offset in (0.,.5,1.,1.5):
    for i,values in enumerate(metadata):
        r=dict(values,stars=values['stars']+offset,techniques=cache['techniques'])
        for name in ('audio','times','ln_probabilities'):r[name]=cache[f'{i}_{name}']
        requests.append(r);labels.append(dict(condition_stars=r['stars'],original_candidate=i))
device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
model,_=load_adapter(Path('runs/technique_adapter_v2/epoch_complete.pt'),device)
model.technique_strength=.35
print('Decoding '+str(len(requests))+' candidates',flush=True)
charts,diagnostics=decode_batch(model,requests,device,1337)
result=[];texts=[]
for i,notes in enumerate(charts):
    text=serialize_osu(notes,4,'audio.mp3','Altitude diagnostic',3.5,original['timing'])
    stars=calculated_stars(text)
    pressure=local_pressure_summary(*head_events(notes),4)
    row=dict(labels[i],candidate=i,stars=stars,ln_fraction=sum(n[3]=='hold' for n in notes)/len(notes),
             objects=len(notes),pressure=pressure['overlap_p95'],pressure_max=pressure['overlap_max'])
    result.append(row);texts.append(dict(candidate=i,osu_text=text))
(APP/'workspace/qa/ln_sweep.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
(APP/'workspace/qa/ln_sweep_charts.json').write_text(json.dumps(texts),encoding='utf-8')
print(json.dumps(sorted(result,key=lambda r:abs(r['stars']-3.5))[:15],indent=2),flush=True)
