"""Soft lane-history costs for decoding; these are not learned pattern weights."""
from collections import defaultdict

import numpy as np


RECOVERY_MS = 220.
REPEAT_STRENGTH = 3.


def history_weights(base_weights, time_ms, last_head, run_lengths):
    """Keep every available lane possible, while discouraging fast repeat runs.

    Strong model preference or LN occupancy can still produce intentional jacks.
    The recovery window is a soft scoring parameter, never a minimum spacing.
    """
    gap = time_ms - last_head
    pressure = np.where(last_head >= 0, np.maximum(0., 1. - gap / RECOVERY_MS), 0.)
    cost = REPEAT_STRENGTH * pressure * (1. + .75 * np.maximum(0, run_lengths - 1))
    # Bound the numerical cost, not the length of a permitted repeat run.
    return base_weights * np.exp(-np.minimum(cost, 20.))


def pattern_metrics(notes, keys, interval_ms=150.):
    """Diagnostic repeat counts include chord heads; no playability verdict."""
    last = np.full(keys, -np.inf)
    runs = np.zeros(keys, dtype=int)
    repeats = triples = longest = 0
    lane_counts = np.zeros(keys, dtype=int)
    events = defaultdict(list)
    for start, _, lane, _ in sorted(notes, key=lambda n: (n[0], n[2])):
        close = 0 < start - last[lane] <= interval_ms
        repeats += int(close)
        runs[lane] = runs[lane] + 1 if close else 1
        triples += int(runs[lane] >= 3)
        longest = max(longest, int(runs[lane]))
        last[lane] = start
        lane_counts[lane] += 1
        events[start].append(lane)
    pairs = repeated_pairs = 0
    previous = None
    for time, lanes in sorted(events.items()):
        if previous is not None and 0 < time - previous[0] <= interval_ms and len(lanes) == len(previous[1]) == 1:
            pairs += 1
            repeated_pairs += int(lanes[0] == previous[1][0])
        previous = time, lanes
    return {'interval_ms': interval_ms, 'objects': len(notes), 'repeat_heads': repeats,
            'repeat_fraction': repeats / max(1, len(notes)), 'heads_in_run_position_3_or_later': triples,
            'longest_chain': longest, 'lane_counts': lane_counts.tolist(),
            'adjacent_single_pairs': pairs, 'repeated_single_pairs': repeated_pairs,
            'single_pair_repeat_fraction': repeated_pairs / max(1, pairs)}
