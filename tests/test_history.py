import io
import threading
import time
import wave
from server import create_app


def upload(client):
    stream=io.BytesIO()
    with wave.open(stream,'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(22050);wav.writeframes(b'\0\0'*22050)
    stream.seek(0)
    return client.post('/api/uploads',data={'kind':'audio','file':(stream,'song.wav')}).json


def test_clear_files_and_records_preserves_external_files(tmp_path):
    root=tmp_path/'workspace';app=create_app(root,run_worker=False);client=app.test_client()
    asset=upload(client)
    job=client.post('/api/jobs',json=dict(audio_id=asset['id'],keys=4,stars=2,metadata={})).json
    assert client.get('/api/history/cleanup').json['can_clear'] is False
    assert client.delete('/api/history').status_code==409
    assert client.get(asset['url']).status_code==200
    client.post('/api/jobs/'+job['id']+'/cancel')
    exported=root/'jobs'/job['id']/'export';exported.mkdir();(exported/'beatmap.osz').write_bytes(b'generated fixture')
    imported=client.post('/api/audio-imports',json={'url':'https://youtu.be/BaW_jenozKc'}).json
    assert client.delete('/api/history').status_code==409
    client.post('/api/audio-imports/'+imported['id']+'/cancel')
    (root/'imports'/imported['id']/'audio.mp3').write_bytes(b'downloaded fixture')
    external=tmp_path/'saved.osz';external.write_bytes(b'user export')
    (root/'server.pid').write_text('123')
    summary=client.get('/api/history/cleanup').json
    assert summary['jobs']==1 and summary['imports']==1 and summary['assets']==1 and summary['bytes']>0
    assert client.delete('/api/history',headers={'Origin':'https://evil.example'}).status_code==403
    result=client.delete('/api/history').json
    assert result['cleared'] and result['freed_bytes']==summary['bytes']
    assert client.get('/api/jobs').json=={'jobs':[]}
    assert client.get('/api/uploads/'+asset['id']).status_code==400
    assert client.get('/api/audio-imports/'+imported['id']).status_code==404
    for name in ('uploads','imports','jobs'):assert list((root/name).iterdir())==[]
    assert external.read_bytes()==b'user export' and (root/'server.pid').is_file()
    assert client.get('/api/history/cleanup').json['bytes']==0
    assert client.delete('/api/history').json['cleared']
    # Cancelled queue entries removed by cleanup must not kill the worker.
    jobs=app.extensions['studio_jobs']
    thread=threading.Thread(target=jobs.worker,daemon=True);thread.start()
    jobs.pending.join();assert thread.is_alive();jobs.close();thread.join(timeout=2)
    fresh=upload(client)
    assert client.post('/api/jobs',json=dict(audio_id=fresh['id'],keys=7,stars=3,metadata={})).status_code==202


def test_cleanup_waits_for_cancelled_worker_to_exit(tmp_path):
    app=create_app(tmp_path,run_worker=False);client=app.test_client()
    jobs=app.extensions['studio_jobs'];jobs.inflight.add('finishing')
    assert client.delete('/api/history').status_code==409
    jobs.inflight.clear()
    imports=app.extensions['studio_imports'];imports.inflight.add('finishing')
    assert client.delete('/api/history').status_code==409
    imports.inflight.clear()
    assert client.delete('/api/history').status_code==200
