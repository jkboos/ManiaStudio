"""Causal joint-chord model with incremental GRU state and explicit LN state."""
import torch
from torch import nn
from torch.nn import functional as F


class PatternModel(nn.Module):
    def __init__(self, width=256, layers=2):
        super().__init__()
        self.width, self.layers = width, layers
        self.audio = nn.Sequential(nn.LayerNorm(640), nn.Linear(640, 256), nn.SiLU(), nn.Linear(256, 192))
        self.head_embedding = nn.Embedding(128, 64)
        self.hold_embedding = nn.Embedding(128, 32)
        self.numbers = nn.Sequential(nn.Linear(24, 64), nn.SiLU())
        self.keys = nn.Embedding(2, 16)
        self.style = nn.Embedding(2, 16)
        self.stars = nn.Sequential(nn.Linear(1, 32), nn.SiLU())
        self.input = nn.Linear(192 + 64 + 32 + 64 + 64, width)
        self.rnn = nn.GRU(width, width, layers, batch_first=True, dropout=.1 if layers > 1 else 0.)
        self.heads = nn.Linear(width, 128)
        self.tail = nn.Sequential(nn.Linear(width + 64, width), nn.SiLU())
        self.holds = nn.Linear(width, 128)
        self.duration = nn.Linear(width, 8)
        self.shared = nn.Linear(width, 1)
        self.register_buffer('bits', ((torch.arange(128)[:, None] >> torch.arange(7)) & 1).bool())

    def forward(self, audio, prev_heads, prev_holds, numbers, stars, keys, style, hidden=None):
        condition = torch.cat([self.keys((keys == 7).long()), self.style(style), self.stars(stars[:, None] / 10)], -1)
        condition = condition[:, None].expand(-1, audio.shape[1], -1)
        x = torch.cat([self.audio(audio), self.head_embedding(prev_heads), self.hold_embedding(prev_holds),
                       self.numbers(numbers), condition], -1)
        states, hidden = self.rnn(F.silu(self.input(x)), hidden)
        logits = self.heads(states)
        occupied = numbers[..., 7:14] > 0
        invalid = (occupied[:, :, None] & self.bits[None, None]).any(-1)
        labels = torch.arange(128, device=audio.device)[None, None]
        invalid |= (labels == 0) | (labels >= (1 << keys[:, None, None]))
        return logits.masked_fill(invalid, -1e4), states, hidden

    def endings(self, states, heads):
        x = self.tail(torch.cat([states, self.head_embedding(heads)], -1))
        logits = self.holds(x)
        choices = torch.arange(128, device=x.device)
        invalid = (choices & heads[..., None]) != choices
        return {'holds': logits.masked_fill(invalid, -1e4), 'duration': F.softplus(self.duration(x)),
                'shared': self.shared(x).squeeze(-1)}


def pattern_loss(model, batch, history_drop=0.):
    prev_heads, prev_holds, numbers = batch['prev_heads'], batch['prev_holds'], batch['numbers']
    if history_drop:
        # Occasional token dropout reduces dependence on perfect teacher history.
        drop = torch.rand_like(prev_heads.float()) < history_drop
        prev_heads = prev_heads.masked_fill(drop, 0)
        prev_holds = prev_holds.masked_fill(drop, 0)
    logits, states, _ = model(batch['audio'], prev_heads, prev_holds, numbers, batch['stars'], batch['keys'], batch['style'])
    tail = model.endings(states, batch['heads'])
    mask = batch['mask']
    head_loss = F.cross_entropy(logits[mask], batch['heads'][mask])
    hold_loss = F.cross_entropy(tail['holds'][mask], batch['holds'][mask])
    hold_bits = model.bits[batch['holds']] & mask[..., None]
    duration_loss = F.smooth_l1_loss(tail['duration'][..., :7][hold_bits], batch['duration'][hold_bits]) if hold_bits.any() else states.sum() * 0
    shared_mask = (hold_bits.sum(-1) >= 2) & mask
    shared_loss = F.binary_cross_entropy_with_logits(tail['shared'][shared_mask], batch['shared'][shared_mask].float()) if shared_mask.any() else states.sum() * 0
    common = shared_mask & batch['shared'].bool()
    common_duration = (batch['duration'] * hold_bits).sum(-1) / hold_bits.sum(-1).clamp_min(1)
    common_loss = F.smooth_l1_loss(tail['duration'][..., 7][common], common_duration[common]) if common.any() else states.sum() * 0
    return head_loss + .6 * hold_loss + 2 * duration_loss + .2 * shared_loss + common_loss, logits, tail
