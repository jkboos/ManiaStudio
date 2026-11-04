"""Regenerate an existing request into a new review entry while Studio is off."""
from pathlib import Path
import json
import sys
APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from server import create_app

def main():
    source=APP/'workspace/jobs'/sys.argv[1]/'job.json'
    original=json.loads(source.read_text(encoding='utf-8'))
    app=create_app(run_worker=False)
    jobs=app.extensions['studio_jobs']
    job=jobs.submit(original['request'])
    marker=APP/'workspace/qa/ln_plan_review_job.json'
    marker.write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(id=job['id'],status='running')),flush=True)
    jobs.run(job['id'])
    result=jobs.get(job['id'])
    marker.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    if result['status']!='completed':
        raise RuntimeError(result.get('error_details',result.get('error')))
    print(json.dumps(dict(id=result['id'],actual_stars=result['result']['actual_stars'],
                         ln_fraction=result['result']['ln_fraction'],backend=result['result']['backend_version'])),flush=True)

if __name__=='__main__':main()
