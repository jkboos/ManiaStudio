"""Minimal lane-only repair for exceptionally close repeated presses."""
import bisect

import numpy as np
import torch

from osu_export import validate_notes
from pattern_data import encode_events, event_inputs, audio_at_events, CONTEXT


def close_pairs(notes, min_head_ms=60., min_release_ms=40.):
    previous = {}
    found = []
    for i in sorted(range(len(notes)), key=lambda i: (notes[i][0], notes[i][2])):
        start, end, lane, kind = notes[i]
        if lane in previous:
            j = previous[lane]
            pstart, pend, _, pkind = notes[j]
            head_gap, release_gap = start-pstart, start-pend
            if head_gap < min_head_ms or (pkind == 'hold' and release_gap < min_release_ms):
                found.append({'index': i, 'previous_index': j, 'time_ms': start, 'lane': lane,
                              'head_gap_ms': head_gap,
                              'release_gap_ms': release_gap if pkind == 'hold' else None})
        previous[lane] = i
    return found


def legal_destination(notes, index, lane, min_head_ms, min_release_ms):
    start, end, _, kind = notes[index]
    others = sorted([n for i,n in enumerate(notes) if i != index and n[2] == lane], key=lambda n:n[0])
    at = bisect.bisect_left([n[0] for n in others], start)
    if at:
        previous = others[at-1]
        if start-previous[0] < min_head_ms or start < previous[1]: return False
        if previous[3] == 'hold' and start-previous[1] < min_release_ms: return False
    if at < len(others):
        following = others[at]
        if following[0]-start < min_head_ms or end > following[0]: return False
        if kind == 'hold' and following[0]-end < min_release_ms: return False
    return True


class ModelLaneScorer:
    def __init__(self, model, normalized_features, keys, stars, style, device):
        self.model, self.features, self.keys, self.stars, self.style, self.device = model, normalized_features, keys, stars, style, device

    @torch.inference_mode()
    def __call__(self, notes, index, lanes):
        ordered = sorted(notes, key=lambda n:(n[0],n[2]))
        events = encode_events(ordered)
        at = int(np.searchsorted(events['time'], notes[index][0]))
        first = max(0, at-CONTEXT)
        prev_heads, prev_holds, numbers = event_inputs(events)
        selection = slice(first,at+1)
        audio = audio_at_events(self.features,events['time'][selection],np.zeros(128),np.ones(128))
        tensor = lambda x:torch.as_tensor(x,device=self.device)[None]
        logits, states, _ = self.model(tensor(audio.astype(np.float32)),tensor(prev_heads[selection]),
                tensor(prev_holds[selection]),tensor(numbers[selection]),
                torch.tensor([self.stars],dtype=torch.float32,device=self.device),
                torch.tensor([self.keys],device=self.device),torch.tensor([self.style],device=self.device))
        old_lane = notes[index][2]
        heads = [int(events['heads'][at]) & ~(1<<old_lane) | (1<<lane) for lane in lanes]
        holds = [int(events['holds'][at]) & ~(1<<old_lane) | ((1<<lane) if notes[index][3]=='hold' else 0) for lane in lanes]
        h = torch.tensor(heads,device=self.device)[:,None]
        tail = self.model.endings(states[:,-1:].expand(len(lanes),-1,-1),h)
        head_scores = logits[0,-1].log_softmax(-1)[h[:,0]]
        hold_scores = tail['holds'][:,0].log_softmax(-1)[torch.arange(len(lanes),device=self.device),torch.tensor(holds,device=self.device)]
        return (head_scores + .6*hold_scores).cpu().tolist()


def repair_short_jacks(notes, keys, scorer, min_head_ms=60., min_release_ms=40.):
    """Keep every timestamp, note type and full LN length; move only legal lanes.

    Thresholds are configurable test-chart preferences, not universal standards.
    If no relocation is possible, preserve and report the unresolved pair.
    """
    validate_notes(notes,keys)
    repaired = [list(n) for n in notes]
    initial = close_pairs(repaired,min_head_ms,min_release_ms)
    edits = []
    while True:
        violations = close_pairs(repaired,min_head_ms,min_release_ms)
        changed = False
        for issue in violations:
            # Prefer moving the new press; try its predecessor only if necessary.
            for index in (issue['index'],issue['previous_index']):
                lanes = [lane for lane in range(keys) if lane != repaired[index][2] and
                         legal_destination(repaired,index,lane,min_head_ms,min_release_ms)]
                if not lanes: continue
                scores = scorer(repaired,index,lanes)
                lane = lanes[int(np.argmax(scores))]
                old_lane = repaired[index][2]
                repaired[index][2] = lane
                edits.append({'index':index,'time_ms':repaired[index][0],'end_ms':repaired[index][1],
                              'type':repaired[index][3],'old_lane':old_lane,'new_lane':lane,
                              'joint_model_score':float(max(scores)),'trigger':issue})
                changed = True
                break
            if changed: break
        if not changed: break
        assert len(close_pairs(repaired,min_head_ms,min_release_ms)) < len(violations)
    validate_notes(repaired,keys)
    assert [(n[0],n[1],n[3]) for n in repaired] == [(n[0],n[1],n[3]) for n in notes]
    remaining = close_pairs(repaired,min_head_ms,min_release_ms)
    repaired.sort(key=lambda n:(n[0],n[2]))
    return repaired, {'min_head_gap_ms':min_head_ms,'min_release_gap_ms':min_release_ms,
                      'initial_pairs':len(initial),'remaining_pairs':len(remaining),'moved_notes':len(edits),
                      'edits':edits,'unresolved':remaining,
                      'preserved':['all timestamps','all note types','all full LN durations','note count'],
                      'note':'Local lane repair using learned chord scores; no retraining or global pattern regeneration.'}
