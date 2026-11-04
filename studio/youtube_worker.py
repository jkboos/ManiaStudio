"""Download one YouTube audio track and register it as an ordinary audio asset."""
from pathlib import Path
import io
import re
import sys
import time
import json
import subprocess
from urllib.parse import urlsplit
from PIL import Image

from werkzeug.datastructures import FileStorage
from .assets import AssetStore
from .domain import read_json, write_json
from .youtube import youtube_url
from .video import VIDEO_LIMIT, probe, register_video, convert_silent

APP = Path(__file__).resolve().parents[1]
LIMIT = 200*1024*1024
VIDEO_BOUNDS = '[width<=1280][height<=720][fps<=30]'
VIDEO_FORMAT = ('bestvideo[ext=mp4][vcodec^=avc1]'+VIDEO_BOUNDS
                +'/bestvideo[ext=mp4]'+VIDEO_BOUNDS
                +'/bestvideo'+VIDEO_BOUNDS)


def stage(name, progress=None):
    print(json.dumps(dict(import_stage=name, progress=progress)), flush=True)


def clean(value, limit=250):
    return ' '.join(str(value or '').split())[:limit]


def download_background(info, ydl, assets, source_url):
    """Import a validated video cover; cover failure never discards the audio."""
    thumbnails = sorted(info.get('thumbnails') or [],
                        key=lambda t:(t.get('width') or 0)*(t.get('height') or 0),reverse=True)
    video_id = info.get('id')
    maximum = [f'https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg'] if isinstance(video_id,str) and re.fullmatch(r'[A-Za-z0-9_-]{11}',video_id) else []
    candidates = maximum + [t.get('url') for t in thumbnails] + [info.get('thumbnail')]
    urls = list(dict.fromkeys(url for url in candidates if isinstance(url, str)))[:5]
    if isinstance(info.get('thumbnail'),str) and info['thumbnail'] not in urls:
        urls.append(info['thumbnail']) # Keep the default even with many broken high-res URLs.
    downloaded = []
    for url in urls:
        try:
            parsed = urlsplit(url)
            host = (parsed.hostname or '').lower()
            if parsed.scheme not in ('http', 'https') or not (host == 'ytimg.com' or host.endswith('.ytimg.com')):
                continue
            with ydl.urlopen(url) as response:
                data = response.read(20*1024*1024+1)
            if len(data) > 20*1024*1024:
                continue
            with Image.open(io.BytesIO(data)) as image:
                suffix = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp'}.get(image.format)
                if not suffix or image.width*image.height > 40_000_000:
                    continue
                image.load()
                downloaded.append((image.width*image.height, data, suffix, url))
        except Exception as exc:
            print('Cover unavailable: '+str(exc), flush=True)
    for _, data, suffix, url in sorted(downloaded,key=lambda x:x[0],reverse=True):
        try:
            background = assets.upload(FileStorage(stream=io.BytesIO(data), filename='YouTube cover'+suffix), 'background')
            background.update(source_url=source_url, thumbnail_url=url, selection='largest_decoded_thumbnail')
            write_json(assets.root/background['id']/'asset.json', background)
            return background, None
        except Exception as exc:
            print('Cover unavailable: '+str(exc), flush=True)
    return None, '音訊已下載，但無法取得影片封面；可以自行上傳背景圖。'


def download_video(url, folder, assets, audio):
    import yt_dlp
    last_update = 0.
    def progress(message):
        nonlocal last_update
        downloaded = message.get('downloaded_bytes') or 0
        if downloaded > VIDEO_LIMIT:
            raise ValueError('背景影片超過 2 GB，已停止下載。')
        if message['status']=='downloading' and time.monotonic()-last_update>.4:
            total = message.get('total_bytes') or message.get('total_bytes_estimate')
            stage('video_downloading', min(100, downloaded/total*100) if total else None)
            last_update = time.monotonic()
    def reject_live(info, *, incomplete=False):
        if info.get('is_live') or info.get('live_status') in ('is_live','is_upcoming'):
            raise ValueError('不支援直播中或尚未開始的影片。')
    # Prefer playable MP4/H.264, then other MP4, then other video-only formats.
    # Every branch respects the same 720p/30fps cap; no muxed audio fallback.
    options = dict(format=VIDEO_FORMAT, noplaylist=True, outtmpl=str(folder/'video_source.%(ext)s'),
                   js_runtimes={'node':{'path':str(APP/'bin/node.exe')}},
                   ffmpeg_location=str(APP/'bin'), progress_hooks=[progress], match_filter=reject_live,
                   max_filesize=VIDEO_LIMIT, socket_timeout=20, retries=2, fragment_retries=2,
                   quiet=True, noprogress=True, no_color=True, cachedir=False)
    stage('video_downloading')
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(youtube_url(url), download=True)
        if not info or info.get('_type') in ('playlist','multi_video'):
            raise ValueError('無法取得純影片串流。')
        source = Path(ydl.prepare_filename(info)).resolve()
    if not source.is_relative_to(folder.resolve()) or not source.is_file():
        raise ValueError('未取得影片檔案，可能超過 2 GB 或來源無法存取。')
    source_info = probe(source, APP)
    streams = source_info.get('streams', [])
    video = next((s for s in streams if s['codec_type']=='video'), None)
    if not video or any(s['codec_type']=='audio' for s in streams):
        raise ValueError('來源不是純影片串流。')
    compatible = video['codec_name']=='h264' and video.get('pix_fmt')=='yuv420p'
    stage('video_packaging' if compatible else 'video_converting')
    output = folder/'background_video.mp4'
    # Limits are applied during stream selection, without upscaling or
    # increasing frame rate. Music uses the same source timeline origin.
    conversion = convert_silent(source, output, APP)
    record = register_video(output, assets, APP, audio, youtube_url(url))
    record.update(conversion, origin='youtube', selection_policy='mp4_h264_first_720p30',
                  selected_format_id=info.get('format_id'))
    write_json(assets.root/record['id']/'asset.json', record)
    return record, output


def download(url, folder, workspace, include_video=False):
    import yt_dlp
    for name in ('ffmpeg.exe', 'ffprobe.exe', 'node.exe'):
        if not (APP/'bin'/name).is_file():
            raise ValueError(f'缺少 {name}，請確認 bin 資料夾完整。')
    last_update = 0.

    def progress(message):
        nonlocal last_update
        downloaded = message.get('downloaded_bytes') or 0
        if downloaded > LIMIT:
            raise ValueError('音訊超過 200 MB，已停止下載。')
        if message['status'] == 'finished':
            stage('converting')
        elif message['status'] == 'downloading' and time.monotonic()-last_update > .4:
            total = message.get('total_bytes') or message.get('total_bytes_estimate')
            percent = min(100, round(downloaded/total*100, 1)) if total else None
            stage('downloading', percent)
            last_update = time.monotonic()

    def reject_live(info, *, incomplete=False):
        if info.get('is_live') or info.get('live_status') in ('is_live', 'is_upcoming'):
            raise ValueError('請使用已發布的影片；不支援直播中或尚未開始的影片。')

    options = dict(format='bestaudio', noplaylist=True, outtmpl=str(folder/'audio.%(ext)s'),
        ffmpeg_location=str(APP/'bin'), js_runtimes={'node': {'path': str(APP/'bin/node.exe')}},
        progress_hooks=[progress], postprocessor_hooks=[lambda _: stage('converting')],
        postprocessors=[dict(key='FFmpegExtractAudio', preferredcodec='mp3', preferredquality='192')],
        match_filter=reject_live, max_filesize=LIMIT, socket_timeout=20, retries=2, fragment_retries=2,
        quiet=True, noprogress=True, no_color=True, cachedir=False)
    stage('fetching')
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(youtube_url(url), download=True)
    path = folder/'audio.mp3'
    if not info or info.get('_type') in ('playlist', 'multi_video') or not path.is_file():
        raise ValueError('未取得可用的音訊，影片可能無法存取或檔案超過 200 MB。')
    stage('registering')
    assets = AssetStore(Path(workspace)/'uploads')
    with path.open('rb') as stream:
        asset = assets.upload(FileStorage(stream=stream, filename='YouTube audio.mp3'), 'audio')
    title = clean(info.get('track') or info.get('title')) or 'YouTube audio'
    artist = clean(info.get('artist') or info.get('creator') or info.get('uploader'))
    asset.update(title=title, artist=artist, original_name=title+'.mp3', source_url=youtube_url(url))
    write_json(assets.root/asset['id']/'asset.json', asset)
    stage('background')
    with yt_dlp.YoutubeDL(dict(quiet=True, no_color=True, socket_timeout=10, cachedir=False)) as ydl:
        background, warning = download_background(info, ydl, assets, youtube_url(url))
    video = None
    if include_video:
        video, video_path = download_video(url, folder, assets, asset)
        if not background:
            # Keep a real image even when the thumbnail server is unavailable.
            still = folder/'video_cover.jpg'
            subprocess.run([str(APP/'bin/ffmpeg.exe'),'-nostdin','-y','-v','error','-i',str(video_path),
                            '-frames:v','1',str(still)],check=True,
                           creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            with still.open('rb') as stream:
                background = assets.upload(FileStorage(stream=stream,filename='Video cover.jpg'),'background')
            background.update(source_url=youtube_url(url))
            write_json(assets.root/background['id']/'asset.json',background)
            warning = '無法取得 YouTube 封面，已使用影片畫面作為背景圖片。'
    return dict(asset=asset, background=background, video=video, warning=warning)


def main():
    folder = Path(sys.argv[1]).resolve()
    request = read_json(folder/'request.json')
    try:
        result = download(request['url'], folder, request['workspace'], request.get('include_video',False))
        write_json(folder/'result.json', result)
    except Exception as exc:
        detail = re.sub(r'\x1b\[[0-9;]*m', '', str(exc))[-1600:]
        message = '下載未完成。影片可能無法存取、需要登入，或連線暫時失敗。可重試或改用音檔上傳。\n' + detail
        write_json(folder/'result.json', dict(error=message))
        print(message, flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
