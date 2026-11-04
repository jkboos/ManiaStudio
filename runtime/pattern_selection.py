"""Candidate ranking preferences, not a learned or universal playability score."""
from collections import defaultdict, deque
import math


def repetition_metrics(notes, keys):
    """Detect sustained rapid repetitions, including simultaneous chord heads.

    Short repetitions remain unpenalized. A repeated chord may span slightly
    longer gaps than an individual rapid jack. All values are diagnostics;
    nothing here changes notes or forbids intentional jack patterns.
    """
    events = defaultdict(list)
    for start, _, lane, _ in notes:
        events[start].append(lane)
    last = [float('-inf')] * keys
    lane_runs = [0] * keys
    previous_time, previous_mask, chord_run = float('-inf'), 0, 0
    longest_chord = longest_lane = flagged_total = object_total = 0
    window = deque()
    window_objects = window_flagged = 0
    worst_fraction = 0.
    worst_start = worst_end = None
    chord_runs = []
    run_start = None
    for time, lanes in sorted(events.items()):
        mask = sum(1 << lane for lane in lanes)
        continues = len(lanes) >= 2 and mask == previous_mask and time - previous_time <= 200
        if not continues:
            if chord_run > 4:
                chord_runs.append(dict(start_ms=run_start, end_ms=previous_time,
                                       events=chord_run, mask=previous_mask))
            chord_run = 0
            run_start = time
        chord_run = chord_run + 1 if len(lanes) >= 2 else 0
        longest_chord = max(longest_chord, chord_run)
        flagged = 0
        for lane in lanes:
            lane_runs[lane] = lane_runs[lane] + 1 if time - last[lane] <= 150 else 1
            last[lane] = time
            longest_lane = max(longest_lane, lane_runs[lane])
            flagged += int(lane_runs[lane] > 4 or chord_run > 4)
        object_total += len(lanes)
        flagged_total += flagged
        window.append((time, len(lanes), flagged))
        window_objects += len(lanes)
        window_flagged += flagged
        while window and window[0][0] < time - 8000:
            _, old_objects, old_flagged = window.popleft()
            window_objects -= old_objects
            window_flagged -= old_flagged
        # Avoid unstable ratios in nearly empty windows.
        if window_objects >= 32 and window_flagged / window_objects > worst_fraction:
            worst_fraction = window_flagged / window_objects
            worst_start, worst_end = window[0][0], time
        previous_time, previous_mask = time, mask
    if chord_run > 4:
        chord_runs.append(dict(start_ms=run_start, end_ms=previous_time,
                               events=chord_run, mask=previous_mask))
    return dict(longest_repeated_chord=longest_chord, longest_rapid_lane_chain=longest_lane,
                sustained_repeat_heads=flagged_total,
                sustained_repeat_fraction=flagged_total / max(1, object_total),
                worst_8s_repeat_fraction=worst_fraction,
                worst_window_ms=[worst_start, worst_end],
                repeated_chord_runs=sorted(chord_runs, key=lambda r: r['events'], reverse=True),
                preferences=dict(lane_gap_ms=150, chord_gap_ms=200, unpenalized_run_heads=4,
                                 window_ms=8000, minimum_window_objects=32))


def select_candidate(candidates, target_stars, style='normal', policy='balanced', star_tolerance=None, technique_slack=.25):
    if not candidates:
        raise ValueError('need candidates')
    if policy not in ('balanced', 'closest', 'pressure','techniques','techniques-local'):
        raise ValueError('unknown candidate selection policy')
    tolerance = max(.5 if policy in ('pressure','techniques','techniques-local') else .3, .05 * target_stars) if star_tolerance is None else star_tolerance
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError('star tolerance must be nonnegative and finite')
    if not math.isfinite(technique_slack) or technique_slack < 0:
        raise ValueError('technique slack must be nonnegative and finite')
    eligible = [c for c in candidates if c['absolute_star_error'] <= tolerance]
    profile_eligible=[]
    if policy == 'closest' or (style == 'dan' and policy not in ('techniques','techniques-local')) or not eligible:
        chosen = min(candidates, key=lambda c: c['absolute_star_error'])
        reason = ('explicit_closest' if policy == 'closest' else
                  'dan_style_preserves_repetition' if style == 'dan' and policy not in ('techniques','techniques-local') else 'no_candidate_within_tolerance')
    elif policy=='techniques-local':
        best_distance=min(c['technique_distance'] for c in eligible)
        profile_eligible=[c for c in eligible if c['technique_distance']<=best_distance+technique_slack]
        chosen=min(profile_eligible,key=lambda c:(c['local_pressure']['overlap_p95'],
            c['local_pressure']['overlap_max'],c['technique_distance'],c['absolute_star_error']))
        reason='reduce_local_overlap_among_nearby_technique_profiles'
    elif policy=='techniques':
        chosen=min(eligible,key=lambda c:(c['technique_distance'],c['absolute_star_error']))
        reason='match_requested_technique_profile_within_star_tolerance'
    elif policy == 'pressure':
        chosen = min(eligible, key=lambda c: (
            c['local_pressure']['overlap_p95'],
            c['repetition_metrics']['worst_8s_repeat_fraction'], c['absolute_star_error']))
        reason = 'reduce_local_overlapping_chords_within_star_tolerance'
    else:
        chosen = min(eligible, key=lambda c: (
            c['repetition_metrics']['worst_8s_repeat_fraction'],
            c['repetition_metrics']['sustained_repeat_fraction'], c['absolute_star_error']))
        reason = 'reduce_sustained_local_repetition_within_star_tolerance'
    return chosen, dict(policy=policy, reason=reason, star_tolerance=tolerance,
                        eligible_candidates=[c['candidate'] for c in eligible],
                        selected_candidate=chosen['candidate'],
                        **({'technique_distance_slack':technique_slack,
                            'profile_eligible_candidates':[c['candidate'] for c in profile_eligible]} if policy=='techniques-local' else {}),
                        limitation='Heuristic candidate preference; not human playability verification or model retraining.')
