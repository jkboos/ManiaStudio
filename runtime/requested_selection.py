"""Uniform candidate selection that respects explicit LN and low-jack intent."""
import math
import numpy as np
from chart_pressure import head_events, pressure_windows, local_pressure_summary


def multiscale_pressure(notes,keys):
    times,masks=head_events(notes)
    scales=[]
    for width in (2000.,4000.,8000.):
        rows=[w for w in pressure_windows(times,masks,keys,width,width/4) if w['fast_pairs']>=8]
        values=[w['fast_overlap_pair_fraction'] for w in rows]
        scales.append(dict(window_ms=width,eligible_windows=len(rows),
            p95=float(np.percentile(values,95)) if values else None,
            maximum=max(values) if values else None))
    populated=[s for s in scales if s['eligible_windows']]
    fallback=local_pressure_summary(times,masks,keys)
    return dict(scales=scales,
        p95=max(s['p95'] for s in populated) if populated else fallback['overlap_p95'],
        maximum=max(s['maximum'] for s in populated) if populated else fallback['overlap_max'],
        limitation='Fast head-overlap diagnostics; not a complete score of LN burden or playability.')


def select_requested_candidate(candidates,target_stars,profile,star_tolerance=None,ln_tolerance=.15):
    if not candidates:raise ValueError('need candidates')
    tolerance=max(.5,.05*target_stars) if star_tolerance is None else star_tolerance
    if not math.isfinite(tolerance) or tolerance<0:raise ValueError('invalid star tolerance')
    eligible=[c for c in candidates if c['absolute_star_error']<=tolerance]
    if not eligible:
        chosen=min(candidates,key=lambda c:c['absolute_star_error'])
        return chosen,dict(policy='requested-techniques',reason='no_candidate_within_star_tolerance',
            selected_candidate=chosen['candidate'],star_tolerance=tolerance,eligible_candidates=[],
            requirement_met=False)
    requested=profile['requested'];ln_candidates=eligible;ln_met=None;target_ln=None
    if 'LN' in requested:
        target_ln=profile['raw']['LN']
        ln_error=lambda c:abs(c['ln_count']/max(1,c['ln_count']+c['note_count'])-target_ln)
        matching=[c for c in eligible if ln_error(c)<=ln_tolerance]
        ln_met=bool(matching)
        # Never hide a failed control request. If no approximate LN match is
        # available, retain the closest LN candidate(s) and report the miss.
        best_error=min(map(ln_error,eligible))
        ln_candidates=matching or [c for c in eligible if ln_error(c)<=best_error+1e-9]
    if requested.get('jack')=='low':
        chosen=min(ln_candidates,key=lambda c:(c['multiscale_pressure']['p95'],
            c['multiscale_pressure']['maximum'],c['technique_distance'],c['absolute_star_error']))
        reason='explicit_low_jack_prioritizes_local_pressure_after_ln_feasibility'
    else:
        chosen=min(ln_candidates,key=lambda c:(c['technique_distance'],c['absolute_star_error']))
        reason='requested_profile_after_ln_feasibility'
    return chosen,dict(policy='requested-techniques',reason=reason,selected_candidate=chosen['candidate'],
        star_tolerance=tolerance,eligible_candidates=[c['candidate'] for c in eligible],
        ln_target=target_ln,ln_absolute_tolerance=ln_tolerance if target_ln is not None else None,
        ln_request_within_tolerance=ln_met,profile_eligible_candidates=[c['candidate'] for c in ln_candidates],
        uses_song_identity=False,changes_candidate_notes=False,
        limitation='Candidate preference with a 15-percentage-point LN tolerance; other technique axes and playability are not guaranteed.')
