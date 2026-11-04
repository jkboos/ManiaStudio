"""Exercise uploads, queued real generation and downloads through the Flask API."""
from pathlib import Path
import io
import json
import sys
import time
import zipfile
from PIL import Image

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from server import create_app


def main():
    workspace = APP/'workspace/qa/control_migration/api_check'
    app = create_app(workspace)
    client = app.test_client()
    results = []
    image = io.BytesIO()
    Image.new('RGB', (32, 32), '#233344').save(image, format='PNG')
    image.seek(0)
    response = client.post('/api/uploads', data={'kind':'background', 'file':(image, 'qa.png')})
    assert response.status_code == 201, response.json
    background_id = response.json['id']
    try:
        for keys, stars, pattern, techniques, reduce_jacks in [
                (4, 6., '*Jack-in-the-VOX.mp3', ['LN','tech','stream'], True),
                (7, 4., 'Aiobahn*.mp3', ['tech','stream'], False)]:
            audio = next(APP.parent.glob(pattern))
            with audio.open('rb') as f:
                response = client.post('/api/uploads', data={'kind':'audio','file':(f,audio.name)})
            assert response.status_code == 201, response.json
            request = dict(audio_id=response.json['id'], background_id=background_id if keys==4 else None,
                           keys=keys, stars=stars, techniques=techniques, reduce_jacks=reduce_jacks,
                           metadata=dict(title='Control integration QA', artist='Test', creator='QA', version=f'{keys}K Control'))
            response = client.post('/api/jobs', json=request)
            assert response.status_code == 202, response.json
            id_ = response.json['id']
            print(json.dumps(dict(stage='submitted', keys=keys, id=id_)), flush=True)
            deadline = time.monotonic()+900
            while time.monotonic() < deadline:
                job = client.get('/api/jobs/'+id_).json
                if job['status'] in ('completed','failed','cancelled'):
                    break
                time.sleep(1)
            assert job['status']=='completed', job
            result = job['result']
            assert result['backend_version']=='studio-control-1' and result['validated']
            assert abs(result['actual_stars']-stars)<=.5
            assert result['metadata']['creator']=='QA'
            assert bool(result['background_file']) == (keys==4)
            assert result['local_repair'] is None and result['ln_plan'] is None
            report = json.loads((workspace/'jobs'/id_/'generated/generation_report.json').read_text(encoding='utf-8'))
            expected = {t:'high' for t in techniques}
            if 'jack' not in techniques: expected['jack']='low'
            assert report['technique_profile']['requested']==expected
            assert report['pattern_checkpoint_sha256']==json.loads((APP/'control_backend.json').read_text())['checkpoint_sha256']
            for kind in ('osu','osz','report'):
                download = client.get(f'/api/jobs/{id_}/download/{kind}')
                assert download.status_code == 200
                if kind=='osz':
                    with zipfile.ZipFile(io.BytesIO(download.data)) as archive:
                        assert archive.testzip() is None
                        assert len(archive.namelist()) == (3 if keys==4 else 2)
            results.append(dict(id=id_, keys=keys, actual_stars=result['actual_stars'], taps=result['taps'], holds=result['holds'],
                                metadata_background_downloads_verified=True, technique_condition_verified=True))
            print(json.dumps(results[-1]), flush=True)
    finally:
        app.extensions['studio_jobs'].close()
        app.extensions['studio_imports'].close()
    (workspace.parent/'api_validation.json').write_text(json.dumps(results,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
