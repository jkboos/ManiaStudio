"""Controlled low-frequency onset side channel for the existing rhythm model."""
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from mania_frames import FrameModel, FrameSpec


class BassFrameModel(FrameModel):
    def __init__(self, spec=FrameSpec(), normalization=None, enabled=True):
        super().__init__(spec)
        if normalization is None:
            raise ValueError('training normalization is required')
        self.low_band_enabled = bool(enabled)
        self.register_buffer('mel_mean', torch.tensor(normalization['mean'], dtype=torch.float32))
        self.register_buffer('mel_std', torch.tensor(normalization['std'], dtype=torch.float32))
        mel_max = 2595 * np.log10(1 + 12000 / 700)
        centers = 700 * (10 ** (np.linspace(0, mel_max, 130)[1:-1] / 2595) - 1)
        self.register_buffer('low_band_indices', torch.tensor(np.flatnonzero((centers >= 30) & (centers <= 250))))
        self.rhythm_adapter = nn.Conv1d(1, 128, 5, padding=2, bias=False)
        nn.init.zeros_(self.rhythm_adapter.weight)

    def low_band_onsets(self, features, valid):
        # Reconstruct dB from the unchanged training-only normalized log-Mel.
        db = features.float() * self.mel_std + self.mel_mean
        power = torch.pow(10., db.index_select(-1, self.low_band_indices).clamp(-100, 20) / 10)
        envelope = power.mean(-1).sqrt() * valid
        # Causal local level estimate: 51 frames = 510 ms, with valid-only padding.
        total = F.avg_pool1d(F.pad(envelope[:, None], (50, 0)), 51, stride=1)[:, 0]
        count = F.avg_pool1d(F.pad(valid[:, None].float(), (50, 0)), 51, stride=1)[:, 0]
        level = total / count.clamp_min(1 / 51)
        rise = torch.diff(envelope, dim=1, prepend=envelope[:, :1]).clamp_min(0)
        adjacent_valid = valid & torch.cat([torch.zeros_like(valid[:, :1]), valid[:, :-1]], 1)
        relative = (rise / level.clamp_min(1e-5)).clamp_max(100)
        return torch.log1p(10 * relative) / 5 * adjacent_valid

    def forward(self, features, valid, stars, keys):
        auxiliary = self.low_band_onsets(features, valid)
        # Both arms contain the same adapter and parameters. The control sees zero.
        auxiliary = auxiliary * float(self.low_band_enabled)
        residual = self.rhythm_adapter(auxiliary[:, None]).transpose(1, 2) * valid[..., None]
        return super().forward(features + residual, valid, stars, keys)

    def initialize_from_frame(self, state):
        missing, unexpected = self.load_state_dict(state, strict=False)
        expected = {'mel_mean', 'mel_std', 'low_band_indices', 'rhythm_adapter.weight'}
        if set(missing) != expected or unexpected:
            raise ValueError(f'unexpected initialization mismatch: {missing}, {unexpected}')


FEATURE_DESCRIPTION = {
    'band_hz': [30, 250], 'local_level_frames': 51, 'hop_ms': 10,
    'definition': 'Positive change in low-band RMS Mel energy, divided by trailing valid mean; log1p compressed.',
    'adapter': 'Zero-initialized 1-to-128 convolution, kernel 5, added to unchanged normalized Mel.',
    'feature_normalization': 'Existing train-only Mel mean/std; no validation-derived auxiliary statistics.',
    'note': 'An extra rhythm cue, not a beat label or an EQ change to the exported audio.'}
