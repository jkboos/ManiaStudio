"""Frozen recurrent backbone with condition-dependent chord/type readouts."""
from pathlib import Path
import torch
from torch import nn

from audio_features import sha256_file
from pattern_model import PatternModel
from technique_models import TechniqueCondition


class OutputTechniqueAdapter(TechniqueCondition, PatternModel):
    def __init__(self, width=256, layers=2):
        super().__init__(width, layers)
        self.technique_projection = nn.ModuleDict({name: nn.Sequential(
            nn.Linear(width + 7, 64), nn.SiLU(), nn.Linear(64, 128)) for name in ('heads', 'holds')})
        for layer in self.technique_projection.values():
            nn.init.zeros_(layer[-1].weight)
            nn.init.zeros_(layer[-1].bias)
        self.technique_condition = None
        self.technique_strength = 1.
        for name, p in self.named_parameters():
            p.requires_grad_(name.startswith('technique_projection.'))

    def train(self, mode=True):
        super().train(mode)
        self.rnn.eval()
        return self

    def disabled(self):
        if self.technique_condition is None:
            raise ValueError('set techniques or explicit zeros to disable')
        return self.technique_strength == 0. or not torch.count_nonzero(self.technique_condition)

    def delta(self, name, states):
        value = self.technique_condition
        if len(value) == 1:
            value = value.expand(len(states), -1)
        if len(value) != len(states):
            raise ValueError('technique batch mismatch')
        value = value[:, None].expand(-1, states.shape[1], -1)
        layer = self.technique_projection[name]
        gate = value.new_ones(*value.shape[:-1], 1)
        return self.technique_strength * (layer(torch.cat([states, value, gate], -1)) -
                                         layer(torch.cat([states, torch.zeros_like(value), torch.zeros_like(gate)], -1)))

    def technique_embedding(self, batch):
        # Magnitude regularizer uses both output branches at a common state.
        states = self.technique_condition.new_zeros(batch, 1, self.width)
        return torch.cat([self.delta(name, states)[:, 0] for name in ('heads', 'holds')], -1)

    def forward(self, *args, **kwargs):
        logits, states, hidden = PatternModel.forward(self, *args, **kwargs)
        if not self.disabled():
            logits = (logits + self.delta('heads', states)).masked_fill(logits <= -9999, -1e4)
        return logits, states, hidden

    def endings(self, states, heads):
        result = PatternModel.endings(self, states, heads)
        if not self.disabled():
            x = self.tail(torch.cat([states, self.head_embedding(heads)], -1))
            original = result['holds']
            result['holds'] = (original + self.delta('holds', x)).masked_fill(original <= -9999, -1e4)
        return result


def load_adapter(path, device):
    saved = torch.load(path, map_location=device, weights_only=True)
    config = saved['config']
    if config['architecture'] != 'output_technique_adapter_v2':
        raise ValueError('not an output technique adapter checkpoint')
    for name in ('pattern_model.py', 'pattern_data.py', 'technique_models.py',
                 'technique_data.py', 'technique_output_adapter.py', 'technique_adapter_data.py'):
        if sha256_file(name) != config['code_sha256'][name]:
            raise ValueError(f'adapter code changed: {name}')
    model = OutputTechniqueAdapter(config['width'], config['layers']).to(device).eval()
    model.load_state_dict(saved['model'])
    return model, saved
