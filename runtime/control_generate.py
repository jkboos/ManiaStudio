"""Portable control checkpoint inference, without Studio's LN/count/repair policy."""
import json
from pathlib import Path
import shutil
import numpy as np
import torch

from audio_features import FeatureSpec, read_mono, resample_audio, iter_log_mel, sha256_file
from generate_frames import load_frame_checkpoint, predict_song
from frame_metrics import onset_peaks
from fixed_timing import onset_envelope, fit_fixed_timing, snap_nearby
from pattern_data import audio_at_events, CORE, CONTEXT
from technique_data import TechniqueStore
from technique_output_adapter import load_adapter
from control_decode import decode_batch
from osu_export import serialize_osu, calculated_stars, validate_notes

RUNTIME = Path(__file__).resolve().parent
APP = RUNTIME.parent


def choose_candidate(candidates, target, tolerance):
    if not candidates:
        raise ValueError('音訊沒有足夠的節奏起點，無法生成譜面。')
    best = min(candidates, key=lambda c: (abs(c['actual_stars']-target), c['candidate']))
    if abs(best['actual_stars']-target) > tolerance:
        raise ValueError(f'Control 本次候選最接近 {best["actual_stars"]:.2f} 星，與指定的 {target:.2f} 星相差超過 {tolerance:.2f}；請調整難度再試。')
    return best


def generate(audio_path, output, keys, stars, techniques):
    manifest = json.loads((APP/'control_backend.json').read_text(encoding='utf-8'))
    params = manifest['parameters']
    checkpoint = RUNTIME/manifest['checkpoint']
    for path, expected in ((checkpoint, manifest['checkpoint_sha256']),
                           (RUNTIME/manifest['decoder'], manifest['decoder_sha256'])):
        if sha256_file(path) != expected:
            raise ValueError(f'Control runtime integrity check failed: {path.name}')
    if output.exists():
        raise ValueError('Use a new generation output directory')
    torch.set_num_threads(4)
    torch.set_float32_matmul_precision('high')
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model, saved = load_adapter(checkpoint, device)
    model.rnn.dropout = 0.
    model.technique_strength = params['technique_strength']
    store = TechniqueStore(RUNTIME/'data/techniques_v1')
    if saved['config']['technique_config'] != store.config:
        raise ValueError('Control technique normalization changed')
    vector, profile = store.profile(keys, stars, techniques)
    rhythm_path = RUNTIME/'runs/full_epoch_large/epoch_complete.pt'
    if sha256_file(rhythm_path) != saved['config']['rhythm_sha256']:
        raise ValueError('Control rhythm checkpoint changed')
    rhythm, rhythm_saved = load_frame_checkpoint(rhythm_path, device)
    cfg = rhythm_saved['config']
    norm = cfg['normalization']
    norm_path = RUNTIME/'data/features/normalization.json'
    if sha256_file(norm_path) != saved['config']['normalization_sha256'] or json.loads(norm_path.read_text()) != norm:
        raise ValueError('Control audio normalization changed')
    spec = FeatureSpec(**cfg['feature_spec'])
    wave, sr, audio = read_mono(audio_path)
    mel = np.concatenate([v for _, v in iter_log_mel(resample_audio(wave, sr, spec), spec)])
    timing = fit_fixed_timing(onset_envelope(mel))
    # The pilot used float16 feature precision for the onset model and the
    # unrounded mel for the control adapter. Keep those separate here too.
    normalized = (mel.astype(np.float16).astype(np.float32)-np.asarray(norm['mean'], np.float32))/np.asarray(norm['std'], np.float32)
    prediction = predict_song(rhythm, normalized, keys, stars, device)
    del rhythm
    threshold = rhythm_saved['evaluation']['global_onset_30ms']['threshold']
    requests = []
    for factor in params['onset_factors']:
        peaks = onset_peaks(prediction['any_onset'], min(.9, threshold*factor))
        times = np.array(sorted({int(round(snap_nearby(float(f*10), timing)[0])) for f in peaks}), dtype=np.int64)
        times = times[(times >= 0) & (times < int(audio['duration_s']*1000))]
        if len(times) < 2:
            continue
        requests.append(dict(times=times, audio=audio_at_events(mel, times, np.asarray(norm['mean'], np.float32), np.asarray(norm['std'], np.float32)),
                             keys=keys, stars=stars, duration_ms=audio['duration_s']*1000,
                             techniques=vector, temperature=params['temperature'], style=0,
                             threshold_factor=factor, reference_heads=np.zeros(len(times), np.int64),
                             reference_holds=np.zeros(len(times), np.int64)))
    if not requests:
        choose_candidate([], stars, params['star_tolerance'])
    candidates, contents, all_notes = [], [], []
    audio_name = 'audio'+audio_path.suffix.lower()
    for attempt in range(params['max_seed_attempts']):
        seed = params['seed']+attempt
        print(json.dumps(dict(status='decoding', stage='control', seed=seed, candidates=len(requests))), flush=True)
        charts, diagnostics = decode_batch(model, requests, device, seed)
        for request, notes, diagnostic in zip(requests, charts, diagnostics):
            validate_notes(notes, keys)
            if not notes:
                continue
            content = serialize_osu(notes, keys, audio_name, audio_path.stem, stars, timing)
            actual = calculated_stars(content)
            candidate = dict(candidate=len(candidates), actual_stars=actual, absolute_star_error=abs(actual-stars),
                             threshold_factor=request['threshold_factor'], seed=seed,
                             temperature=params['temperature'], note_count=sum(n[3]=='tap' for n in notes),
                             ln_count=sum(n[3]=='hold' for n in notes),
                             all_lanes_held_events=diagnostic['all_lanes_held_events'])
            candidates.append(candidate); contents.append(content); all_notes.append(notes)
        if any(c['absolute_star_error'] <= params['star_tolerance'] for c in candidates):
            break
    chosen = choose_candidate(candidates, stars, params['star_tolerance'])
    index = chosen['candidate']
    validate_notes(all_notes[index], keys)
    output.mkdir(parents=True)
    osu_name = f'generated_{keys}K.osu'
    (output/osu_name).write_text(contents[index], encoding='utf-8')
    shutil.copy2(audio_path, output/audio_name)
    report = dict(status='complete', architecture='retrained_control_output_adapter_v2', keys=keys,
                  target_stars=stars, actual_stars=chosen['actual_stars'],
                  note_count=chosen['note_count'], ln_count=chosen['ln_count'],
                  audio_duration_s=audio['duration_s'], audio_sha256=sha256_file(audio_path),
                  timing=timing, osu_file=osu_name, candidates=candidates, selected_candidate=index,
                  pattern_checkpoint=manifest['checkpoint'], pattern_checkpoint_sha256=sha256_file(checkpoint),
                  rhythm_checkpoint_sha256=sha256_file(rhythm_path), technique_profile=profile,
                  technique_strength=params['technique_strength'], seed=chosen['seed'],
                  recurrent_context=dict(rebuild_every_events=CORE, generated_history_events=CONTEXT),
                  local_repair=None, ln_duration_upper_limit_s=None,
                  inference_policy=dict(manifest, generator_sha256=sha256_file(__file__)),
                  limitations=['Control checkpoint and decoder match the pilot; new-audio onset candidate selection differs.',
                               'Technique controls are soft preferences; calculated stars do not guarantee perceived difficulty.'])
    (output/'generation_report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return report
