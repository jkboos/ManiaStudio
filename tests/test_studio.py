import io
from pathlib import Path
import sys
import wave

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import create_app
from studio.domain import validate_request, profile_string
from studio.exporting import metadata_text


@pytest.fixture
def client(tmp_path):
    return create_app(tmp_path, run_worker=False).test_client()


def request_data():
    return dict(audio_id='a'*32, keys=4, stars=4, techniques=['LN','tech','stream'], reduce_jacks=True,
                metadata=dict(title='中文歌曲',artist='演出者',title_romanized='Song',artist_romanized='Artist',
                              creator='Tester',version='Test',source='',tags=''))


def audio_bytes():
    output=io.BytesIO()
    with wave.open(output,'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(22050);wav.writeframes(b'\0\0'*22050)
    output.seek(0)
    return output


def test_optional_metadata_and_controls():
    data=request_data();data['metadata']={};data['techniques']=[]
    result=validate_request(data)
    assert result['metadata']['creator']=='ManiaModel'
    assert result['metadata']['source']==''
    assert result['metadata']['version']=='4K - 4.0 stars'
    assert profile_string(result)=='jack=low'
    data['reduce_jacks']=False
    assert profile_string(validate_request(data))=='jack=low'


@pytest.mark.parametrize('key,value',[('keys',5),('stars',float('nan')),('stars',True),('stars',16),('techniques',['unknown']),('audio_id','../escape')])
def test_rejected_settings(key,value):
    data=request_data();data[key]=value
    with pytest.raises(ValueError):validate_request(data)


def test_metadata_injection_rejected():
    data=request_data();data['metadata']['title']='hi\n[HitObjects]'
    with pytest.raises(ValueError):validate_request(data)
    data=request_data();data['techniques']=['jack']
    assert profile_string(validate_request(data))=='jack=high'


@pytest.mark.parametrize('legacy_toggle',[True,False,None,'false'])
@pytest.mark.parametrize('techniques',[[],['tech','LN'],['jack'],['tech','jack']])
def test_jack_preference_comes_only_from_chip(legacy_toggle,techniques):
    data=request_data();data.update(techniques=techniques,reduce_jacks=legacy_toggle)
    result=validate_request(data)
    expected='jack=high' if 'jack' in techniques else 'jack=low'
    assert result['reduce_jacks']==('jack' not in techniques)
    assert [term for term in profile_string(result).split(',') if term.startswith('jack=')]==[expected]
    # Already queued requests from older versions follow the same rule.
    assert [term for term in profile_string(data).split(',') if term.startswith('jack=')]==[expected]


def test_metadata_background_preserves_notes():
    original='osu file format v14\n[Metadata]\nTitle:Old\n\n[Difficulty]\nCircleSize:4\n[Events]\n\n[TimingPoints]\n0,500,4,2,1,100,1,0\n[HitObjects]\n64,192,1000,1,0,0:0:0:0:\n'
    output=metadata_text(original,request_data()['metadata'],'background.png')
    assert 'Title:Song\nTitleUnicode:中文歌曲' in output
    assert 'Artist:Artist\nArtistUnicode:演出者' in output
    assert '0,0,"background.png",0,0' in output
    assert output.split('[HitObjects]')[1]==original.split('[HitObjects]')[1]


def test_upload_queue_cancel_and_isolation(client):
    response=client.post('/api/uploads',data={'kind':'audio','file':(audio_bytes(),'song.wav')})
    assert response.status_code==201
    asset=response.json
    assert asset['duration_s']==1
    assert client.get(asset['url'],headers={'Range':'bytes=0-20'}).status_code==206
    data=request_data();data['audio_id']=asset['id']
    job=client.post('/api/jobs',json=data)
    assert job.status_code==202
    job_id=job.json['id']
    assert client.get(f'/api/jobs/{job_id}/download/osz').status_code==400
    assert client.post(f'/api/jobs/{job_id}/cancel').json['status']=='cancelled'
    assert client.get('/api/jobs').json['jobs'][0]['status']=='cancelled'
    assert client.get('/api/health',headers={'Host':'evil.example'}).status_code==403
    assert client.post('/api/jobs',json=data,headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/assets/../server.py').status_code==404


def test_images_and_invalid_files(client):
    image=io.BytesIO();Image.new('RGB',(64,32),(120,60,90)).save(image,format='WEBP');image.seek(0)
    response=client.post('/api/uploads',data={'kind':'background','file':(image,'cover.webp')})
    assert response.status_code==201
    assert response.json['file']=='background.png'
    assert Image.open(io.BytesIO(client.get(response.json['url']).data)).size==(64,32)
    for name,kind in [('fake.png','background'),('fake.mp3','audio'),('evil.svg','background')]:
        assert client.post('/api/uploads',data={'kind':kind,'file':(io.BytesIO(b'not a real file'),name)}).status_code==400


def test_restart_marks_interrupted_job(client):
    asset=client.post('/api/uploads',data={'kind':'audio','file':(audio_bytes(),'song.wav')}).json
    data=request_data();data['audio_id']=asset['id']
    job=client.post('/api/jobs',json=data).json
    root=client.application.extensions['studio_jobs'].root.parent
    restarted=create_app(root,run_worker=False).test_client()
    assert restarted.get('/api/jobs/'+job['id']).json['status']=='failed'
