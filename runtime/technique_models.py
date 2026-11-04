"""Add six continuous conditions without modifying legacy model code/hashes."""
import torch
from torch import nn
from torch.nn import functional as F
from pattern_model import PatternModel
from mania_frames import FrameModel


class TechniqueCondition:
    def setup_techniques(self,width):
        self.technique_projection=nn.Sequential(nn.Linear(6,64),nn.SiLU(),nn.Linear(64,width))
        nn.init.zeros_(self.technique_projection[-1].weight)
        nn.init.zeros_(self.technique_projection[-1].bias)
        self.technique_condition=None

    def set_techniques(self,values):
        if values.ndim!=2 or values.shape[-1]!=6 or not torch.isfinite(values).all():
            raise ValueError('expected finite batch x six technique conditions')
        self.technique_condition=values

    def technique_embedding(self,batch):
        if self.technique_condition is None:raise ValueError('technique condition has not been set')
        value=self.technique_condition
        if len(value)==1:value=value.expand(batch,-1)
        if len(value)!=batch:raise ValueError('technique batch mismatch')
        return self.technique_projection(value)


class TechniquePatternModel(TechniqueCondition,PatternModel):
    def __init__(self,width=256,layers=2):
        super().__init__(width,layers);self.setup_techniques(width)

    def forward(self,audio,prev_heads,prev_holds,numbers,stars,keys,style,hidden=None):
        condition=torch.cat([self.keys((keys==7).long()),self.style(style),self.stars(stars[:,None]/10)],-1)
        condition=condition[:,None].expand(-1,audio.shape[1],-1)
        x=torch.cat([self.audio(audio),self.head_embedding(prev_heads),self.hold_embedding(prev_holds),
                     self.numbers(numbers),condition],-1)
        states,hidden=self.rnn(F.silu(self.input(x)+self.technique_embedding(len(audio))[:,None]),hidden)
        logits=self.heads(states)
        occupied=numbers[...,7:14]>0
        invalid=(occupied[:,:,None]&self.bits[None,None]).any(-1)
        labels=torch.arange(128,device=audio.device)[None,None]
        invalid|=(labels==0)|(labels>=(1<<keys[:,None,None]))
        return logits.masked_fill(invalid,-1e4),states,hidden


class TechniqueFrameModel(TechniqueCondition,FrameModel):
    def __init__(self,spec):
        super().__init__(spec);self.setup_techniques(spec.width)

    def forward(self,features,valid,stars,keys):
        difference=torch.diff(features,dim=1,prepend=features[:,:1])
        local=self.local(torch.cat([features,difference],dim=-1).transpose(1,2))
        coarse=self.coarse(local).transpose(1,2)
        condition=self.keys((keys==7).long())+self.stars(stars[:,None]/10)+self.technique_embedding(len(features))
        coarse=coarse+condition[:,None]+self.position(torch.arange(coarse.shape[1],device=features.device))[None]
        mask=valid[:,None].float()
        for _ in range(2):mask=F.max_pool1d(mask,5,stride=2,padding=2)
        coarse=self.context(coarse,src_key_padding_mask=~mask[:,0].bool())
        coarse=F.interpolate(coarse.transpose(1,2),size=local.shape[-1],mode='linear',align_corners=False)
        merged=self.fusion(torch.cat([local,coarse],dim=1))
        return dict(onset=self.onset(merged).transpose(1,2),any_onset=self.any_onset(merged)[:,0],
                    hold=self.hold(merged).transpose(1,2),duration=F.softplus(self.duration(merged).transpose(1,2)))


def initialize_legacy(model,state):
    result=model.load_state_dict(state,strict=False)
    assert not result.unexpected_keys and all(k.startswith('technique_projection.') for k in result.missing_keys)
