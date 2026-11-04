"""Head-density and overlapping-chord diagnostics; not a playability rating."""
from collections import defaultdict

import numpy as np


def head_events(notes):
    events = defaultdict(int)
    for start, _, lane, _ in notes:
        events[start] |= 1 << lane
    times = np.array(sorted(events), dtype=float)
    return times, np.array([events[t] for t in times], dtype=np.int64)


def head_pressure(times, masks, keys, start_ms=None, end_ms=None, fast_gap_ms=200.):
    """Count shared keys even when two successive chord masks differ.

    The set-size lower bound ignores active LN occupancy, so it is a lower
    bound rather than the exact number of repetitions that cannot be avoided.
    LN releases, muscle fatigue and musical suitability are not scored here.
    """
    times, masks = np.asarray(times, dtype=float), np.asarray(masks, dtype=np.int64)
    if len(times) != len(masks) or np.any(np.diff(times) <= 0):
        raise ValueError('need aligned, strictly increasing head events')
    if np.any((masks <= 0) | (masks >= (1 << keys))):
        raise ValueError('invalid head mask')
    if len(times) == 0:
        return {'events': 0, 'objects': 0}
    start = times[0] if start_ms is None else start_ms
    end = times[-1] if end_ms is None else end_ms
    duration_s = max(0., (end-start)/1000.)
    counts = np.array([int(m).bit_count() for m in masks])
    gaps = np.diff(times)
    fast = gaps <= fast_gap_ms
    overlap = np.array([int(a & b).bit_count() for a, b in zip(masks[:-1], masks[1:])])
    lower_bound = np.maximum(0, counts[:-1]+counts[1:]-keys)
    denominator = max(1, int(fast.sum()))
    return dict(events=len(times), objects=int(counts.sum()), duration_s=duration_s,
                events_per_second=len(times)/duration_s if duration_s else None,
                notes_per_second=float(counts.sum()/duration_s) if duration_s else None,
                mean_chord=float(counts.mean()),
                chord_fractions={str(i):float(np.mean(counts == i)) for i in range(1, keys+1)},
                median_event_gap_ms=float(np.median(gaps)) if len(gaps) else None,
                fast_gap_ms=fast_gap_ms, fast_pairs=int(fast.sum()),
                fast_overlap_pair_fraction=float(np.count_nonzero(overlap[fast])/denominator),
                fast_forced_overlap_pair_fraction=float(np.count_nonzero(lower_bound[fast])/denominator),
                fast_repeated_heads=int(overlap[fast].sum()),
                fast_minimum_repeated_heads_from_chord_sizes=int(lower_bound[fast].sum()),
                fast_repeats_above_size_lower_bound=int((overlap[fast]-lower_bound[fast]).sum()))


def pressure_windows(times, masks, keys, window_ms=8000., stride_ms=2000.):
    times, masks = np.asarray(times), np.asarray(masks)
    if len(times) < 2:
        return []
    result = []
    for start in np.arange(times[0], times[-1]-window_ms+1, stride_ms):
        end = start+window_ms
        selected = (times >= start) & (times < end)
        if selected.sum() < 8:
            continue
        result.append(dict(start_ms=float(start), end_ms=float(end),
                           **head_pressure(times[selected], masks[selected], keys, start, end)))
    return result


def local_pressure_summary(times, masks, keys):
    windows = pressure_windows(times, masks, keys)
    eligible = [w for w in windows if w['fast_pairs'] >= 8]
    if not eligible:
        eligible = [head_pressure(times, masks, keys)] if len(times) >= 2 else []
    values = [w['fast_overlap_pair_fraction'] for w in eligible]
    worst = max(eligible, key=lambda w:w['fast_overlap_pair_fraction']) if eligible else None
    return dict(window_ms=8000, stride_ms=2000, windows=len(windows),
                eligible_windows=len(eligible), minimum_fast_pairs=8,
                overlap_p95=float(np.percentile(values, 95)) if values else 0.,
                overlap_max=max(values) if values else 0., worst_window=worst)
