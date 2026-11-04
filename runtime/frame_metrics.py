"""Event-time evaluation; shifted-audio controls test actual timing dependence."""
import numpy as np
from scipy.signal import find_peaks
import torch

from mania_frames import frame_batch, frame_loss


def onset_peaks(probability, threshold, distance=4):
    # Padding also permits genuine peaks at the beginning/end of the clip.
    peaks, _ = find_peaks(np.r_[-1., probability, -1.], height=threshold, distance=distance, prominence=.015)
    return peaks - 1


def event_counts(predicted, reference, tolerance=3):
    a, b, matched = 0, 0, 0
    while a < len(predicted) and b < len(reference):
        if abs(predicted[a] - reference[b]) <= tolerance:
            matched += 1
            a += 1
            b += 1
        elif predicted[a] < reference[b]:
            a += 1
        else:
            b += 1
    return matched, len(predicted) - matched, len(reference) - matched


def summarize_counts(counts):
    tp, fp, fn = (int(n) for n in counts)
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    return {'precision': precision, 'recall': recall, 'f1': 2 * tp / max(1, 2 * tp + fp + fn),
            'matched': tp, 'extra': fp, 'missed': fn}


@torch.inference_mode()
def evaluate_frames(model, samples, device, threshold=None, shifted=False, batch_size=8):
    model.eval()
    probabilities, references = [], []
    durations, hold_probs, hold_labels, losses = [], [], [], []
    for first in range(0, len(samples), batch_size):
        batch = frame_batch(samples[first:first + batch_size], device)
        features = torch.roll(batch['features'], shifts=137, dims=1) if shifted else batch['features']
        out = model(features, batch['valid'], batch['stars'], batch['keys'])
        loss, _ = frame_loss(out, batch)
        losses.append(float(loss))
        p = out['any_onset'].sigmoid().cpu().numpy()
        actual = batch['heads'].amax(-1).cpu().numpy()
        mask = batch['loss_mask'].cpu().numpy()
        for i in range(len(p)):
            probabilities.append(p[i][mask[i]])
            references.append(np.flatnonzero(actual[i][mask[i]]))
        selected = batch['heads'].bool() & batch['loss_mask'][:, :, None]
        hold_probs.extend(out['hold'].sigmoid()[selected].cpu().tolist())
        hold_labels.extend(batch['hold'][selected].cpu().tolist())
        holds = selected & batch['hold'].bool()
        error = (out['duration'][holds].expm1() - batch['duration'][holds].expm1()).abs()
        durations.extend(error.cpu().tolist())
    results = []
    for value in ([threshold] if threshold is not None else [.2, .3, .4, .5, .6, .7, .8]):
        counts = np.zeros(3, dtype=int)
        for p, ref in zip(probabilities, references):
            counts += event_counts(onset_peaks(p, value), ref)
        results.append(dict(threshold=value, **summarize_counts(counts)))
    best = max(results, key=lambda r: r['f1'])
    hold_results = []
    hp, ht = np.array(hold_probs), np.array(hold_labels, dtype=bool)
    for value in [.3, .4, .5, .6, .7]:
        pred = hp >= value
        hold_results.append(dict(threshold=value, **summarize_counts([sum(pred & ht), sum(pred & ~ht), sum(~pred & ht)])))
    return {'loss': float(np.mean(losses)), 'global_onset_30ms': best, 'threshold_sweep': results,
            'ln_type_at_reference_heads': max(hold_results, key=lambda r: r['f1']),
            'ln_duration_absolute_error_s': {'median': float(np.median(durations)), 'p90': float(np.percentile(durations, 90))} if durations else None,
            'shifted_audio_1370ms': shifted, 'clips': len(samples)}
