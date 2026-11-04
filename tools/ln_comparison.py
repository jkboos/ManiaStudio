"""Summarize the actual old/new playtest without modifying either chart."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
def summarize(path):
    notes=[]
    for line in path.read_text(encoding='utf-8').split('[HitObjects]')[1].splitlines():
        if line.strip():
            values=line.split(',');notes.append((int(values[2]),bool(int(values[3])&128)))
    result=[]
    for start,end in [(0,121000),(121000,244000)]:
        selected=[n for n in notes if start<=n[0]<end]
        result.append(dict(start_s=start/1000,end_s=end/1000,notes=len(selected),
                           ln_fraction=sum(n[1] for n in selected)/len(selected)))
    return result
old=ROOT/'workspace/jobs/3fa3b10319ea461592c5c83903b185af'
review=json.loads((ROOT/'workspace/qa/ln_plan_review_job.json').read_text(encoding='utf-8'))
new=ROOT/'workspace/jobs'/review['id']
result=dict(before=summarize(old/'export/beatmap.osu'),after=summarize(new/'export/beatmap.osu'),
            before_stars=json.loads((old/'export/result.json').read_text(encoding='utf-8'))['actual_stars'],
            after_stars=json.loads((new/'export/result.json').read_text(encoding='utf-8'))['actual_stars'])
(ROOT/'workspace/qa/ln_plan_comparison.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
