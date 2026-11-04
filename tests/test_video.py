import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import wave
import zipfile
import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP/'runtime'))
from server import create_app
from studio.assets import AssetStore
from studio.domain import validate_request, write_json
from studio.exporting import package_result
from studio import youtube_worker
from studio.video import probe, register_video
from audio_features import sha256_file
from osu_export import serialize_osu, calculated_stars

URL = 'https://www.youtube.com/watch?v=BaW_jenozKc'


def test_real_ytdlp_selector_prefers_compatible_mp4_with_caps():
    import yt_dlp
    def fmt(id_,ext,codec,height,fps=30,audio='none'):
        return dict(format_id=id_,ext=ext,vcodec=codec,acodec=audio,height=height,width=height*16//9,
                    fps=fps,url='https://example.invalid/'+id_)
    avc720=fmt('avc720','mp4','avc1.640028',720)
    avc1080=fmt('avc1080','mp4','avc1.64002a',1080,30)
    av1=fmt('av1','mp4','av01.0.08M.08',720,30)
    vp9=fmt('vp9','webm','vp9',720,30)
    oversize=fmt('avc1440','mp4','avc1.640033',1440,60)
    fast=fmt('avc60fps','mp4','avc1.640033',720,60)
    muxed=fmt('muxed','mp4','avc1.64002a',720,30,'mp4a.40.2')
    with yt_dlp.YoutubeDL(dict(quiet=True)) as ydl:
        selector=ydl.build_format_selector(youtube_worker.VIDEO_FORMAT)
        choose=lambda formats:[f['format_id'] for f in ydl._select_formats(formats,selector)]
        assert choose([avc720,avc1080,vp9,av1,oversize,fast,muxed])==['avc720']
        assert choose([avc720,av1,vp9])==['avc720']
        assert choose([av1,vp9])==['av1']
        assert choose([vp9,oversize,fast,muxed])==['vp9']
        assert choose([avc1080,oversize,fast,muxed])==[]


@pytest.fixture(scope='module')
def media(tmp_path_factory):
    root = tmp_path_factory.mktemp('video_media')
    video = root/'silent.mp4'
    subprocess.run([str(APP/'bin/ffmpeg.exe'),'-nostdin','-y','-v','error','-f','lavfi','-i',
                    'testsrc2=size=1920x1080:rate=12','-t','2','-an','-c:v','libx264','-preset','ultrafast',
                    '-pix_fmt','yuv420p','-threads','2',str(video)],check=True)
    wav = root/'audio.wav'
    with wave.open(str(wav),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(22050);f.writeframes(b'\0\0'*44100)
    mp3 = root/'audio.mp3'
    subprocess.run([str(APP/'bin/ffmpeg.exe'),'-nostdin','-y','-v','error','-i',str(wav),str(mp3)],check=True)
    return video, mp3


def fake_network(monkeypatch, media, folder):
    import yt_dlp
    formats = []
    class YDL:
        def __init__(self, options):self.options=options
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def extract_info(self,url,download):
            assert url==URL and download
            fmt=self.options['format'];formats.append(fmt)
            assert self.options['noplaylist'] and 'cookiesfrombrowser' not in self.options
            if fmt==youtube_worker.VIDEO_FORMAT:
                assert 'height<=720' in fmt and 'fps<=30' in fmt and '+' not in fmt
                shutil.copy2(media[0],folder/'video_source.mp4')
            else:
                assert fmt=='bestaudio';shutil.copy2(media[1],folder/'audio.mp3')
            return dict(id='BaW_jenozKc',title='Video fixture',artist='Artist',ext='mp4',thumbnail='https://i.ytimg.com/test.jpg')
        def prepare_filename(self,info):return str(folder/'video_source.mp4')
        def urlopen(self,url):
            stream=io.BytesIO();Image.new('RGB',(160,90),'blue').save(stream,format='JPEG');stream.seek(0);return stream
    monkeypatch.setattr(yt_dlp,'YoutubeDL',YDL)
    return formats


@pytest.mark.parametrize('include_video',[False,True])
def test_download_modes_keep_cover_and_video_is_silent(tmp_path,monkeypatch,media,include_video):
    folder=tmp_path/'download';folder.mkdir()
    formats=fake_network(monkeypatch,media,folder)
    result=youtube_worker.download(URL,folder,tmp_path/'workspace',include_video)
    assert result['asset'] and result['background']
    assert formats==(['bestaudio',youtube_worker.VIDEO_FORMAT] if include_video else ['bestaudio'])
    if include_video:
        v=result['video'];assert v['width']==1920 and v['height']==1080 and v['stream_copied']
        assert v['audio_id']==result['asset']['id'] and v['silent']
        path=AssetStore(tmp_path/'workspace/uploads').get(v['id'],'video')[1]
        assert {s['codec_type'] for s in probe(path,APP)['streams']}=={'video'}
    else:assert result['video'] is None


def test_cover_failure_uses_video_frame(tmp_path,monkeypatch,media):
    folder=tmp_path/'download';folder.mkdir();fake_network(monkeypatch,media,folder)
    monkeypatch.setattr(youtube_worker,'download_background',lambda *args:(None,'failed'))
    result=youtube_worker.download(URL,folder,tmp_path/'workspace',True)
    assert result['background']['width']==1920 and result['video']
    assert result['warning']


def setup_assets(tmp_path,media):
    app=create_app(tmp_path,run_worker=False);store=app.extensions['studio_assets']
    with media[1].open('rb') as f:audio=store.upload(FileStorage(f,filename='audio.mp3'),'audio')
    audio['source_url']=URL;write_json(store.root/audio['id']/'asset.json',audio)
    image=io.BytesIO();Image.new('RGB',(160,90),'blue').save(image,format='PNG');image.seek(0)
    background=store.upload(FileStorage(image,filename='cover.png'),'background')
    video=register_video(media[0],store,APP,audio,URL)
    return app,store,audio,background,video


def test_api_pairs_video_with_audio_and_cleanup(tmp_path,media):
    app,store,audio,background,video=setup_assets(tmp_path,media);client=app.test_client()
    payload=dict(audio_id=audio['id'],background_id=background['id'],video_id=video['id'],keys=4,stars=2)
    assert client.post('/api/audio-imports',json=dict(url=URL,include_video='yes')).status_code==400
    imported=client.post('/api/audio-imports',json=dict(url=URL,include_video=True)).json
    assert imported['include_video'] is True
    assert client.delete('/api/history').status_code==409
    client.post('/api/audio-imports/'+imported['id']+'/cancel')
    assert client.post('/api/jobs',json=dict(payload,background_id=None)).status_code==400
    video_path=store.get(video['id'])[1]
    job=client.post('/api/jobs',json=payload);assert job.status_code==202
    request=json.loads((tmp_path/'jobs'/job.json['id']/'request.json').read_text())
    assert request['video_path']==str(video_path)
    assert client.get(video['url'],headers={'Range':'bytes=0-20'}).status_code==206
    video['audio_id']='f'*32;write_json(store.root/video['id']/'asset.json',video)
    assert client.post('/api/jobs',json=payload).status_code==400
    client.post('/api/jobs/'+job.json['id']+'/cancel')
    assert client.delete('/api/history').status_code==200
    assert not video_path.exists()


def test_osz_video_and_image_coexist_notes_unchanged(tmp_path,media):
    app,store,audio,bg,video=setup_assets(tmp_path/'workspace',media)
    source=tmp_path/'generated';source.mkdir();shutil.copy2(media[1],source/'audio.mp3')
    notes=[[100,100,0,'tap'],[500,900,1,'hold'],[1200,1200,2,'tap']]
    timing=dict(bpm=120,offset_ms=0)
    text=serialize_osu(notes,4,'audio.mp3','Video fixture',2,timing)
    (source/'generated.osu').write_text(text,encoding='utf-8')
    write_json(source/'generation_report.json',dict(osu_file='generated.osu',actual_stars=calculated_stars(text),
        audio_sha256=sha256_file(source/'audio.mp3'),audio_duration_s=audio['duration_s'],note_count=2,ln_count=1,
        timing=timing,candidates=[dict(candidate=0)],selected_candidate=0))
    request=validate_request(dict(audio_id=audio['id'],keys=4,stars=2))
    for enabled in (False,True):
        dest=tmp_path/str(enabled)
        result=package_result(source,dest,request,store.get(bg['id'])[1],dict(version='test'),store.get(video['id'])[1] if enabled else None)
        with zipfile.ZipFile(dest/'beatmap.osz') as archive:
            assert 'background.png' in archive.namelist()
            assert ('video.mp4' in archive.namelist())==enabled
            exported=archive.read('beatmap.osu').decode('utf-8')
            assert ('Video,0,"video.mp4",0,0' in exported)==enabled
            assert '0,0,"background.png",0,0' in exported
            assert exported.split('[HitObjects]')[1].splitlines()==text.split('[HitObjects]')[1].splitlines()
        assert bool(result['video_file'])==enabled


def test_non_h264_transcodes_without_resizing(tmp_path,monkeypatch,media):
    source=tmp_path/'vp9.webm'
    subprocess.run([str(APP/'bin/ffmpeg.exe'),'-nostdin','-y','-v','error','-f','lavfi','-i',
                    'testsrc2=size=320x180:rate=12','-t','2','-an','-c:v','libvpx-vp9',
                    '-deadline','realtime','-threads','2',str(source)],check=True)
    folder=tmp_path/'download';folder.mkdir()
    fake_network(monkeypatch,(source,media[1]),folder)
    result=youtube_worker.download(URL,folder,tmp_path/'workspace',True)
    video=result['video']
    assert not video['stream_copied']
    assert (video['width'],video['height'])==(320,180)
    assert video['silent'] and video['codec']=='h264'


def test_manual_upload_strips_audio_and_keeps_resolution(tmp_path,media):
    app,store,audio,bg,_=setup_assets(tmp_path/'workspace',media)
    client=app.test_client();movie=tmp_path/'with_audio.mp4'
    subprocess.run([str(APP/'bin/ffmpeg.exe'),'-nostdin','-y','-v','error','-i',str(media[0]),
                    '-i',str(media[1]),'-c:v','copy','-c:a','aac','-shortest',str(movie)],check=True)
    assert any(s['codec_type']=='audio' for s in probe(movie,APP)['streams'])
    with movie.open('rb') as f:
        response=client.post('/api/uploads',data=dict(kind='video',audio_id=audio['id'],file=(f,'Local movie.mp4')))
    assert response.status_code==201,response.json
    record=response.json
    assert record['origin']=='upload' and record['original_name']=='Local movie.mp4'
    assert record['width']==1920 and record['height']==1080 and record['stream_copied']
    assert {s['codec_type'] for s in probe(store.get(record['id'])[1],APP)['streams']}=={'video'}
    assert record['audio_id']==audio['id'] and record['source_url'] is None
    assert not list(store.root.glob('video_*'))
    job=client.post('/api/jobs',json=dict(audio_id=audio['id'],video_id=record['id'],background_id=bg['id'],keys=4,stars=2))
    assert job.status_code==202,job.json
    client.post('/api/jobs/'+job.json['id']+'/cancel')


def test_upload_invalid_movie_leaves_previous_assets(tmp_path,media):
    app,store,audio,bg,video=setup_assets(tmp_path/'workspace',media);client=app.test_client()
    assert client.post('/api/uploads',data=dict(kind='video',file=(io.BytesIO(b'bad'),'bad.mp4'))).status_code==400
    assert client.post('/api/uploads',data=dict(kind='video',audio_id=audio['id'],file=(io.BytesIO(b'bad'),'bad.exe'))).status_code==400
    assert client.post('/api/uploads',data=dict(kind='video',audio_id=audio['id'],file=(io.BytesIO(b'bad'),'bad.mp4'))).status_code==400
    assert client.get(video['url']).status_code==200
    assert not list(store.root.glob('video_*'))
