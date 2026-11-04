"""Technique control with the preferred legacy rhythm and frozen pattern backbone."""
import argparse
import json
from pathlib import Path
import shutil
import zipfile
import subprocess

import numpy as np
import torch

from audio_features import FeatureSpec,read_mono,resample_audio,iter_log_mel,sha256_file
from generate_frames import load_frame_checkpoint,predict_song,alignment_proxy
from frame_metrics import onset_peaks
from fixed_timing import onset_envelope,fit_fixed_timing,snap_nearby
from pattern_decode import decode_batch,request_from_audio
from technique_output_adapter import load_adapter as load_pattern_checkpoint
from pattern_data import CORE, CONTEXT
from short_jacks import ModelLaneScorer, repair_short_jacks
from lane_history import pattern_metrics
from pattern_selection import repetition_metrics, select_candidate
from chart_pressure import head_events, head_pressure, local_pressure_summary
from osu_export import serialize_osu,calculated_stars


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('audio',type=Path)
    p.add_argument('--analysis-audio',type=Path,help='Optional same-length audio fed to the models; exported playback audio stays original')
    p.add_argument('--analysis-scope',choices=('all','rhythm'),default='all',
                   help='Use alternate audio for both models or only the rhythm model')
    p.add_argument('--variant-label',default='technique adapter')
    p.add_argument('--checkpoint',type=Path,default=Path('runs/full_epoch_large/epoch_complete.pt'))
    p.add_argument('--patterns',type=Path,default=Path('runs/technique_adapter_v2/epoch_complete.pt'),help='Frozen-backbone technique adapter checkpoint, shared by 4K and 7K')
    p.add_argument('--keys',type=int,choices=(4,7),required=True)
    p.add_argument('--stars',type=float,required=True)
    p.add_argument('--techniques',default='preferred',help='Soft profile, e.g. stream=high,jack=low,LN=0.25, preferred for saved preferences, or off to reproduce the legacy baseline')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seed',type=int,default=42)
    p.add_argument('--style',choices=('normal','dan'),default='normal')
    p.add_argument('--selection',choices=('balanced','closest','pressure','techniques','techniques-local'),
                   help='Prefer fewer sustained rapid repetitions within approximate star tolerance, or closest stars')
    p.add_argument('--star-tolerance',type=float,help='Optional absolute star tolerance for candidate selection')
    p.add_argument('--technique-slack',type=float,default=.25,help='Allowed extra normalized technique distance for techniques-local selection')
    p.add_argument('--strength',type=float,default=1.,help='Technique adapter strength, 0 disables it, 1 is full trained strength')
    p.add_argument('--min-head-gap-ms',type=float,default=0.)
    p.add_argument('--min-release-gap-ms',type=float,default=0.)
    args=p.parse_args()
    if args.techniques=='preferred':
        args.techniques=json.loads(Path('generation_preferences.json').read_text(encoding='utf-8'))['preferred_techniques']
    bypass=args.techniques=='off' or args.strength==0
    args.selection=args.selection or ('closest' if bypass else 'techniques-local')
    if not np.isfinite(args.strength) or not 0<=args.strength<=1:
        p.error('strength must be between zero and one')
    if args.output.exists() or not np.isfinite(args.stars) or args.stars<=0:p.error('use new output and positive stars')
    if not all(np.isfinite(v) and v>=0 for v in (args.min_head_gap_ms,args.min_release_gap_ms)):
        p.error('gap preferences must be nonnegative and finite')
    if args.star_tolerance is not None and (not np.isfinite(args.star_tolerance) or args.star_tolerance<0):
        p.error('star tolerance must be nonnegative and finite')
    if not np.isfinite(args.technique_slack) or args.technique_slack<0:
        p.error('technique slack must be nonnegative and finite')
    torch.set_num_threads(4)
    device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    rhythm,saved=load_frame_checkpoint(args.checkpoint,device)
    pattern,pattern_saved=load_pattern_checkpoint(args.patterns,device)
    from technique_data import TechniqueStore
    from technique_integrity import validate_technique_sources
    store=TechniqueStore()
    if pattern_saved['config']['technique_config']!=store.config:
        raise ValueError('technique data differs from the trained adapter')
    if sha256_file(args.checkpoint)!=pattern_saved['config']['rhythm_sha256']:
        raise ValueError('use the frozen legacy rhythm checkpoint paired with this adapter')
    technique_provenance=validate_technique_sources(store.config)
    if bypass:
        technique_vector=np.zeros(6,dtype=np.float32);technique_profile=None
    else:
        technique_vector,technique_profile=store.profile(args.keys,args.stars,args.techniques)
    conditioned=not bypass
    if bypass and args.selection in ('techniques','techniques-local'):
        p.error('technique ranking requires a requested profile')
    pattern.technique_strength=args.strength
    pattern.set_techniques(torch.tensor(technique_vector[None],device=device))
    if args.keys not in pattern_saved['config'].get('allowed_generation_keys',[4,7]):
        raise ValueError('this pattern checkpoint is specialized for another key mode')
    cfg=saved['config'];norm=cfg['normalization'];spec=FeatureSpec(**cfg['feature_spec'])
    actual_norm=Path(pattern_saved['config']['data_report']['features'])/'normalization.json'
    if sha256_file(actual_norm)!=pattern_saved['config']['normalization_sha256']:
        raise ValueError('normalization changed')
    if json.loads(actual_norm.read_text(encoding='utf-8'))!=norm:
        raise ValueError('rhythm/pattern normalization mismatch')
    wave,sr,audio=read_mono(args.audio)
    signal=resample_audio(wave,sr,spec)
    original_signal=signal
    analysis_path=args.analysis_audio or args.audio
    if args.analysis_audio:
        analysis_wave,analysis_sr,_=read_mono(args.analysis_audio)
        analysis_signal=resample_audio(analysis_wave,analysis_sr,spec)
        if len(analysis_signal)!=len(signal):raise ValueError('analysis audio must have exactly the same resampled length')
        signal=analysis_signal
    mel=np.concatenate([v for _,v in iter_log_mel(signal)])
    envelope=onset_envelope(mel);timing=fit_fixed_timing(envelope)
    normalized=(mel.astype(np.float16).astype(np.float32)-np.array(norm['mean'],dtype=np.float32))/np.array(norm['std'],dtype=np.float32)
    pattern_features=normalized
    if args.analysis_audio and args.analysis_scope=='rhythm':
        original_mel=np.concatenate([v for _,v in iter_log_mel(original_signal)])
        pattern_features=(original_mel.astype(np.float16).astype(np.float32)-np.array(norm['mean'],dtype=np.float32))/np.array(norm['std'],dtype=np.float32)
    prediction=predict_song(rhythm,normalized,args.keys,args.stars,device)
    threshold=saved['evaluation']['global_onset_30ms']['threshold']
    requests=[]
    for factor in (.85,1.,1.15):
        peaks=onset_peaks(prediction['any_onset'],min(.9,threshold*factor))
        times=sorted({int(round(snap_nearby(float(frame*10),timing)[0])) for frame in peaks})
        times=[t for t in times if 0<=t<audio['duration_s']*1000]
        for temperature in (.7,.85,1.):
            requests.append(request_from_audio(pattern_features,times,args.keys,args.stars,audio['duration_s']*1000,
                            style=int(args.style=='dan'),temperature=temperature,threshold=min(.9,threshold*factor),
                            techniques=technique_vector))
    print(json.dumps({'status':'decoding','candidates':len(requests),'onsets':[len(r['times']) for r in requests]}),flush=True)
    charts,diagnostics=decode_batch(pattern,requests,device,args.seed)
    pattern.set_techniques(torch.tensor(technique_vector[None],device=device))
    candidates=[];contents=[]
    scorer=ModelLaneScorer(pattern,pattern_features,args.keys,args.stars,int(args.style=='dan'),device)
    for i,(notes,info,r) in enumerate(zip(charts,diagnostics,requests)):
        notes,repair=repair_short_jacks(notes,args.keys,scorer,args.min_head_gap_ms,args.min_release_gap_ms)
        info['pattern_metrics']=pattern_metrics(notes,args.keys)
        info['repetition_metrics']=repetition_metrics(notes,args.keys)
        info['head_pressure']=head_pressure(*head_events(notes),args.keys)
        info['local_pressure']=local_pressure_summary(*head_events(notes),args.keys)
        info['local_repair']=repair
        text=serialize_osu(notes,args.keys,'audio'+args.audio.suffix.lower(),args.audio.stem,args.stars,timing)
        text=text.replace('Creator:ManiaModel prototype','Creator:ManiaModel learned patterns')
        label=args.variant_label.replace('\r',' ').replace('\n',' ')
        text=text.replace(f'Version:{args.keys}K target',f'Version:{args.keys}K Pattern v1 {label} target')
        actual=calculated_stars(text)
        candidates.append(dict(info,candidate=i,actual_stars=actual,absolute_star_error=abs(actual-args.stars),
                               threshold=r['threshold'],temperature=r['temperature'],
                               note_count=sum(n[3]=='tap' for n in notes),ln_count=sum(n[3]=='hold' for n in notes),
                               alignment_proxy=alignment_proxy(notes,envelope)))
        contents.append(text)
    if conditioned:
        from technique_data import AXES
        scored=subprocess.run(['node',str(Path(__file__).with_name('score_techniques.mjs'))],
            input=json.dumps([dict(candidate=i,osu_text=s) for i,s in enumerate(contents)]),
            text=True,encoding='utf-8',capture_output=True,check=True)
        actual=json.loads(scored.stdout)
        if len(actual)!=len(candidates):raise ValueError('missing candidate technique analysis')
        requested=technique_profile['requested'] or dict.fromkeys(AXES)
        indices=[AXES.index(a) for a in requested]
        for candidate,score in zip(candidates,actual):
            assert candidate['candidate']==score['candidate']
            if score['status']!='ok':raise ValueError(f'candidate technique analysis failed: {score}')
            vector=store.normalize([score['raw'][a] for a in AXES],args.keys)
            candidate['technique_analysis']=score
            candidate['technique_distance']=float(np.mean((vector[indices]-technique_vector[indices])**2))
    selected,selection=select_candidate(candidates,args.stars,args.style,args.selection,args.star_tolerance,args.technique_slack)
    args.output.mkdir(parents=True)
    osu_name=f'generated_{args.keys}K.osu';osz_name=f'generated_{args.keys}K.osz';audio_name='audio'+args.audio.suffix.lower()
    (args.output/osu_name).write_text(contents[selected['candidate']],encoding='utf-8')
    (args.output/'candidate_charts.json').write_text(json.dumps([
        {'candidate':i,'osu_text':text} for i,text in enumerate(contents)],indent=2),encoding='utf-8')
    shutil.copy2(args.audio,args.output/audio_name)
    with zipfile.ZipFile(args.output/osz_name,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name in (osu_name,audio_name):z.write(args.output/name,name)
    report={'status':'complete','architecture':'legacy_rhythm_output_technique_adapter_v2','technique_strength':args.strength,'technique_bypass':bypass,'rhythm_checkpoint_sha256':sha256_file(args.checkpoint),'baseline_pattern_sha256':pattern_saved['config']['initialization_sha256'],'checkpoint':str(args.checkpoint.resolve()),
            'pattern_checkpoint':str(args.patterns.resolve()),'pattern_checkpoint_sha256':sha256_file(args.patterns),
            'pattern_training_step':pattern_saved['step'],'style':args.style,'seed':args.seed,
            'recurrent_context':{'rebuild_every_events':CORE,'generated_history_events':CONTEXT},
            'local_repair':selected['local_repair'],
            'keys':args.keys,'target_stars':args.stars,'actual_stars':selected['actual_stars'],
            'technique_profile':technique_profile,
            'technique_provenance':technique_provenance,
            'technique_analysis':selected.get('technique_analysis'),
            'technique_distance':selected.get('technique_distance'),
            'note_count':selected['note_count'],'ln_count':selected['ln_count'],'timing':timing,
            'selected_candidate':selected['candidate'],'candidates':candidates,
            'selection':selection,'repetition_metrics':selected['repetition_metrics'],
            'head_pressure':selected['head_pressure'],
            'local_pressure':selected['local_pressure'],
            'audio_path':str(args.audio.resolve()),'audio_sha256':sha256_file(args.audio),'audio_duration_s':audio['duration_s'],
            'analysis_audio_path':str(analysis_path.resolve()),'analysis_audio_sha256':sha256_file(analysis_path),
            'analysis_audio_resampled_frames':len(signal),'playback_audio_is_original':True,
            'analysis_scope':args.analysis_scope if args.analysis_audio else 'original',
            'variant_label':args.variant_label,
            'exact_audio_seen_in_training_cache':audio['pcm_sha256'] in norm['audio_ids'],
            'ln_duration_upper_limit_s':None,'osu_file':osu_name,'osz_file':osz_name,
            'decoder_code_sha256':{n:sha256_file(Path(__file__).with_name(n)) for n in ('generate_output_adapter.py','technique_output_adapter.py','technique_adapter_data.py','pattern_decode.py','short_jacks.py','pattern_selection.py','chart_pressure.py','score_techniques.mjs','technique_integrity.py')},
            'limitations':['No human playability verification.','Technique controls are soft geometric proxies; frozen rhythm limits speed/stamina control.','Candidate selection uses approximate calculated stars and a heuristic repetition preference, not perceived difficulty.',
                           'A configurable local gap guard moves notes only when a legal destination exists; unresolved pairs are reported.']}
    (args.output/'generation_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('candidates','timing')},indent=2),flush=True)


if __name__=='__main__':main()
