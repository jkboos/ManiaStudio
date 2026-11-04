from pathlib import Path
import sys
import numpy as np
import torch
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from ln_planning import audio_ln_plan, audio_chord_plan, calibrated_hold_probabilities, calibrated_count_probabilities
from generation_policy import select_candidate
from style_decode import decode_batch


def test_joint_hold_calibration_keeps_legal_masks_and_relative_patterns():
    counts=torch.tensor([int(i).bit_count() for i in range(128)],dtype=torch.float32)
    heads=torch.tensor([3,15,127,1,0])
    logits=torch.randn(5,128)*3
    invalid=(torch.arange(128)[None]&heads[:,None])!=torch.arange(128)[None]
    logits.masked_fill_(invalid,-1e4)
    # Simulate near-absorbing all-tap/all-hold model predictions.
    logits[0,0]=30;logits[1,15]=30
    target=torch.tensor([.2,.35,.98,.1,0.])
    result=calibrated_hold_probabilities(logits,heads,target,counts)
    assert torch.allclose(result.sum(-1),torch.ones(5))
    assert torch.allclose((result*counts).sum(-1),counts[heads]*target,atol=.001)
    assert torch.all(result[invalid]==0)
    assert result[2,127]>0 # intentional high-LN style remains possible
    assert torch.allclose(result[0,1]/result[0,2],torch.exp(logits[0,1]-logits[0,2]),rtol=.002)


def test_audio_plan_matches_requested_prior_and_varies_with_audio():
    prediction=dict(hold=np.r_[np.full((1000,7),.1),np.full((1000,7),.8)],
                    onset=np.full((2000,7),.5),any_onset=np.ones(2000))
    low=audio_ln_plan(prediction,4,.2)
    high=audio_ln_plan(prediction,7,.8)
    assert np.mean(low)==pytest.approx(.2,abs=1e-5)
    assert np.mean(high)==pytest.approx(.8,abs=1e-5)
    assert low[:500].mean()<low[-500:].mean()
    assert np.all(high>low)
    assert np.max(np.abs(np.diff(low)))<.01


def test_chord_plan_and_occupied_lane_capacity():
    prediction=dict(onset=np.r_[np.full((1000,7),.4),np.full((1000,7),.8)],any_onset=np.full(2000,.8))
    plan=audio_chord_plan(prediction,4,1.6)
    assert plan.mean()==pytest.approx(1.6,abs=1e-5)
    assert plan[:500].mean()<plan[-500:].mean()
    counts=torch.tensor([int(i).bit_count() for i in range(128)],dtype=torch.float32)
    logits=torch.full((1,128),-1e4);logits[0,1]=0 # only one free lane
    probabilities=calibrated_count_probabilities(logits,torch.tensor([3.]),counts)
    assert probabilities[0,1]==pytest.approx(1.)
    assert probabilities[0,0]==0


def test_selection_does_not_trade_away_target_difficulty():
    def candidate(i,stars,pressure):
        return dict(candidate=i,actual_stars=stars,absolute_star_error=abs(3.5-stars),
                    technique_distance=0,local_pressure=dict(overlap_p95=pressure,overlap_max=pressure))
    cs=[candidate(0,3.24,.70),candidate(1,2.73,.19),candidate(2,4.2,.01)]
    chosen,report=select_candidate(cs,3.5,policy='techniques-local',star_tolerance=.5)
    assert chosen['candidate']==0
    cs[0]['local_pressure']=dict(overlap_p95=.3,overlap_max=.3)
    assert select_candidate(cs,3.5,policy='techniques-local',star_tolerance=.5)[0]['candidate']==0
    with pytest.raises(ValueError,match='No candidate within'):
        select_candidate([cs[1]],3.5,policy='techniques-local',star_tolerance=.5)
    cs.append(candidate(3,3.42,.35))
    assert select_candidate(cs,3.5,policy='techniques-local',star_tolerance=.5)[0]['candidate']==3


def test_planner_does_not_cap_long_hold_durations():
    class LongHoldModel:
        layers=1; width=1
        bits=((torch.arange(128)[:,None]>>torch.arange(7))&1).bool()
        def __call__(self,audio,heads,holds,numbers,stars,keys,styles,hidden):
            logits=torch.full((len(audio),1,128),-1e4);logits[:,:,15]=0
            return logits,torch.zeros(len(audio),1,1),hidden
        def endings(self,states,heads):
            logits=torch.full((len(states),1,128),-1e4)
            logits.scatter_(2,heads[:,:,None],0)
            return dict(holds=logits,duration=torch.full((len(states),1,8),float(np.log1p(80))),shared=torch.ones(len(states),1))
    request=dict(times=np.array([0.,1000.]),audio=np.zeros((2,640),dtype=np.float32),keys=4,stars=3,
                 duration_ms=100000,ln_probabilities=np.ones(2,dtype=np.float32),ln_target=1.)
    charts,_=decode_batch(LongHoldModel(),[request],torch.device('cpu'))
    assert len(charts[0])==4
    assert all(n[3]=='hold' and n[1]-n[0]>79000 for n in charts[0])
