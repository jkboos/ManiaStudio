"""Per-column repeat and LN recovery diagnostics, independent of chord masks.

These are preferences for low-jack generation, not a human difficulty rating.
"""
import numpy as np


def lane_costs(current, last_heads, active_until, runs, gap_ms=200.):
    gaps=current[:,None]-last_heads
    repeating=(last_heads>=0)&(gaps>=0)&(gaps<=gap_ms)
    # A double is allowed without a streak penalty. The third and subsequent
    # uses of that finger become progressively less likely, never forbidden.
    streak=np.where(repeating,np.minimum(4,np.maximum(0,runs-1)),0).astype(np.float32)
    recovery=current[:,None]-active_until
    release=np.where((active_until>0)&(recovery>=0)&(recovery<100),2*(1-recovery/100),0)
    return (streak+release).astype(np.float32)


def finger_summary(notes,keys,gap_ms=200.):
    repeated=[];release=[];longest=1;worst=None
    for lane in range(keys):
        column=sorted((n for n in notes if n[2]==lane),key=lambda n:n[0])
        run=1;run_start=column[0][0] if column else 0
        for previous,current in zip(column,column[1:]):
            gap=current[0]-previous[0]
            if gap<=gap_ms:
                run+=1
            else:
                run=1;run_start=current[0]
            if run>=3:repeated.append(current[0])
            if run>longest:
                longest=run;worst=dict(lane=lane,start_ms=run_start,end_ms=current[0],heads=run)
            if previous[3]=='hold' and 0<=current[0]-previous[1]<80:
                release.append(current[0])
    head_times=np.sort([n[0] for n in notes])
    flagged=np.sort(repeated)
    local=[]
    if len(head_times):
        for start in np.arange(head_times[0],head_times[-1]+1,500):
            count=np.searchsorted(head_times,start+2000)-np.searchsorted(head_times,start)
            if count<8:continue
            burden=np.searchsorted(flagged,start+2000)-np.searchsorted(flagged,start)
            local.append(burden/count)
    return dict(gap_ms=gap_ms,heads_in_runs_ge3=len(repeated),
                run_head_fraction=len(repeated)/max(1,len(notes)),longest_chain=longest,worst_chain=worst,
                local_2s_p95=float(np.percentile(local,95)) if local else 0.,
                local_2s_max=max(local,default=0.),ln_release_repress_under80ms=len(release),
                release_repress_fraction=len(release)/max(1,sum(n[3]=='hold' for n in notes)))
