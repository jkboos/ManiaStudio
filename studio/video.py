"""Validate and register silent background movies produced by our import worker."""
import json
import math
from pathlib import Path
import shutil
import subprocess
import uuid
import tempfile
from .domain import write_json

VIDEO_LIMIT = 2*1024*1024*1024


def convert_silent(source, output, app):
    info = probe(source, app)
    video = next((s for s in info.get('streams',[]) if s['codec_type']=='video' and not s.get('disposition',{}).get('attached_pic')), None)
    if not video:
        raise ValueError('檔案不含可播放的影片軌。')
    compatible = video['codec_name']=='h264' and video.get('pix_fmt')=='yuv420p'
    codec = ['-c:v','copy'] if compatible else ['-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-threads','2']
    subprocess.run([str(app/'bin/ffmpeg.exe'),'-nostdin','-y','-v','error','-i',str(source),
                    '-map',f'0:{video["index"]}','-an','-sn','-dn',*codec,'-movflags','+faststart',str(output)],
                   check=True, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return dict(source_width=video['width'], source_height=video['height'], stream_copied=compatible)


def upload_video(storage, assets, app, audio_id):
    audio, _ = assets.get(audio_id, 'audio')
    original = storage.filename or ''
    suffix = Path(original).suffix.lower()
    if suffix not in ('.mp4','.mkv','.webm','.avi','.mov'):
        raise ValueError('影片支援 MP4、MKV、WebM、AVI、MOV。')
    with tempfile.TemporaryDirectory(prefix='video_',dir=assets.root) as temp:
        folder=Path(temp).resolve()
        if not folder.is_relative_to(assets.root.resolve()):
            raise ValueError('Invalid video temporary directory')
        source=folder/('source'+suffix);size=0
        with source.open('wb') as out:
            for chunk in iter(lambda:storage.stream.read(1024*1024),b''):
                size+=len(chunk)
                if size>VIDEO_LIMIT:raise ValueError('背景影片上限為 2 GB。')
                out.write(chunk)
        if not size:raise ValueError('影片檔案是空的。')
        output=folder/'video.mp4'
        try:
            conversion=convert_silent(source,output,app)
            record=register_video(output,assets,app,audio,None)
        except (subprocess.CalledProcessError, KeyError, TypeError):
            raise ValueError('無法讀取或轉換影片，請確認檔案有效。') from None
        record.update(conversion,original_name=original,origin='upload')
        write_json(assets.root/record['id']/'asset.json',record)
        return record


def probe(path, app):
    run = subprocess.run([str(app/'bin/ffprobe.exe'), '-v', 'error', '-show_streams',
                          '-show_format', '-of', 'json', str(path)],
                         capture_output=True, text=True, encoding='utf-8', check=True,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return json.loads(run.stdout)


def register_video(path, assets, app, audio, source_url):
    info = probe(path, app)
    streams = info.get('streams', [])
    videos = [s for s in streams if s['codec_type']=='video']
    duration = float(info['format']['duration'])
    if len(videos)!=1 or any(s['codec_type']=='audio' for s in streams):
        raise ValueError('背景影片必須只有一個視訊軌且沒有音軌。')
    if videos[0]['codec_name']!='h264' or not math.isfinite(duration) or duration<1:
        raise ValueError('無法讀取相容的背景影片。')
    if not 0 < path.stat().st_size <= VIDEO_LIMIT:
        raise ValueError('背景影片檔案為空或超過 2 GB。')
    asset_id = uuid.uuid4().hex
    folder = assets.root/asset_id
    folder.mkdir()
    shutil.copy2(path, folder/'video.mp4')
    record = dict(id=asset_id, kind='video', original_name=audio['title']+'.mp4', file='video.mp4',
                  bytes=path.stat().st_size, duration_s=duration, width=videos[0]['width'], height=videos[0]['height'],
                  codec='h264', silent=True, source_url=source_url, audio_id=audio['id'],
                  url=f'/api/uploads/{asset_id}/file')
    write_json(folder/'asset.json', record)
    return record
