"""Repair an existing generated chart locally, preserving its rhythm and LNs."""
import argparse
import json
from pathlib import Path
import re
import shutil
import zipfile

import numpy as np
import torch

from audio_features import FeatureSpec,read_mono,resample_audio,iter_log_mel,sha256_file
from technique_output_adapter import load_adapter as load_pattern_checkpoint
from technique_data import TechniqueStore, AXES
from pattern_selection import repetition_metrics
from chart_pressure import head_events, head_pressure, local_pressure_summary
from requested_selection import multiscale_pressure
from generate_frames import alignment_proxy
from fixed_timing import onset_envelope
import subprocess
from short_jacks import ModelLaneScorer,repair_short_jacks
from lane_history import pattern_metrics
from prepare_dataset import parse_chart
from osu_export import serialize_osu,calculated_stars


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--min-head-gap-ms',type=float,default=60.)
    p.add_argument('--min-release-gap-ms',type=float,default=40.)
    args=p.parse_args()
    if args.output.exists() or not all(np.isfinite(v) and v>=0 for v in (args.min_head_gap_ms,args.min_release_gap_ms)):
        p.error('use new output and finite nonnegative gaps')
    source_report=args.source/'generation_report.json'
    parent=json.loads(source_report.read_text(encoding='utf-8'))
    path=args.source/parent['osu_file']
    chart=parse_chart(path)
    if chart['errors']:raise ValueError(chart['errors'])
    audio_path=args.source/chart['general']['AudioFilename']
    if sha256_file(audio_path)!=parent['audio_sha256']:raise ValueError('audio changed')
    device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    torch.set_num_threads(4)
    model,saved=load_pattern_checkpoint(Path(parent['pattern_checkpoint']),device)
    store=TechniqueStore()
    assert store.config==saved['config']['technique_config']
    vector=store.normalize([parent['technique_profile']['raw'][a] for a in AXES],parent['keys'])
    model.technique_strength=parent['technique_strength']
    model.set_techniques(torch.tensor(vector[None],device=device))
    feature_root=Path(saved['config']['data_report']['features'])
    if sha256_file(feature_root/'normalization.json')!=saved['config']['normalization_sha256']:
        raise ValueError('normalization changed')
    norm=json.loads((feature_root/'normalization.json').read_text(encoding='utf-8'))
    spec=FeatureSpec(**json.loads((feature_root/'feature_config.json').read_text(encoding='utf-8'))['spec'])
    analysis_path=Path(parent.get('analysis_audio_path',str(audio_path))) if parent.get('analysis_scope','all')!='rhythm' else audio_path
    if 'analysis_audio_sha256' in parent and analysis_path!=audio_path:
        if sha256_file(analysis_path)!=parent['analysis_audio_sha256']:raise ValueError('analysis audio changed')
    wave,sr,_=read_mono(analysis_path)
    mel=np.concatenate([v for _,v in iter_log_mel(resample_audio(wave,sr,spec))])
    normalized=(mel.astype(np.float16).astype(np.float32)-np.array(norm['mean'],dtype=np.float32))/np.array(norm['std'],dtype=np.float32)
    scorer=ModelLaneScorer(model,normalized,parent['keys'],parent['target_stars'],int(parent['style']=='dan'),device)
    notes,repairs=repair_short_jacks(chart['notes'],parent['keys'],scorer,args.min_head_gap_ms,args.min_release_gap_ms)
    old=path.read_text(encoding='utf-8')
    head=old.split('[HitObjects]')[0]
    head=re.sub(r'^Version:.*$',f"Version:{parent['keys']}K Technique adapter playtest target {parent['target_stars']:.2f} stars",head,flags=re.M)
    objects=serialize_osu(notes,parent['keys'],audio_path.name,'',parent['target_stars'],parent['timing']).split('[HitObjects]')[1]
    text=head+'[HitObjects]'+objects
    stars=calculated_stars(text)
    scored=subprocess.run(['node','score_techniques.mjs'],input=json.dumps([dict(candidate=0,osu_text=text)]),text=True,encoding='utf-8',capture_output=True,check=True)
    technique=json.loads(scored.stdout)[0]
    assert technique['status']=='ok'
    actual_vector=store.normalize([technique['raw'][a] for a in AXES],parent['keys'])
    indices=[AXES.index(a) for a in parent['technique_profile']['requested']]
    distance=float(np.mean((actual_vector[indices]-vector[indices])**2))
    report=dict(parent)
    previous=next(c for c in parent['candidates'] if c['candidate']==parent['selected_candidate'])
    candidate=dict(previous,candidate=0,actual_stars=stars,absolute_star_error=abs(stars-parent['target_stars']),
                   pattern_metrics=pattern_metrics(notes,parent['keys']), local_repair=repairs,
                   technique_analysis=technique,technique_distance=distance,
                   repetition_metrics=repetition_metrics(notes,parent['keys']),head_pressure=head_pressure(*head_events(notes),parent['keys']),
                   local_pressure=local_pressure_summary(*head_events(notes),parent['keys']),alignment_proxy=alignment_proxy(notes,onset_envelope(mel)))
    report.update(actual_stars=stars,selected_candidate=0,candidates=[candidate],
                  original_selected_candidate=parent['selected_candidate'],
                  technique_analysis=technique,technique_distance=distance,
                  repetition_metrics=candidate['repetition_metrics'],head_pressure=candidate['head_pressure'],local_pressure=candidate['local_pressure'],
                  selection=dict(policy='preserve_selected_candidate_then_local_gap_repair',parent_selection=parent['selection'],selected_candidate=0,reranked_after_repair=False),
                  parent_generation_report=str(source_report.resolve()),parent_report_sha256=sha256_file(source_report),
                  parent_osu_sha256=sha256_file(path),local_repair=repairs,
                  local_repair_code_sha256={n:sha256_file(Path(__file__).with_name(n)) for n in ('short_jacks.py','repair_output_adapter.py')})
    report['limitations']=[x for x in parent['limitations'] if x!='No hand-written jack penalties are applied.']
    report['limitations'].append('Configurable local gap guard; it is not a universal playability standard.')
    report['multiscale_pressure']=multiscale_pressure(notes,parent['keys'])
    report['candidates'][0]['multiscale_pressure']=report['multiscale_pressure']
    report['post_repair_pressure_recomputed']=True
    report['post_repair_pressure_code_sha256']=sha256_file('requested_selection.py')
    args.output.mkdir(parents=True)
    (args.output/parent['osu_file']).write_text(text,encoding='utf-8')
    shutil.copy2(audio_path,args.output/audio_path.name)
    with zipfile.ZipFile(args.output/parent['osz_file'],'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name in (parent['osu_file'],audio_path.name):z.write(args.output/name,name)
    (args.output/'generation_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'keys':parent['keys'],'before_stars':parent['actual_stars'],'actual_stars':stars,'repairs':repairs},indent=2))


if __name__=='__main__':main()
