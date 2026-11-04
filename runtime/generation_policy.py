"""Versioned inference policy around unmodified model/checkpoint code."""
from pathlib import Path
import json
import numpy as np
from audio_features import sha256_file
from ln_planning import audio_ln_plan, audio_chord_plan
from style_decode import decode_batch
from technique_data import TechniqueStore
from pattern_selection import select_candidate as legacy_select
from osu_export import serialize_osu, calculated_stars
from chart_pressure import head_events, local_pressure_summary

VERSION='studio-ln-plan-2'


def select_candidate(candidates, target_stars, style='normal', policy='balanced', star_tolerance=None, technique_slack=.25, prefer_jacks=False):
    tolerance=.5 if star_tolerance is None else star_tolerance
    close=min(.3,tolerance)
    use=close if any(c['absolute_star_error']<=close for c in candidates) else tolerance
    chosen,report=legacy_select(candidates,target_stars,style,policy,use,technique_slack)
    if policy=='techniques-local':
        eligible=[c for c in candidates if c['absolute_star_error']<=use]
        def cost(c):
            pressure=0. if prefer_jacks else c['local_pressure']['overlap_p95']+.2*c['local_pressure']['overlap_max']
            return pressure+.25*c['technique_distance']+.5*c['absolute_star_error']/max(use,.001)
        if eligible:
            chosen=min(eligible,key=lambda c:(cost(c),c['absolute_star_error']))
            report.update(selected_candidate=chosen['candidate'],reason='joint_star_technique_and_local_pressure_cost',
                          costs={str(c['candidate']):cost(c) for c in eligible},
                          profile_filter='soft_distance_cost',profile_eligible_candidates=[c['candidate'] for c in eligible],
                          intentional_jack_preference=prefer_jacks)
    if chosen['absolute_star_error']>tolerance:
        raise ValueError(f'No candidate within {tolerance:.2f} stars of target {target_stars:.2f}; closest was {chosen["actual_stars"]:.2f}. No lower-difficulty substitute exported.')
    report.update(requested_star_tolerance=tolerance,inference_policy=VERSION)
    return chosen,report


def install(generate, keys, stars, techniques):
    _,profile=TechniqueStore().profile(keys,stars,techniques)
    target=profile['raw']['LN']
    original_predict=generate.predict_song
    original_timing=generate.fit_fixed_timing
    plans={}
    root=Path(__file__).resolve().parent
    prior_path=root/'data/chord_priors.json'
    prior=json.loads(prior_path.read_text(encoding='utf-8'))
    peers=[r for r in prior['rows'] if r['keys']==keys and r['style']==0]
    close_peers=[r for r in peers if abs(r['stars']-stars)<=.5]
    if len(close_peers)<24:close_peers=sorted(peers,key=lambda r:abs(r['stars']-stars))[:64]
    chord_priors=np.quantile([r['mean_chord'] for r in close_peers],[.5,.8,.95])
    def timing(*args,**kwargs):
        value=original_timing(*args,**kwargs);plans['timing']=value;return value
    def predict(*args,**kwargs):
        prediction=original_predict(*args,**kwargs)
        plans['prediction']=prediction
        plans['probabilities']=audio_ln_plan(prediction,keys,target)
        return prediction
    def decode(model,requests,device,seed):
        for request in requests:
            frames=np.clip(np.round(request['times']/10).astype(int),0,len(plans['probabilities'])-1)
            request['ln_probabilities']=plans['probabilities'][frames]
            request['ln_target']=target
        charts,diagnostics=decode_batch(model,requests,device,seed)
        # Keep an already suitable first pass; only broaden search when stars
        # and local pressure cannot both be satisfied. Do not alter onset times.
        suitable=False
        for notes in charts:
            actual=calculated_stars(serialize_osu(notes,keys,'audio.mp3','',stars,plans['timing']))
            if abs(actual-stars)<=.3:
                pressure=local_pressure_summary(*head_events(notes),keys)
                if pressure['overlap_p95']<=.45 and pressure['overlap_max']<=.7:
                    suitable=True;break
        if not suitable:
            extra=[]
            for quantile,mean_chord in zip((.5,.8,.95),chord_priors):
                count_plan=audio_chord_plan(plans['prediction'],keys,float(mean_chord))
                for request in requests:
                    frames=np.clip(np.round(request['times']/10).astype(int),0,len(count_plan)-1)
                    extra.append(dict(request,head_counts=count_plan[frames],chord_prior=float(mean_chord),chord_quantile=quantile))
            print(json.dumps(dict(status='decoding',stage='difficulty_search',candidates=len(extra))),flush=True)
            added,info=decode_batch(model,extra,device,seed+1)
            for diagnostic,request in zip(info,extra):
                diagnostic['chord_plan']=dict(mean_chord=request['chord_prior'],training_quantile=request['chord_quantile'],reference_charts=len(close_peers))
            requests.extend(extra);charts.extend(added);diagnostics.extend(info)
        return charts,diagnostics
    generate.predict_song=predict
    generate.fit_fixed_timing=timing
    generate.decode_batch=decode
    generate.select_candidate=lambda *args,**kwargs:select_candidate(*args,**kwargs,prefer_jacks=profile['requested'].get('jack')=='high')
    return dict(version=VERSION,ln_target=target,source='training_peer_profile_and_audio_model',
                chord_prior_sha256=sha256_file(prior_path),chord_reference_charts=len(close_peers),
                chord_priors=chord_priors.tolist(),
                code_sha256={name:sha256_file(root/name) for name in
                             ('generation_policy.py','ln_planning.py','style_decode.py')},
                limitations=['Inference calibration, not retraining or human playability verification.',
                             'Audio LN probabilities are estimates; musical phrase choice remains imperfect.'])
