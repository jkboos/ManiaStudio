"""Deterministic mania .osu serialization and a simple audio-only tempo estimate."""
import math
import numpy as np
from scipy.signal import fftconvolve
import rosu_pp_py as rosu


def validate_notes(notes, keys):
    if keys not in (4, 7):
        raise ValueError('invalid keys')
    previous = {}
    for start, end, lane, kind in sorted(notes, key=lambda n: (n[0], n[2])):
        if not (math.isfinite(start) and math.isfinite(end) and start >= 0 and 0 <= lane < keys):
            raise ValueError('invalid note coordinates')
        if kind not in ('tap', 'hold') or (end <= start if kind == 'hold' else end != start):
            raise ValueError('invalid note duration/type')
        if lane in previous and (start <= previous[lane][0] or start < previous[lane][1]):
            raise ValueError('same-lane collision')
        previous[lane] = (start, end)


def estimate_timing(mel, hop_ms=10.):
    # A baseline global estimate for scrolling/grid metadata, not note snapping.
    envelope = np.maximum(np.diff(np.asarray(mel, dtype=np.float32), axis=0), 0).mean(axis=1)
    envelope = np.r_[0., envelope]
    envelope = np.maximum(envelope - np.median(envelope), 0)
    lo, hi = max(1, round(60000 / (220 * hop_ms))), round(60000 / (60 * hop_ms))
    if len(envelope) < hi * 2 or float(envelope.max()) < 1e-5:
        return {'bpm': 120., 'offset_ms': 0., 'method': 'fallback_120_bpm'}
    corr = fftconvolve(envelope, envelope[::-1], mode='full')[len(envelope) - 1:]
    lags = np.arange(lo, hi + 1)
    score = corr[lags] / (len(envelope) - lags)
    lag = int(lags[np.argmax(score)])
    phase = np.bincount(np.arange(len(envelope)) % lag, weights=envelope, minlength=lag)
    return {'bpm': 60000 / (lag * hop_ms), 'offset_ms': float(np.argmax(phase) * hop_ms),
            'method': 'global_onset_autocorrelation_no_tempo_changes'}


def serialize_osu(notes, keys, audio_filename, title, target_stars, timing):
    validate_notes(notes, keys)
    clean = lambda value: str(value).replace('\r', ' ').replace('\n', ' ')
    header = f'''osu file format v14

[General]
AudioFilename: {clean(audio_filename)}
AudioLeadIn: 0
PreviewTime: -1
Mode: 3

[Metadata]
Title:{clean(title)}
Artist:Unknown
Creator:ManiaModel prototype
Version:{keys}K target {target_stars:.2f} stars
Tags:generated prototype
BeatmapID:0
BeatmapSetID:-1

[Difficulty]
HPDrainRate:5
CircleSize:{keys}
OverallDifficulty:7
ApproachRate:5
SliderMultiplier:1.4
SliderTickRate:1

[Events]

[TimingPoints]
{timing['offset_ms']:.3f},{60000 / timing['bpm']:.12f},4,1,0,70,1,0

[HitObjects]
'''
    objects = []
    for start, end, lane, kind in sorted(notes, key=lambda n: (n[0], n[2])):
        x = int((lane + .5) * 512 / keys)
        if kind == 'hold':
            objects.append(f'{x},192,{round(start)},128,0,{round(end)}:0:0:0:0:')
        else:
            objects.append(f'{x},192,{round(start)},1,0,0:0:0:0:')
    return header + '\n'.join(objects) + '\n'


def calculated_stars(content):
    beatmap = rosu.Beatmap(content=content)
    if beatmap.is_suspicious():
        raise ValueError('rosu flagged generated chart as suspicious')
    return float(rosu.Difficulty(mods=0, clock_rate=1., lazer=False).calculate(beatmap).stars)
