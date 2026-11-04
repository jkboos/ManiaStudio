"""Read-only chart diagnostics against comparable training charts.

These measurements describe timing and pattern statistics, not a human skill
rating. Candidate files and completed exports are never modified.
"""
from pathlib import Path
import gzip
import json
import math
import sys
import numpy as np

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP/'runtime'))
from prepare_dataset import parse_chart
from chart_pressure import head_events


def windows(notes,keys,width=1000,step=250):
    starts=np.asarray([n[0] for n in notes],dtype=float)
    end=max(n[1] for n in notes)
    grid=np.arange(starts.min(),max(starts.min()+1,end-width+1),step)
    counts=np.stack([np.searchsorted(np.array([n[0] for n in notes if n[2]==lane]),grid+width,side='left')-
                     np.searchsorted(np.array([n[0] for n in notes if n[2]==lane]),grid,side='left') for lane in range(keys)],axis=1)
    return grid,counts


def measurements(notes,keys):
    notes=sorted(notes)
    grid,counts=windows(notes,keys)
    _,four=windows(notes,keys,4000,1000)
    total=counts.sum(1)
    chains=[];short_releases=[];released=0
    for lane in range(keys):
        column=[n for n in notes if n[2]==lane]
        chain=1
        for a,b in zip(column,column[1:]):
            chain=chain+1 if b[0]-a[0]<=160 else 1
            chains.append((chain,b[0],lane))
            if a[3]=='hold':
                released+=1
                if b[0]-a[1]<80:short_releases.append(dict(time_s=b[0]/1000,lane=lane,gap_ms=b[0]-a[1]))
    positive=total[total>0]
    m=dict(max_heads_1s=int(total.max()),p95_heads_1s=float(np.percentile(total,95)),
           max_lane_heads_1s=int(counts.max()),max_lane_heads_4s=int(four.max()),
           lane_overload_window_fraction=float(np.mean(counts.max(1)>=7)),
           p95_to_median_density=float(np.percentile(positive,95)/max(1,np.median(positive))),
           top10pct_density_share=float(np.sort(total)[-max(1,len(total)//10):].sum()/max(1,total.sum())),
           longest_lane_chain_160ms=max([x[0] for x in chains],default=1),
           heads_in_chain_ge3_fraction=sum(x[0]>=3 for x in chains)/len(notes),
           release_to_head_under80ms_fraction=len(short_releases)/max(1,released))
    top=[]
    for i in np.argsort(total)[::-1]:
        if all(abs(grid[i]/1000-r['start_s'])>=4 for r in top):
            top.append(dict(start_s=float(grid[i]/1000),heads=int(total[i]),lane_counts=counts[i].tolist()))
        if len(top)==8:break
    return m,dict(density_peaks=top,longest_chains=sorted(chains,reverse=True)[:8],short_releases=short_releases[:12])


COUNTS=np.array([int(i).bit_count() for i in range(128)])
CHOICES=np.array([math.comb(7,k) for k in range(8)])
def transition_counts(notes):
    times,masks=head_events(notes)
    bucket=np.searchsorted([100,150,200],np.diff(times),side='left')
    histogram=np.zeros((4,128,128),dtype=np.int64)
    np.add.at(histogram,(bucket,masks[:-1],masks[1:]),1)
    return histogram,bucket,masks


def surprise(notes,history,leave_out=False):
    own,bucket,masks=transition_counts(notes)
    reference=history-own if leave_out else history
    denominator=np.stack([reference[:,:,COUNTS==k].sum(-1) for k in range(8)],axis=-1)
    p=(reference[bucket,masks[:-1],masks[1:]]+1)/(denominator[bucket,masks[:-1],COUNTS[masks[1:]]]+CHOICES[COUNTS[masks[1:]]])
    return float(np.mean(-np.log(p)))


def main():
    job_id=sys.argv[1]
    root=APP/'workspace/jobs'/job_id
    job=json.loads((root/'job.json').read_text(encoding='utf-8'))
    notes=parse_chart(root/'export/beatmap.osu')['notes']
    request=job['request'];keys=request['keys'];stars=request['stars']
    fraction=sum(n[3]=='hold' for n in notes)/len(notes)
    rows=json.loads((APP.parent/'data/patterns_v1/train.json').read_text(encoding='utf-8'))
    peers=[r for r in rows if r['key_count']==keys and abs(r['star_rating']-stars)<=.5
           and not r['dan_style'] and abs(r['ln_ratio']-fraction)<=.15]
    metrics,detail=measurements(notes,keys)
    reference=[];peer_notes=[]
    histogram=np.zeros((4,128,128),dtype=np.int64)
    for row in peers:
        with gzip.open(row['chart_file'],'rt',encoding='utf-8') as source:
            ns=json.load(source)['notes']
        m,_=measurements(ns,keys);reference.append(m);peer_notes.append(ns)
        if keys==7:histogram+=transition_counts(ns)[0]
    if keys==7:
        metrics['transition_surprise_nats']=surprise(notes,histogram)
        for m,ns in zip(reference,peer_notes):m['transition_surprise_nats']=surprise(ns,histogram,True)
    comparisons={}
    for name,value in metrics.items():
        values=np.array([r[name] for r in reference])
        comparisons[name]=dict(generated=value,peer_median=float(np.median(values)),peer_p90=float(np.percentile(values,90)),
                               generated_percentile=float(100*np.mean(values<=value)))
    result=dict(job_id=job_id,title=request['metadata']['title'],keys=keys,target_stars=stars,
                actual_stars=job['result']['actual_stars'],ln_fraction=fraction,reference_charts=len(peers),
                criteria='training charts, same keys, within 0.5 stars, within 0.15 LN fraction, excluding dan names',
                comparisons=comparisons,details=detail,
                limitations=['Percentiles are relative to this selected corpus, not a difficulty grade.',
                             'Transition rarity does not establish physical difficulty or musical correctness.'])
    output=APP/'workspace/qa/local_burden_analysis.json';output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
