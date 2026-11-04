"""Continuous fixed-tempo/phase estimation, with explicit ambiguity diagnostics."""
import numpy as np
from scipy.ndimage import gaussian_filter1d, median_filter
from scipy.signal import find_peaks


def onset_envelope(mel):
    mel = np.asarray(mel, dtype=np.float32)
    amplitude = np.power(10., mel / 20)
    scale = np.maximum(np.median(amplitude, axis=0), 1e-5)
    compressed = np.log1p(np.minimum(amplitude / scale, 100.) * 10)
    flux = np.maximum(np.diff(compressed, axis=0, prepend=compressed[:1]), 0).mean(axis=1)
    flux = np.maximum(flux - median_filter(flux, size=101, mode='nearest'), 0)
    flux = gaussian_filter1d(flux, .6)
    # Centered Hann-window spectral differences anticipate an impulsive onset.
    # A one-hop correction is verified end-to-end on synthetic impulse trains.
    flux = np.r_[0., flux[:-1]]
    scale = np.percentile(flux, 99) if len(flux) else 0
    return np.clip(flux / max(float(scale), 1e-8), 0, 3).astype(np.float32)


def periodic_scores(times_s, weights, bpms):
    scores, coherences, phases = [], [], []
    denominator = max(weights.sum(), 1e-12)
    for first in range(0, len(bpms), 128):
        tempo = np.asarray(bpms[first:first + 128])
        angle = 2j * np.pi * tempo[:, None] / 60 * times_s[None]
        fundamental = np.exp(angle)
        c1 = (fundamental * weights).sum(axis=1) / denominator
        c2 = ((fundamental ** 2) * weights).sum(axis=1) / denominator
        c4 = ((fundamental ** 4) * weights).sum(axis=1) / denominator
        score = .7 * np.abs(c1) + .2 * np.abs(c2) + .1 * np.abs(c4)
        # Weak octave tie-break only; report octave alternatives explicitly.
        score *= np.exp(-.04 * np.log2(tempo / 125) ** 2)
        scores.extend(score.tolist())
        coherences.extend(np.abs(c1).tolist())
        phases.extend((np.angle(c1) / (2 * np.pi) % 1).tolist())
    return np.array(scores), np.array(coherences), np.array(phases)


def fit_fixed_timing(envelope, hop_ms=10.):
    envelope = np.asarray(envelope, dtype=np.float64)
    peaks, _ = find_peaks(envelope, distance=max(1, round(60 / hop_ms)), prominence=.05)
    peaks = peaks[envelope[peaks] >= .15]
    if len(peaks) < 12:
        return {'bpm': 120., 'offset_ms': 0., 'method': 'insufficient_onsets_fallback',
                'reliable_for_snapping': False, 'confidence': 0., 'onset_count': len(peaks)}
    times = peaks * hop_ms / 1000
    weights = np.minimum(envelope[peaks], 2.)
    tempos = np.arange(60., 220.0001, .1)
    score, _, _ = periodic_scores(times, weights, tempos)
    strongest, _ = find_peaks(score, distance=10)
    best_coarse = strongest[np.argsort(score[strongest])[-8:]] if len(strongest) else [int(np.argmax(score))]
    candidates = []
    for index in best_coarse:
        fine = np.arange(max(60, tempos[index] - .15), min(220, tempos[index] + .15) + .0005, .001)
        values, coherence, phase = periodic_scores(times, weights, fine)
        winner = int(np.argmax(values))
        candidates.append({'bpm': float(fine[winner]), 'score': float(values[winner]),
                           'coherence': float(coherence[winner]), 'phase': float(phase[winner])})
    candidates.sort(key=lambda c: c['score'], reverse=True)
    best = candidates[0]
    bpm, phase = best['bpm'], best['phase']
    beat_ms = 60000 / bpm
    residuals, local = [], []
    # Fixed global clock evaluated on independent time regions; no tempo changes emitted.
    for start in np.arange(0, len(envelope) * hop_ms / 1000, 30.):
        mask = (times >= start) & (times < start + 30)
        if mask.sum() < 12:
            continue
        values, coherence, local_phase = periodic_scores(times[mask], weights[mask], np.array([bpm]))
        if coherence[0] < .08:
            continue
        residual = ((local_phase[0] - phase + .5) % 1 - .5) * beat_ms
        residuals.append(abs(float(residual)))
        local.append({'start_s': float(start), 'phase_error_ms': float(residual), 'coherence': float(coherence[0])})
    phase_error = float(np.median(residuals)) if residuals else None
    confidence = float(best['coherence'])
    reliable = confidence >= .15 and len(local) >= 2 and phase_error is not None and phase_error <= 30
    return {'bpm': bpm, 'offset_ms': phase * beat_ms, 'method': 'continuous_fixed_tempo_harmonic_fit',
            'confidence': confidence, 'reliable_for_snapping': bool(reliable),
            'onset_count': len(peaks), 'median_local_phase_error_ms': phase_error,
            'local_phase_checks': local, 'alternatives': candidates[:5],
            'note': 'Offset is a beat phase modulo one beat, not a verified downbeat. Octave ambiguity can remain.'}


def snap_nearby(time_ms, timing, max_shift_ms=20., subdivision=4):
    if not timing.get('reliable_for_snapping', False):
        return time_ms, False
    step = 60000 / timing['bpm'] / subdivision
    nearest = timing['offset_ms'] + round((time_ms - timing['offset_ms']) / step) * step
    if nearest >= 0 and abs(nearest - time_ms) <= max_shift_ms:
        return nearest, True
    return time_ms, False
