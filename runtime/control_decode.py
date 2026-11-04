"""Free-running joint chords and LN endings; no hand-written jack penalties."""
import math
from pathlib import Path

import numpy as np
import torch

from audio_features import sha256_file
from pattern_data import audio_at_events, CORE, CONTEXT
from pattern_model import PatternModel
from osu_export import validate_notes
from lane_history import pattern_metrics


def load_pattern_checkpoint(path, device):
    saved = torch.load(path, map_location=device, weights_only=True)
    config = saved['config']
    for name in ('pattern_model.py', 'pattern_data.py'):
        if config['code_sha256'][name] != sha256_file(Path(__file__).with_name(name)):
            raise ValueError(f'pattern checkpoint code mismatch: {name}')
    if config.get('architecture')=='technique_pattern_v1':
        from technique_models import TechniquePatternModel
        if sha256_file(Path(__file__).with_name('technique_models.py'))!=config['code_sha256']['technique_models.py']:
            raise ValueError('technique model code mismatch')
        model=TechniquePatternModel(config['width'],config['layers']).to(device).eval()
    else:
        model = PatternModel(config['width'], config['layers']).to(device).eval()
    model.load_state_dict(saved['model'])
    return model, saved


@torch.inference_mode()
def decode_batch(model, requests, device, seed=42):
    """Each request contains exact onset times, event audio, keys, stars and style.

    Batch parallelism is across independent candidates, never future events.
    """
    batch_size = len(requests)
    if hasattr(model,'set_techniques'):
        model.set_techniques(torch.tensor(np.stack([r['techniques'] for r in requests]),dtype=torch.float32,device=device))
    lengths = np.array([len(r['times']) for r in requests])
    if np.any(lengths < 1):
        raise ValueError('need nonempty onset sequence')
    max_len = int(lengths.max())
    audio = np.zeros((batch_size, max_len, 640), dtype=np.float32)
    times = np.zeros((batch_size, max_len), dtype=np.float64)
    for b, r in enumerate(requests):
        audio[b, :lengths[b]] = r['audio']
        times[b, :lengths[b]] = r['times']
        if np.any(np.diff(r['times']) <= 0):
            raise ValueError('onset times must be strictly increasing')
    audio = torch.tensor(audio, device=device)
    ref_heads=np.zeros((batch_size,max_len),dtype=np.int64)
    ref_holds=np.zeros((batch_size,max_len),dtype=np.int64)
    for b,r in enumerate(requests):
        ref_heads[b,:lengths[b]]=r['reference_heads']
        ref_holds[b,:lengths[b]]=r['reference_holds']
    ref_heads=torch.tensor(ref_heads,device=device)
    ref_holds=torch.tensor(ref_holds,device=device)
    trace={name:torch.zeros((batch_size,max_len),device=device) for name in ('legal','head_nll','hold_nll','head_correct')}
    keys = torch.tensor([r['keys'] for r in requests], device=device)
    stars = torch.tensor([r['stars'] for r in requests], dtype=torch.float32, device=device)
    styles = torch.tensor([r.get('style', 0) for r in requests], device=device)
    temperatures = torch.tensor([r.get('temperature', .85) for r in requests], device=device)[:, None]
    generator = torch.Generator(device=device).manual_seed(seed)
    last_heads = np.full((batch_size, 7), -1., dtype=np.float64)
    active_until = np.zeros((batch_size, 7), dtype=np.float64)
    previous_heads = np.zeros(batch_size, dtype=np.int64)
    previous_holds = np.zeros(batch_size, dtype=np.int64)
    previous_duration = np.zeros((batch_size, 7), dtype=np.float32)
    previous_event = np.full(batch_size, -1., dtype=np.float64)
    hidden = torch.zeros(model.layers, batch_size, model.width, device=device)
    cached_numbers=[];cached_heads=[];cached_holds=[];cached_usable=[]
    results = [[] for _ in requests]
    diagnostics = [dict(all_lanes_held_events=0, shared_release_chords=0, ln_duration_upper_limit_s=None) for _ in requests]
    for i in range(max_len):
        # Training sees at most 32 preceding events before each 96-event core.
        # Rebuild from generated history to avoid unbounded hidden-state drift.
        if i and i % CORE == 0:
            hidden = torch.zeros_like(hidden)
            for past in range(max(0,i-CONTEXT),i):
                _,_,updated = model(audio[:,past:past+1],cached_heads[past],cached_holds[past],
                                     cached_numbers[past],stars,keys,styles,hidden)
                hidden = torch.where(cached_usable[past][None,:,None],updated,hidden)
        current = times[:, i]
        real = i < lengths
        age = np.where(last_heads >= 0, np.maximum(0., current[:, None]-last_heads)/1000, 60.)
        remaining = np.maximum(0., active_until-current[:, None])/1000
        gaps = np.zeros((batch_size, 3), dtype=np.float32)
        gaps[:, 0] = np.where(previous_event >= 0, np.maximum(0., current-previous_event)/1000, 0)
        for ahead in (1, 2):
            if i+ahead < max_len:
                gaps[:, ahead] = np.where(i+ahead < lengths, np.maximum(0.,times[:,i+ahead]-current)/1000,0)
        numbers = np.concatenate([np.log1p(age),np.log1p(remaining),previous_duration,np.log1p(gaps)],axis=-1).astype(np.float32)
        input_heads=torch.tensor(previous_heads[:,None],device=device)
        input_holds=torch.tensor(previous_holds[:,None],device=device)
        input_numbers=torch.tensor(numbers[:,None],device=device)
        logits, states, updated = model(audio[:,i:i+1],input_heads,input_holds,input_numbers,stars,keys,styles,hidden)
        reference=ref_heads[:,i]
        trace['legal'][:,i]=(logits[:,0].gather(1,reference[:,None])[:,0]>-9999).float()
        trace['head_nll'][:,i]=-torch.log_softmax(logits[:,0],-1).gather(1,reference[:,None])[:,0]
        trace['head_correct'][:,i]=(logits[:,0].argmax(-1)==reference).float()
        reference_tail=model.endings(states,reference[:,None])
        trace['hold_nll'][:,i]=-torch.log_softmax(reference_tail['holds'][:,0],-1).gather(1,ref_holds[:,i,None])[:,0]
        # No nonempty legal chord exists while every lane is held.
        usable = np.array([real[b] and np.any(active_until[b,:r['keys']] <= current[b]) for b,r in enumerate(requests)])
        usable_tensor=torch.tensor(usable,device=device)
        cached_numbers.append(input_numbers);cached_heads.append(input_heads);cached_holds.append(input_holds);cached_usable.append(usable_tensor)
        hidden = torch.where(usable_tensor[None,:,None],updated,hidden)
        head_prob = torch.softmax(logits[:,0]/temperatures,dim=-1)
        heads = torch.multinomial(head_prob,1,generator=generator)
        heads[~torch.tensor(usable,device=device)] = 0
        tail = model.endings(states,heads)
        hold_prob = torch.softmax(tail['holds'][:,0]/temperatures,dim=-1)
        holds = torch.multinomial(hold_prob,1,generator=generator)[:,0].cpu().numpy()
        heads = heads[:,0].cpu().numpy()
        durations = tail['duration'][:,0].cpu().numpy()
        shared = (tail['shared'][:,0] >= 0).cpu().numpy()
        for b,r in enumerate(requests):
            if not real[b]: continue
            if not usable[b]:
                diagnostics[b]['all_lanes_held_events'] += 1
                continue
            time_ms = int(current[b])
            share = bool(shared[b] and int(holds[b]).bit_count() >= 2)
            diagnostics[b]['shared_release_chords'] += int(share)
            previous_duration[b] = 0
            for lane in range(r['keys']):
                if not (heads[b] & (1 << lane)):continue
                if holds[b] & (1 << lane):
                    log_duration = float(durations[b,7 if share else lane])
                    available_s = max(0.,(math.floor(r['duration_ms'])-time_ms)/1000)
                    seconds = math.expm1(min(log_duration,math.log1p(available_s)))
                    end = min(math.floor(r['duration_ms']),time_ms+max(1,round(seconds*1000)))
                    if end > time_ms:
                        results[b].append([time_ms,end,lane,'hold'])
                        active_until[b,lane] = end
                        previous_duration[b,lane] = math.log1p((end-time_ms)/1000)
                    else:
                        holds[b] &= ~(1 << lane)
                        results[b].append([time_ms,time_ms,lane,'tap'])
                else:
                    results[b].append([time_ms,time_ms,lane,'tap'])
                last_heads[b,lane] = time_ms
            previous_heads[b],previous_holds[b] = heads[b],holds[b]
            previous_event[b] = current[b]
    for b,r in enumerate(requests):
        validate_notes(results[b],r['keys'])
        diagnostics[b]['pattern_metrics'] = pattern_metrics(results[b],r['keys'])
        lengths_s=[(end-start)/1000 for start,end,_,kind in results[b] if kind=='hold']
        diagnostics[b]['ln_duration_s']={'median':float(np.median(lengths_s)),'max':max(lengths_s)} if lengths_s else None
    arrays={name:value.cpu().numpy() for name,value in trace.items()}
    for b,r in enumerate(requests):
        diagnostics[b]['audit_trace']={name:value[b,:lengths[b]].tolist() for name,value in arrays.items()}
    if any(r.get('capture_history') for r in requests):
        history=dict(prev_heads=torch.cat(cached_heads,dim=1).cpu().numpy(),
                     prev_holds=torch.cat(cached_holds,dim=1).cpu().numpy(),
                     numbers=torch.cat(cached_numbers,dim=1).cpu().numpy(),
                     usable=torch.stack(cached_usable,dim=1).cpu().numpy())
        for b,r in enumerate(requests):
            diagnostics[b]['generated_history']={name:value[b,:lengths[b]] for name,value in history.items()}
    return results,diagnostics


def request_from_audio(features, times, keys, stars, duration_ms, mean=None, std=None, **options):
    return dict(times=np.asarray(times),audio=audio_at_events(features,times,
                np.zeros(128,dtype=np.float32) if mean is None else mean,
                np.ones(128,dtype=np.float32) if std is None else std),keys=keys,stars=stars,
                duration_ms=duration_ms,**options)
