import io
import json
from pathlib import Path
import subprocess
import sys
import time
import wave

import pytest
from werkzeug.datastructures import FileStorage

from server import create_app
from studio.youtube import AudioImports, youtube_url
from studio import youtube_worker


@pytest.mark.parametrize('url',[
    'https://www.youtube.com/watch?v=BaW_jenozKc&list=ignored&t=20',
    'https://youtu.be/BaW_jenozKc?si=tracking',
    'music.youtube.com/watch?v=BaW_jenozKc',
    'https://m.youtube.com/shorts/BaW_jenozKc',
    'https://www.youtube.com/embed/BaW_jenozKc',
])
def test_single_video_normalization(url):
    assert youtube_url(url)=='https://www.youtube.com/watch?v=BaW_jenozKc'


@pytest.mark.parametrize('url',[
    None, [], '', 'file:///C:/secret', 'http://127.0.0.1/audio',
    'https://youtube.com.evil.example/watch?v=BaW_jenozKc',
    'https://youtube.com@evil.example/watch?v=BaW_jenozKc',
    'https://youtube.com:8080/watch?v=BaW_jenozKc',
    'https://youtube.com/playlist?list=anything', 'https://youtube.com/@channel',
    'https://youtu.be/invalid', 'https://youtu.be/BaW_jenozKc/extra',
])
def test_reject_non_video_url(url):
    with pytest.raises(ValueError):youtube_url(url)


def test_import_api_lifecycle(tmp_path):
    app=create_app(tmp_path,run_worker=False);client=app.test_client()
    assert client.post('/api/audio-imports',json={'url':'https://example.com'}).status_code==400
    assert client.post('/api/audio-imports',json=[]).status_code==400
    assert client.get('/api/audio-imports/current').json=={'item':None}
    item=client.post('/api/audio-imports',json={'url':'https://youtu.be/BaW_jenozKc'}).json
    assert client.get('/api/audio-imports/current').json['item']['id']==item['id']
    assert client.post('/api/audio-imports',json={'url':item['url']}).status_code==400
    assert client.post('/api/audio-imports/'+item['id']+'/cancel').json['status']=='cancelled'
    app.extensions['studio_imports'].run(item['id']) # late worker must not revive cancellation
    assert client.get('/api/audio-imports/'+item['id']).json['status']=='cancelled'
    second=client.post('/api/audio-imports',json={'url':item['url']}).json
    restarted=create_app(tmp_path,run_worker=False).test_client()
    assert restarted.get('/api/audio-imports/'+second['id']).json['status']=='failed'
    assert restarted.get('/api/audio-imports/current').json['item'] is None
    assert client.post('/api/audio-imports',json={'url':item['url']},headers={'Origin':'https://evil.example'}).status_code==403


def test_download_conversion_registers_existing_asset(tmp_path,monkeypatch):
    """Use real FFmpeg MP3 conversion; mock only the external YouTube network."""
    import yt_dlp
    wav=tmp_path/'fixture.wav'
    with wave.open(str(wav),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(22050);f.writeframes(b'\0\0'*44100)
    folder=tmp_path/'download';folder.mkdir()
    class YDL:
        def __init__(self, options):
            self.options=options
            if 'format' not in options:return
            assert options['noplaylist'] and options['format']=='bestaudio'
            assert 'cookiesfrombrowser' not in options
            assert Path(options['js_runtimes']['node']['path']).is_file()
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def extract_info(self,url,download):
            assert url=='https://www.youtube.com/watch?v=BaW_jenozKc' and download
            hook=self.options['progress_hooks'][0]
            hook(dict(status='downloading',downloaded_bytes=5,total_bytes=10))
            subprocess.run([str(youtube_worker.APP/'bin/ffmpeg.exe'),'-y','-v','error','-i',str(wav),'-codec:a','libmp3lame',str(folder/'audio.mp3')],check=True)
            hook(dict(status='finished'))
            return dict(title='音樂\n測試',artist='作曲者',duration=2)
    monkeypatch.setattr(yt_dlp,'YoutubeDL',YDL)
    result=youtube_worker.download('https://youtu.be/BaW_jenozKc',folder,tmp_path/'workspace')
    assert result['background'] is None and result['warning']
    record=result['asset']
    assert record['title']=='音樂 測試' and record['artist']=='作曲者'
    assert record['duration_s']==pytest.approx(2,abs=.1)
    assert record['source_url']=='https://www.youtube.com/watch?v=BaW_jenozKc'
    client=create_app(tmp_path/'workspace',run_worker=False).test_client()
    assert client.get(record['url']).status_code==200
    assert client.post('/api/jobs',json=dict(audio_id=record['id'],keys=4,stars=2,metadata={})).status_code==202


def test_size_and_live_limits(tmp_path,monkeypatch):
    import yt_dlp
    class YDL:
        def __init__(self,options):self.options=options
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def extract_info(self,*args,**kwargs):
            with pytest.raises(ValueError,match='直播'):
                self.options['match_filter']({'is_live':True},incomplete=False)
            self.options['progress_hooks'][0](dict(status='downloading',downloaded_bytes=youtube_worker.LIMIT+1))
    monkeypatch.setattr(yt_dlp,'YoutubeDL',YDL)
    with pytest.raises(ValueError,match='200 MB'):
        youtube_worker.download('https://youtu.be/BaW_jenozKc',tmp_path,tmp_path/'workspace')


def test_import_cancels_owned_process(tmp_path):
    manager=AudioImports(youtube_worker.APP,tmp_path,run_worker=False)
    item=manager.submit('https://youtu.be/BaW_jenozKc')
    process=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
    try:
        manager.processes[item['id']]=process
        assert manager.cancel(item['id'])['status']=='cancelled'
        assert process.wait(timeout=5) is not None
    finally:
        if process.poll() is None:process.kill()


def test_cover_import_and_fallback(tmp_path):
    from PIL import Image
    from studio.assets import AssetStore
    image=io.BytesIO();Image.new('RGB',(320,180),(80,60,100)).save(image,format='WEBP')
    class Downloader:
        def urlopen(self,url):
            if 'bad' in url:raise OSError('cover unavailable')
            return io.BytesIO(image.getvalue())
    store=AssetStore(tmp_path/'uploads')
    source='https://www.youtube.com/watch?v=BaW_jenozKc'
    background,warning=youtube_worker.download_background(dict(thumbnail='https://i.ytimg.com/bad.webp',thumbnails=[{'url':'https://i.ytimg.com/good.webp'}]),Downloader(),store,source)
    assert warning is None and background['width']==320 and background['height']==180
    assert background['source_url']==source and background['file']=='background.png'
    assert Image.open(store.get(background['id'])[1]).size==(320,180)
    background,warning=youtube_worker.download_background(dict(thumbnail='https://i.ytimg.com/bad.webp'),Downloader(),store,source)
    assert background is None and warning


def test_cover_chooses_largest_actual_image_not_default_or_claimed_size(tmp_path):
    from PIL import Image
    from studio.assets import AssetStore
    images={}
    for name,size in [('default',(480,360)),('large',(1920,1080)),('misreported',(120,90))]:
        image=io.BytesIO();Image.new('RGB',size,(80,60,100)).save(image,format='JPEG');images[name]=image.getvalue()
    class Downloader:
        def urlopen(self,url):return io.BytesIO(images[url.rsplit('/',1)[-1]])
    info=dict(thumbnail='https://i.ytimg.com/default',thumbnails=[
        dict(url='https://i.ytimg.com/large',width=1920,height=1080),
        dict(url='https://i.ytimg.com/misreported',width=3840,height=2160)])
    cover,warning=youtube_worker.download_background(info,Downloader(),AssetStore(tmp_path/'uploads'),'https://youtu.be/BaW_jenozKc')
    assert warning is None and (cover['width'],cover['height'])==(1920,1080)
    assert cover['thumbnail_url'].endswith('/large')


def test_cover_maxres_probe_and_missing_maxres_fallback(tmp_path):
    from PIL import Image
    from studio.assets import AssetStore
    class Downloader:
        def __init__(self,available):self.available=available
        def urlopen(self,url):
            maximum='maxresdefault' in url
            if maximum and not self.available:raise OSError('not found')
            image=io.BytesIO();Image.new('RGB',(1280,720) if maximum else (480,360)).save(image,format='JPEG');image.seek(0);return image
    info=dict(id='BaW_jenozKc',thumbnail='https://i.ytimg.com/default.jpg')
    for available in (True,False):
        cover,warning=youtube_worker.download_background(info,Downloader(available),AssetStore(tmp_path/str(available)),'https://youtu.be/BaW_jenozKc')
        assert warning is None and cover['width']==(1280 if available else 480)
