"""Run the frozen generator with an isolated experimental LN planning decoder."""
import argparse
import json
import os
from pathlib import Path
import sys

APP=Path(__file__).resolve().parents[1]
RUNTIME=APP/'runtime'
sys.path.insert(0,str(RUNTIME));os.chdir(RUNTIME)
os.environ['PATH']=str(APP/'bin')+os.pathsep+os.environ.get('PATH','')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('audio',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--keys',type=int,default=4);p.add_argument('--stars',type=float,default=3.5)
    p.add_argument('--techniques',default='jack=low')
    p.add_argument('--seed',type=int,default=42)
    p.add_argument('--pattern-stars',type=float)
    p.add_argument('--capture',type=Path)
    p.add_argument('--onset-scale',type=float,default=1.)
    p.add_argument('--chord-prior',type=float)
    args=p.parse_args()
    import generate_output_adapter as generate
    import numpy as np
    import torch
    from technique_output_adapter import load_adapter
    from technique_data import TechniqueStore
    from ln_planning import audio_ln_plan, audio_chord_plan
    from style_decode import decode_batch
    store=TechniqueStore();_,profile=store.profile(args.keys,args.stars,args.techniques)
    target=profile['raw']['LN']
    loader=load_adapter
    def portable(path,device):
        model,saved=loader(path,device);saved['config']['data_report']['features']=str(RUNTIME/'data/features')
        return model,saved
    generate.load_pattern_checkpoint=portable
    original_peaks=generate.onset_peaks
    generate.onset_peaks=lambda values,threshold:original_peaks(values,threshold*args.onset_scale)
    original=generate.predict_song
    plans={}
    def predict(*a,**kw):
        prediction=original(*a,**kw);plans['values']=audio_ln_plan(prediction,args.keys,target)
        if args.chord_prior:plans['head_counts']=audio_chord_plan(prediction,args.keys,args.chord_prior)
        return prediction
    generate.predict_song=predict
    def decode(model,requests,device,seed):
        for request in requests:
            frames=np.clip(np.round(request['times']/10).astype(int),0,len(plans['values'])-1)
            request['ln_probabilities']=plans['values'][frames];request['ln_target']=target
            if args.chord_prior:request['head_counts']=plans['head_counts'][frames]
            if args.pattern_stars is not None:request['stars']=args.pattern_stars
        if args.capture:
            arrays={f'{i}_{name}':r[name] for i,r in enumerate(requests) for name in ('audio','times','ln_probabilities')}
            arrays['metadata']=np.array(json.dumps([{k:v for k,v in r.items() if k not in ('audio','times','ln_probabilities','techniques')} for r in requests]))
            arrays['techniques']=requests[0]['techniques']
            np.savez(args.capture,**arrays)
            raise SystemExit(0)
        return decode_batch(model,requests,device,seed)
    generate.decode_batch=decode
    sys.argv=['generate_output_adapter.py',str(args.audio),'--keys',str(args.keys),'--stars',str(args.stars),
              '--techniques',args.techniques,'--strength','.35','--selection','techniques-local',
              '--seed',str(args.seed),
              '--output',str(args.output),'--variant-label','audio LN plan v1']
    generate.main()

if __name__=='__main__':main()
