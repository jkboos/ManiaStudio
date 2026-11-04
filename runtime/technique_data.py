"""Sidecar technique labels with training-only normalization and profile lookup."""
import json
from pathlib import Path

import numpy as np

from audio_features import sha256_file
from pattern_data import PatternDataset
from epoch_data import FullEpochDataset

AXES=('speed','stamina','tech','jack','stream','LN')
ROOT=Path('data/techniques_v1')


def transformed(raw):
    value=np.asarray(raw,dtype=np.float32).copy()
    value[..., :2]=np.log1p(value[..., :2])
    return value


def prepare():
    labels=[json.loads(s) for s in (ROOT/'labels.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(labels)==6690 and len({r['id'] for r in labels})==6690
    by_id={r['chart_id']:r for r in labels if r['status']=='ok'}
    records=[];split_hashes={}
    for split in ('train','validation','test'):
        path=Path(f'data/patterns_v1/{split}.json');split_hashes[split]=sha256_file(path)
        for row in json.loads(path.read_text(encoding='utf-8')):
            label=by_id[row['chart_id']]
            assert label['keys']==row['key_count'] and label['osu_sha256']==row['osu_sha256']
            assert label['object_count']==row['object_count']
            records.append(dict(chart_id=row['chart_id'],keys=row['key_count'],split=split,
                                stars=row['star_rating'],raw=[label['raw'][a] for a in AXES],
                                osu_sha256=row['osu_sha256']))
    normalization={}
    for keys in (4,7):
        train=[r for r in records if r['keys']==keys and r['split']=='train']
        raw=np.array([r['raw'] for r in train]);x=transformed(raw)
        normalization[str(keys)]=dict(charts=len(train),mean=x.mean(0).tolist(),
                                      std=np.maximum(x.std(0),.05).tolist(),
                                      raw_quantiles={str(q):np.quantile(raw,q,axis=0).tolist() for q in (.2,.5,.8)})
    (ROOT/'ready.json').write_text(json.dumps(records,ensure_ascii=False),encoding='utf-8')
    config=dict(axes=list(AXES),normalization=normalization,fit_split='train',
                labels_sha256=sha256_file(ROOT/'labels.jsonl'),ready_sha256=sha256_file(ROOT/'ready.json'),
                source_split_sha256=split_hashes,upstream_commit='2811e5273f286f63b6f8300d0fda1eb7f85f19c1',
                semantics='Offline geometric proxies, not exact Mania Tracker MSD-derived UI tiles.',
                granularity='whole-chart profile; not independently annotated per section')
    (ROOT/'config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    report=dict(status='complete',source_charts=len(labels),analyzed=sum(r['status']=='ok' for r in labels),
                errors=[dict(id=r['id'],path=r['osu_path'],error=r['error']) for r in labels if r['status']!='ok'],
                ready_charts=len(records),splits={s:sum(r['split']==s for r in records) for s in split_hashes},
                normalization=config,source_hashes={p:sha256_file(p) for p in ('technique_analyzer.mjs','register_tracker.mjs','tracker_prism_flags.mjs')})
    (ROOT/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('normalization','source_hashes')},indent=2))


class TechniqueStore:
    def __init__(self,root=ROOT):
        root=Path(root)
        self.config=json.loads((root/'config.json').read_text())
        assert sha256_file(root/'ready.json')==self.config['ready_sha256']
        self.rows=json.loads((root/'ready.json').read_text(encoding='utf-8'))
        self.rows_by_id={r['chart_id']:r for r in self.rows}
        self.vectors={r['chart_id']:self.normalize(r['raw'],r['keys']) for r in self.rows}

    def normalize(self,raw,keys):
        norm=self.config['normalization'][str(keys)]
        return ((transformed(raw)-np.array(norm['mean']))/np.array(norm['std'])).astype(np.float32)

    def profile(self,keys,stars,request=''):
        train=[r for r in self.rows if r['split']=='train' and r['keys']==keys]
        peers=[r for r in train if abs(r['stars']-stars)<=.5]
        if len(peers)<24:peers=sorted(train,key=lambda r:abs(r['stars']-stars))[:64]
        values=np.array([r['raw'] for r in peers]);raw=np.median(values,axis=0)
        requested={}
        for term in filter(None,(s.strip() for s in request.split(','))):
            name,_,level=term.partition('=');name='LN' if name.lower()=='ln' else name.lower()
            if name not in AXES:raise ValueError(f'unknown technique: {name}')
            level=level.lower() or 'high';index=AXES.index(name)
            if level in ('low','medium','high'):
                value=float(np.quantile(values[:,index],dict(low=.2,medium=.5,high=.8)[level]))
            else:value=float(level)
            if not np.isfinite(value) or value<0 or (index>=2 and value>1):raise ValueError(f'invalid {name} value')
            raw[index]=value;requested[name]=level
        return self.normalize(raw,keys),dict(requested=requested,raw=dict(zip(AXES,raw.tolist())),
                reference_charts=len(peers),reference_split='train',soft_preferences=True)


class TechniquePatternDataset(PatternDataset):
    def __init__(self,root='data/patterns_v1',split='train'):
        super().__init__(root,split);self.techniques=TechniqueStore()
    def __getitem__(self,index):
        sample=super().__getitem__(index);ci=int(self.chunks[index,0])
        sample['techniques']=self.techniques.vectors[self.rows[ci]['chart_id']]
        return sample


class TechniqueEpochDataset(FullEpochDataset):
    def __init__(self,root='data/epoch_v2',seed=2026):
        super().__init__(root,seed);self.techniques=TechniqueStore()
    def __getitem__(self,index):
        sample=super().__getitem__(index)
        sample['techniques']=self.techniques.vectors[self.rows[sample['chart_index']]['chart_id']]
        return sample


if __name__=='__main__':prepare()
