"""Audio-aligned note heads and explicitly supervised, uncapped LN durations."""
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
import gzip
import json
import math
from pathlib import Path
import random

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from audio_features import FeatureStore


@dataclass(frozen=True)
class FrameSpec:
    hop_ms: int = 10
    core_frames: int = 400
    context_frames: int = 200
    width: int = 128
    layers: int = 2
    dropout: float = .1

    @property
    def frames(self):
        return self.core_frames + 2 * self.context_frames


def frame_labels(notes, start_frame, spec=FrameSpec()):
    shape = (spec.frames, 7)
    onset, heads, hold, duration = [np.zeros(shape, dtype=np.float32) for _ in range(4)]
    for start, end, lane, kind in notes:
        frame = int(math.floor(start / spec.hop_ms + .5)) - start_frame
        if 0 <= frame < spec.frames:
            # Keep complete LN length, even when its head or tail crosses context.
            if heads[frame, lane]:
                raise ValueError('two same-lane heads quantize to one frame')
            heads[frame, lane] = 1
            hold[frame, lane] = kind == 'hold'
            if kind == 'hold':
                duration[frame, lane] = math.log1p((end - start) / 1000)
        for delta, value in ((-2, .15), (-1, .6), (0, 1.), (1, .6), (2, .15)):
            at = frame + delta
            if 0 <= at < spec.frames:
                onset[at, lane] = max(onset[at, lane], value)
    loss_mask = np.zeros(spec.frames, dtype=bool)
    loss_mask[spec.context_frames:spec.context_frames + spec.core_frames] = True
    return dict(onset=onset, heads=heads, hold=hold, duration=duration,
                any_onset=onset.max(axis=1), loss_mask=loss_mask)


class FrameSampler:
    def __init__(self, root, split, seed=42, spec=FrameSpec()):
        self.root, self.spec, self.store = Path(root), spec, FeatureStore(root)
        self.rng = random.Random(seed)
        self.rows = [json.loads(s) for s in (self.root / 'splits' / f'{split}.jsonl').read_text(encoding='utf-8').splitlines()]
        self.groups = {4: defaultdict(list), 7: defaultdict(list)}
        for r in self.rows:
            self.groups[r['key_count']][r['song_group_id']].append(r)
        self.rejected = 0

    @lru_cache(maxsize=128)
    def notes(self, path):
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            return json.load(f)['notes']

    def make(self, row, core_start):
        first = core_start - self.spec.context_frames
        sample = frame_labels(self.notes(row['chart_file']), first, self.spec)
        window = self.store.read_window(row['feature_audio_id'], first, self.spec.frames)
        sample.update(features=window['features'], valid=window['valid_mask'],
                      stars=row['star_rating'], keys=row['key_count'], chart_id=row['chart_id'],
                      audio_id=row['feature_audio_id'], core_start=core_start)
        sample['loss_mask'] &= sample['valid']
        return sample

    def sample(self):
        for _ in range(100):
            keys = self.rng.choice([k for k in (4, 7) if self.groups[k]])
            group = self.rng.choice(list(self.groups[keys]))
            row = self.rng.choice(self.groups[keys][group])
            if self.rng.random() < .8:
                note = self.rng.choice(self.notes(row['chart_file']))
                first = max(0, int(note[0] / self.spec.hop_ms) - self.rng.randrange(self.spec.core_frames))
            else:
                first = self.rng.randrange(max(1, row['feature_frames']))
            try:
                return self.make(row, first)
            except ValueError:
                self.rejected += 1
        raise RuntimeError('too many unrepresentable training windows')


def frame_batch(samples, device):
    arrays = {k: np.stack([s[k] for s in samples]) for k in
              ('features', 'valid', 'onset', 'heads', 'hold', 'duration', 'any_onset', 'loss_mask')}
    arrays['stars'] = np.asarray([s['stars'] for s in samples], dtype=np.float32)
    arrays['keys'] = np.asarray([s['keys'] for s in samples], dtype=np.int64)
    return {k: torch.as_tensor(v, device=device) for k, v in arrays.items()}


class FrameModel(nn.Module):
    def __init__(self, spec=FrameSpec()):
        super().__init__()
        self.spec = spec
        d = spec.width
        self.local = nn.Sequential(nn.Conv1d(256, d, 5, padding=2), nn.GELU(),
                                   nn.Conv1d(d, d, 5, padding=2), nn.GELU())
        self.coarse = nn.Sequential(nn.Conv1d(d, d, 5, stride=2, padding=2), nn.GELU(),
                                    nn.Conv1d(d, d, 5, stride=2, padding=2), nn.GELU())
        self.keys = nn.Embedding(2, d)
        self.stars = nn.Sequential(nn.Linear(1, d), nn.SiLU(), nn.Linear(d, d))
        self.position = nn.Embedding((spec.frames + 3) // 4, d)
        layer = nn.TransformerEncoderLayer(d, 4, d * 4, spec.dropout, activation='gelu',
                                            batch_first=True, norm_first=True)
        self.context = nn.TransformerEncoder(layer, spec.layers, norm=nn.LayerNorm(d), enable_nested_tensor=False)
        self.fusion = nn.Sequential(nn.Conv1d(2 * d, d, 3, padding=1), nn.GELU())
        self.onset = nn.Conv1d(d, 7, 1)
        self.any_onset = nn.Conv1d(d, 1, 1)
        self.hold = nn.Conv1d(d, 7, 1)
        self.duration = nn.Conv1d(d, 7, 1)

    def forward(self, features, valid, stars, keys):
        difference = torch.diff(features, dim=1, prepend=features[:, :1])
        local = self.local(torch.cat([features, difference], dim=-1).transpose(1, 2))
        coarse = self.coarse(local).transpose(1, 2)
        condition = self.keys((keys == 7).long()) + self.stars(stars[:, None] / 10)
        coarse = coarse + condition[:, None] + self.position(torch.arange(coarse.shape[1], device=features.device))[None]
        mask = valid[:, None].float()
        for _ in range(2):
            mask = F.max_pool1d(mask, 5, stride=2, padding=2)
        coarse = self.context(coarse, src_key_padding_mask=~mask[:, 0].bool())
        coarse = F.interpolate(coarse.transpose(1, 2), size=local.shape[-1], mode='linear', align_corners=False)
        merged = self.fusion(torch.cat([local, coarse], dim=1))
        return {'onset': self.onset(merged).transpose(1, 2),
                'any_onset': self.any_onset(merged)[:, 0],
                'hold': self.hold(merged).transpose(1, 2),
                'duration': F.softplus(self.duration(merged).transpose(1, 2))}


def frame_loss(prediction, batch):
    lane_mask = torch.arange(7, device=batch['keys'].device)[None, None] < batch['keys'][:, None, None]
    mask = batch['loss_mask'][:, :, None] & lane_mask
    def weighted_bce(logits, target, weight, selected):
        raw = F.binary_cross_entropy_with_logits(logits, target, reduction='none')
        raw = raw * (1 + (weight - 1) * target)
        return raw.masked_select(selected).mean()
    onset = weighted_bce(prediction['onset'], batch['onset'], 12., mask)
    union = weighted_bce(prediction['any_onset'], batch['any_onset'], 5., batch['loss_mask'])
    heads = (batch['heads'] > 0) & mask
    holds = (batch['hold'] > 0) & heads
    hold = weighted_bce(prediction['hold'], batch['hold'], 2., heads) if heads.any() else prediction['hold'].sum() * 0
    duration = F.smooth_l1_loss(prediction['duration'][holds], batch['duration'][holds]) if holds.any() else prediction['duration'].sum() * 0
    return onset + union + .5 * hold + 2 * duration, {
        'onset': onset.detach(), 'any_onset': union.detach(), 'hold': hold.detach(), 'duration': duration.detach()}
