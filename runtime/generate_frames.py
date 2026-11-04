"""Generate from audio-aligned predictions with explicit, uncapped LN endings."""
import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import shutil
import sys
import zipfile

import numpy as np
import torch

from audio_features import FeatureSpec, read_mono, resample_audio, iter_log_mel, sha256_file
from mania_frames import FrameSpec, FrameModel
from frame_metrics import onset_peaks
from fixed_timing import onset_envelope, fit_fixed_timing, snap_nearby
from osu_export import serialize_osu, calculated_stars, validate_notes
from lane_history import history_weights, pattern_metrics, RECOVERY_MS, REPEAT_STRENGTH


def load_frame_checkpoint(path, device):
    saved = torch.load(path, map_location=device, weights_only=True)
    config = saved['config']
    for name in ('audio_features.py', 'mania_frames.py'):
        if sha256_file(Path(__file__).with_name(name)) != config['code_sha256'][name]:
            raise ValueError(f'checkpoint frontend/model code differs: {name}')
    if config.get('architecture') == 'frame_techniques_v1':
        from technique_models import TechniqueFrameModel
        if sha256_file(Path(__file__).with_name('technique_models.py'))!=config['code_sha256']['technique_models.py']:
            raise ValueError('technique model code mismatch')
        model=TechniqueFrameModel(FrameSpec(**config['spec'])).to(device)
    elif config.get('architecture') == 'frame_low_band_ab_v1':
        from bass_frames import BassFrameModel
        if sha256_file(Path(__file__).with_name('bass_frames.py')) != config['code_sha256']['bass_frames.py']:
            raise ValueError('checkpoint low-band feature/model code differs')
        model = BassFrameModel(FrameSpec(**config['spec']), config['normalization'], config['low_band_enabled']).to(device)
    else:
        model = FrameModel(FrameSpec(**config['spec'])).to(device)
    model.load_state_dict(saved['model'])
    model.eval()
    return model, saved


@torch.inference_mode()
def predict_song(model, features, keys, stars, device):
    spec = model.spec
    result = {k: np.zeros((len(features), 7), dtype=np.float32) for k in ('onset', 'hold', 'duration')}
    result['any_onset'] = np.zeros(len(features), dtype=np.float32)
    weights = np.zeros(len(features), dtype=np.float32)
    taper = np.maximum(.1, np.hanning(spec.core_frames)).astype(np.float32)
    # 50% overlapping central predictions reduce window seam artifacts.
    for core in range(0, len(features), spec.core_frames // 2):
        first = core - spec.context_frames
        x = np.zeros((spec.frames, 128), dtype=np.float32)
        valid = np.zeros(spec.frames, dtype=bool)
        a, b = max(0, first), min(len(features), first + spec.frames)
        x[a - first:b - first] = features[a:b]
        valid[a - first:b - first] = True
        out = model(torch.tensor(x[None], device=device), torch.tensor(valid[None], device=device),
                    torch.tensor([stars], dtype=torch.float32, device=device), torch.tensor([keys], device=device))
        length = min(spec.core_frames, len(features) - core)
        selection = slice(spec.context_frames, spec.context_frames + length)
        for name in result:
            value = out[name][0, selection]
            if name != 'duration':
                value = value.sigmoid()
            value = value.cpu().numpy()
            result[name][core:core + length] += value * (taper[:length, None] if value.ndim == 2 else taper[:length])
        weights[core:core + length] += taper[:length]
    for name in result:
        result[name] /= weights[:, None] if result[name].ndim == 2 else weights
    return result


def notes_from_predictions(prediction, keys, duration_ms, timing, threshold, hold_threshold,
                           seed=42, chord_scale=1., snap=True, lane_policy='history'):
    if lane_policy not in ('history', 'independent'):
        raise ValueError('unknown lane policy')
    rng = np.random.default_rng(seed)
    peaks = onset_peaks(prediction['any_onset'], threshold)
    active_until = np.zeros(keys)
    last_head = np.full(keys, -1.)
    run_lengths = np.zeros(keys, dtype=int)
    notes = []
    diagnostics = {'detected_onsets': len(peaks), 'snapped_onsets': 0, 'suppressed_occupied_lanes': 0,
                   'all_lanes_held_events': 0, 'tails_at_audio_end': 0, 'ln_duration_upper_limit_s': None}
    for frame in peaks:
        time_ms = frame * 10.
        if time_ms >= duration_ms:
            continue
        if snap:
            time_ms, did_snap = snap_nearby(time_ms, timing)
            diagnostics['snapped_onsets'] += int(did_snap)
        time_ms = int(round(time_ms))
        if time_ms >= duration_ms:
            continue
        probabilities = prediction['onset'][frame, :keys].astype(float)
        # Undo positive BCE weighting before estimating expected chord size.
        posterior = probabilities / np.maximum(12 - 11 * probabilities, 1e-6)
        desired = max(1., min(keys, posterior.sum() * chord_scale))
        count = int(math.floor(desired)) + int(rng.random() < desired % 1)
        available = (active_until <= time_ms) & (last_head < time_ms)
        diagnostics['suppressed_occupied_lanes'] += int((~available).sum())
        if not available.any():
            diagnostics['all_lanes_held_events'] += 1
            continue
        count = min(count, int(available.sum()))
        # Preserve learned preference, with optional soft cost for recent repeats.
        weights = np.maximum(posterior, 1e-5) ** 2 * available
        if lane_policy == 'history':
            weights = history_weights(weights, time_ms, last_head, run_lengths)
        lanes = rng.choice(keys, size=count, replace=False, p=weights / weights.sum())
        for lane in sorted(lanes):
            if prediction['hold'][frame, lane] >= hold_threshold:
                # No style/duration cap. Only the actual audio boundary is enforced.
                remaining_s = max(0., (math.floor(duration_ms) - time_ms) / 1000)
                log_duration = max(0., float(prediction['duration'][frame, lane]))
                predicted_s = math.expm1(min(log_duration, math.log1p(remaining_s)))
                end = min(math.floor(duration_ms), time_ms + max(1, round(predicted_s * 1000)))
                if end > time_ms:
                    if end == math.floor(duration_ms):
                        diagnostics['tails_at_audio_end'] += 1
                    notes.append([time_ms, end, int(lane), 'hold'])
                    active_until[lane] = end
                else:
                    notes.append([time_ms, time_ms, int(lane), 'tap'])
            else:
                notes.append([time_ms, time_ms, int(lane), 'tap'])
            run_lengths[lane] = run_lengths[lane] + 1 if last_head[lane] >= 0 and time_ms - last_head[lane] < RECOVERY_MS else 1
            last_head[lane] = time_ms
    notes.sort(key=lambda n: (n[0], n[2]))
    validate_notes(notes, keys)
    lengths = [(e - s) / 1000 for s, e, _, kind in notes if kind == 'hold']
    diagnostics['ln_duration_s'] = {'median': float(np.median(lengths)), 'p95': float(np.percentile(lengths, 95)), 'max': max(lengths)} if lengths else None
    diagnostics['lane_policy'] = lane_policy
    diagnostics['pattern_metrics'] = pattern_metrics(notes, keys)
    return notes, diagnostics


def alignment_proxy(notes, envelope):
    peaks = onset_peaks(envelope, .15, distance=4)
    heads = np.unique([round(n[0] / 10) for n in notes])
    if not len(heads) or not len(peaks):
        return {'within_30ms_of_audio_onset_fraction': 0., 'median_distance_ms': None}
    closest = []
    for head in heads:
        at = np.searchsorted(peaks, head)
        candidates = peaks[max(0, at - 1):min(len(peaks), at + 1)]
        closest.append(int(np.min(np.abs(candidates - head))) * 10)
    return {'within_30ms_of_audio_onset_fraction': float(np.mean(np.array(closest) <= 30)),
            'median_distance_ms': float(np.median(closest)),
            'note': 'Spectral-onset proximity is a diagnostic, not musical correctness or playability.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio', type=Path)
    parser.add_argument('--checkpoint', type=Path, default=Path('runs/frames_v2/best.pt'))
    parser.add_argument('--keys', type=int, choices=(4, 7), required=True)
    parser.add_argument('--stars', type=float, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--lane-policy', choices=('history', 'independent'), default='history',
                        help='Soft repeat-history costs, or the original independent sampling for comparison')
    args = parser.parse_args()
    if args.output.exists() or not math.isfinite(args.stars) or args.stars <= 0:
        parser.error('use a new output directory and a positive finite star rating')
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    torch.set_num_threads(4)
    model, saved = load_frame_checkpoint(args.checkpoint, device)
    config = saved['config']
    waveform, sr, audio = read_mono(args.audio)
    signal = resample_audio(waveform, sr, FeatureSpec(**config['feature_spec']))
    mel = np.concatenate([v for _, v in iter_log_mel(signal, FeatureSpec(**config['feature_spec']))])
    envelope = onset_envelope(mel)
    timing = fit_fixed_timing(envelope)
    print(json.dumps({'timing': timing}), flush=True)
    norm = config['normalization']
    normalized = (mel.astype(np.float16).astype(np.float32) - np.array(norm['mean'], dtype=np.float32)) / np.array(norm['std'], dtype=np.float32)
    prediction = predict_song(model, normalized, args.keys, args.stars, device)
    evaluation = saved['evaluation']
    threshold = evaluation['global_onset_30ms']['threshold']
    hold_threshold = evaluation['ln_type_at_reference_heads']['threshold']
    calibration_path = args.checkpoint.parent / 'decoder_calibration.json'
    calibration = None
    base_scale = 1.
    if calibration_path.exists():
        calibration = json.loads(calibration_path.read_text(encoding='utf-8'))
        if calibration['checkpoint_sha256'] != sha256_file(args.checkpoint):
            raise ValueError('decoder calibration is stale; rerun calibrate_frames.py')
        base_scale = calibration['by_key'][str(args.keys)]['scale']
    candidates, best = [], None
    for index, (factor, density) in enumerate((f, c) for f in (.85, 1., 1.15) for c in (.8, 1., 1.2)):
        chord_scale = base_scale * density
        notes, diagnostics = notes_from_predictions(prediction, args.keys, audio['duration_s'] * 1000,
                                                    timing, min(.9, threshold * factor), hold_threshold,
                                                    args.seed + index, chord_scale, lane_policy=args.lane_policy)
        text = serialize_osu(notes, args.keys, 'audio' + args.audio.suffix.lower(), args.audio.stem, args.stars, timing)
        text = text.replace('Creator:ManiaModel prototype', 'Creator:ManiaModel v2')
        version = 'History v1' if args.lane_policy == 'history' else 'v2 audio-aligned'
        text = text.replace(f'Version:{args.keys}K target {args.stars:.2f} stars', f'Version:{args.keys}K {version} target {args.stars:.2f} stars')
        actual = calculated_stars(text)
        summary = dict(diagnostics, candidate=index, threshold=threshold * factor, chord_scale=chord_scale,
                       note_count=sum(n[3] == 'tap' for n in notes), ln_count=sum(n[3] == 'hold' for n in notes),
                       actual_stars=actual, absolute_star_error=abs(actual - args.stars), alignment_proxy=alignment_proxy(notes, envelope))
        candidates.append(summary)
        if notes and (best is None or summary['absolute_star_error'] < best[0]['absolute_star_error']):
            best = summary, text
    args.output.mkdir(parents=True)
    if best is None:
        raise ValueError('no nonempty chart generated')
    selected, text = best
    osu_name, audio_name = f'generated_{args.keys}K.osu', 'audio' + args.audio.suffix.lower()
    (args.output / osu_name).write_text(text, encoding='utf-8')
    shutil.copy2(args.audio, args.output / audio_name)
    osz_name = f'generated_{args.keys}K.osz'
    with zipfile.ZipFile(args.output / osz_name, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.write(args.output / osu_name, osu_name)
        z.write(args.output / audio_name, audio_name)
    report = {'status': 'complete', 'architecture': config['architecture'], 'checkpoint': str(args.checkpoint.resolve()),
              'checkpoint_step': saved['step'], 'keys': args.keys, 'target_stars': args.stars,
              'actual_stars': selected['actual_stars'], 'note_count': selected['note_count'], 'ln_count': selected['ln_count'],
              'audio_path': str(args.audio.resolve()), 'audio_sha256': sha256_file(args.audio),
              'audio_duration_s': audio['duration_s'], 'exact_audio_seen_in_training_cache': audio['pcm_sha256'] in norm['audio_ids'],
              'timing': timing, 'selected_candidate': selected['candidate'], 'candidates': candidates,
              'decoder_calibration': calibration,
              'lane_policy': args.lane_policy,
              'lane_history_settings': {'recovery_ms': RECOVERY_MS, 'repeat_strength': REPEAT_STRENGTH,
                                        'learned': False} if args.lane_policy == 'history' else None,
              'decoder_code_sha256': {name: sha256_file(Path(__file__).with_name(name))
                                      for name in ('generate_frames.py', 'lane_history.py')},
              'ln_duration_upper_limit_s': None, 'osu_file': osu_name, 'osz_file': osz_name,
              'limitations': ['No human playability verification.', 'BPM/octave/phase estimation can be ambiguous.',
                              'Column selection and difficulty still require evaluation; spectral onset proximity is only a diagnostic.']}
    (args.output / 'generation_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    np.savez_compressed(args.output / 'prediction_diagnostics.npz', any_onset=prediction['any_onset'], audio_onset=envelope)
    print(json.dumps({k: v for k, v in report.items() if k != 'candidates'}, indent=2), flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
