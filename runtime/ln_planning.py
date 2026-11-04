"""Audio-conditioned LN probabilities; independent of generated note history.

The existing audio model supplies section variation. A chart-level prior comes
from the training charts at the requested keys/difficulty/techniques. The prior
is a soft expected proportion, never a duration cap or post-generation edit.
"""
import numpy as np
import torch
from scipy.ndimage import gaussian_filter1d
from scipy.special import expit, logit


def audio_ln_plan(prediction, keys, target):
    probability = np.clip(prediction['hold'][:, :keys], 1e-5, 1-1e-5)
    # The head classifier was trained with positive BCE weight 2.
    posterior = probability/(2-probability)
    weights = np.maximum(prediction['onset'][:, :keys], 1e-4)
    evidence = (posterior*weights).sum(1)/weights.sum(1)
    # Smooth context rather than using lane-specific noise as musical intent.
    evidence = gaussian_filter1d(logit(np.clip(evidence, 1e-5, 1-1e-5)), 100, mode='nearest')
    weight = np.maximum(prediction['any_onset'], 1e-4)
    low, high = -40., 40.
    for _ in range(50):
        offset = (low+high)/2
        if np.average(expit(evidence+offset), weights=weight) < target:
            low = offset
        else:
            high = offset
    return expit(evidence+(low+high)/2).astype(np.float32)


def calibrated_count_probabilities(logits, desired, counts):
    """Exponential tilt preserves learned relative probabilities at equal count.

    Find the smallest common per-LN log-odds shift matching the audio plan's
    expected hold count. Masked illegal chords remain masked. No hard quota:
    both taps and LNs remain possible, including fully held chords.
    """
    legal = logits > -9999
    maximum = torch.where(legal, counts[None], 0).max(-1).values
    minimum = torch.where(legal, counts[None], 128).min(-1).values
    desired = torch.minimum(torch.maximum(desired, minimum), maximum)
    lower = torch.full_like(desired, -80.)
    upper = torch.full_like(desired, 80.)
    for _ in range(18):
        bias = (lower+upper)/2
        probabilities = torch.softmax(logits+bias[:, None]*counts[None], -1)
        expected = (probabilities*counts[None]).sum(-1)
        below = expected < desired
        lower = torch.where(below, bias, lower)
        upper = torch.where(below, upper, bias)
    return torch.softmax(logits+((lower+upper)/2)[:, None]*counts[None], -1)


def calibrated_hold_probabilities(logits, heads, target, counts):
    return calibrated_count_probabilities(logits,counts[heads]*target,counts)


def audio_chord_plan(prediction, keys, mean_chord):
    probability=np.clip(prediction['onset'][:,:keys],1e-5,1-1e-5)
    lane_posterior=probability/(12-11*probability)
    union=np.clip(prediction['any_onset'],1e-5,1-1e-5)
    union_posterior=union/(5-4*union)
    expected=lane_posterior.sum(1)/np.maximum(union_posterior,1e-3)
    extra=np.clip((expected-1)/(keys-1),1e-3,1-1e-3)
    evidence=gaussian_filter1d(logit(extra),25,mode='nearest')
    weight=np.maximum(union,1e-4)
    low,high=-40.,40.
    for _ in range(50):
        offset=(low+high)/2
        if np.average(1+(keys-1)*expit(evidence+offset),weights=weight)<mean_chord:low=offset
        else:high=offset
    return (1+(keys-1)*expit(evidence+(low+high)/2)).astype(np.float32)


def section_summary(notes, window_ms=15000):
    if not notes:return []
    result=[]
    for start in range(0,int(max(n[0] for n in notes))+1,window_ms):
        group=[n for n in notes if start<=n[0]<start+window_ms]
        if group:
            holds=sum(n[3]=='hold' for n in group)
            result.append(dict(start_s=start/1000, notes=len(group), holds=holds, ln_fraction=holds/len(group)))
    return result
