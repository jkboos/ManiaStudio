"""Metadata/background packaging only; never modify generated hit objects."""
from __future__ import annotations
import hashlib
import copy
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile

_archive_lock = threading.Lock()


def archive_osu_name(export_id):
    if not isinstance(export_id, str) or not re.fullmatch(r'[a-f0-9]{32}', export_id):
        raise ValueError('Invalid generation ID')
    return f'ManiaStudio-{export_id}.osu'


def ensure_unique_archive(export_dir, job_id):
    """Upgrade old history archives without changing map/media contents.

    Local imports must not reuse the generic internal beatmap.osu filename.
    Keep the canonical disk filenames for existing workers and download URLs.
    Only replace the archive after the rebuilt ZIP has passed integrity checks.
    """
    expected = archive_osu_name(job_id)
    archive_path = Path(export_dir)/'beatmap.osz'
    with _archive_lock:
        temporary = None
        try:
            with zipfile.ZipFile(archive_path) as source:
                maps = [i for i in source.infolist() if i.filename.lower().endswith('.osu')]
                if len(maps) != 1:
                    raise ValueError('Expected one generated beatmap per archive')
                if maps[0].filename == expected:
                    return archive_path
                with tempfile.NamedTemporaryFile(dir=archive_path.parent, prefix='import-', suffix='.tmp', delete=False) as f:
                    temporary = Path(f.name)
                with zipfile.ZipFile(temporary, 'w') as target:
                    for info in source.infolist():
                        renamed = copy.copy(info)
                        if info is maps[0]:
                            renamed.filename = expected
                        with source.open(info) as src, target.open(renamed, 'w', force_zip64=True) as dst:
                            shutil.copyfileobj(src, dst, 1024*1024)
                with zipfile.ZipFile(temporary) as check:
                    if check.testzip() is not None:
                        raise ValueError('Rebuilt archive failed integrity validation')
                    for info in source.infolist():
                        name = expected if info is maps[0] else info.filename
                        updated = check.getinfo(name)
                        if (updated.CRC, updated.file_size) != (info.CRC, info.file_size):
                            raise ValueError('Archive upgrade changed file contents')
            # Windows may still have a previous download open briefly.
            for delay in (.05, .1, .2, .4, .8, 1.6, None):
                try:
                    os.replace(temporary, archive_path)
                    break
                except PermissionError:
                    if delay is None:
                        raise
                    time.sleep(delay)
            return archive_path
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass # Preserve a failed replacement's original exception.


def download_name(job, kind):
    """A stable archive name per generation, including legacy history entries.

    osu!stable imports local archives into a directory named after the archive.
    Keep the job ID even when metadata is identical or filename characters are
    removed. Internal media paths remain relative to that independent directory.
    """
    if kind not in ('osu', 'osz', 'report'):
        raise ValueError('Unknown download type')
    job_id = job['id']
    if not re.fullmatch(r'[a-f0-9]{32}', job_id):
        raise ValueError('Invalid generation ID')
    metadata = job['request']['metadata']
    def safe(value, limit, fallback):
        value = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', ' ', str(value or ''))
        return re.sub(r'\s+', ' ', value).strip(' .')[:limit].rstrip(' .') or fallback
    artist = safe(metadata.get('artist'), 20, 'Unknown')
    title = safe(metadata.get('title'), 32, 'Untitled')
    extension = 'json' if kind == 'report' else kind
    return f"ManiaStudio {artist} - {title} [{job['request']['keys']}K {job_id}].{extension}"


def metadata_text(text, metadata, background_name=None, video_name=None):
    mapping = {'Title': metadata['title_romanized'] or metadata['title'],
               'TitleUnicode': metadata['title'],
               'Artist': metadata['artist_romanized'] or metadata['artist'],
               'ArtistUnicode': metadata['artist'], 'Creator': metadata['creator'],
               'Version': metadata['version'], 'Source': metadata['source'], 'Tags': metadata['tags'],
               'BeatmapID': '0', 'BeatmapSetID': '-1'}
    section = '[Metadata]\n' + '\n'.join(f'{k}:{v}' for k, v in mapping.items()) + '\n\n'
    text, count = re.subn(r'(?ms)^\[Metadata\]\s*\n.*?(?=^\[)', lambda _: section, text, count=1)
    if count != 1:
        raise ValueError('Missing metadata section')
    if video_name and not background_name:
        raise ValueError('含影片的譜面仍需背景圖片。')
    if background_name:
        events = f'[Events]\n0,0,"{background_name}",0,0\n'
        if video_name:
            events += f'Video,0,"{video_name}",0,0\n'
        text, count = re.subn(r'(?ms)^\[Events\]\s*\n.*?(?=^\[)',
                             lambda _: events+'\n', text, count=1)
        if count != 1:
            raise ValueError('Missing events section')
    return text


def package_result(source: Path, destination: Path, request, background: Path | None, frozen_manifest, video: Path | None = None):
    from prepare_dataset import parse_chart
    from osu_export import validate_notes, calculated_stars
    from audio_features import sha256_file
    report = json.loads((source/'generation_report.json').read_text(encoding='utf-8'))
    original = (source/report['osu_file']).read_text(encoding='utf-8')
    old_chart = parse_chart(source/report['osu_file'])
    destination.mkdir(parents=True, exist_ok=False)
    audio_name = old_chart['general']['AudioFilename']
    shutil.copy2(source/audio_name, destination/audio_name)
    background_name = None
    if background:
        background_name = 'background' + background.suffix.lower()
        shutil.copy2(background, destination/background_name)
    video_name = None
    if video:
        if not background:
            raise ValueError('含影片的譜面仍需背景圖片。')
        video_name = 'video.mp4'
        shutil.copy2(video, destination/video_name)
        if sha256_file(video) != sha256_file(destination/video_name):
            raise ValueError('Exported video differs')
    text = metadata_text(original, request['metadata'], background_name, video_name)
    if text.split('[HitObjects]', 1)[1] != original.split('[HitObjects]', 1)[1]:
        raise ValueError('Metadata export changed hit objects')
    osu = destination/'beatmap.osu'
    osu.write_text(text, encoding='utf-8')
    parsed = parse_chart(osu)
    if parsed['errors'] or parsed['key_count'] != request['keys']:
        raise ValueError('Exported map validation failed')
    validate_notes(parsed['notes'], request['keys'])
    if parsed['notes'] != old_chart['notes'] or max(n[1] for n in parsed['notes']) > report['audio_duration_s']*1000:
        raise ValueError('Exported notes differ or exceed audio duration')
    stars = calculated_stars(text)
    if abs(stars-report['actual_stars']) > 1e-8:
        raise ValueError('Metadata export changed calculated difficulty')
    if sha256_file(destination/audio_name) != report['audio_sha256']:
        raise ValueError('Exported audio differs')
    export_id = destination.parent.name
    if not re.fullmatch(r'[a-f0-9]{32}', export_id):
        export_id = uuid.uuid4().hex
    map_name = archive_osu_name(export_id)
    filenames = [map_name, audio_name] + ([background_name] if background_name else []) + ([video_name] if video_name else [])
    with zipfile.ZipFile(destination/'beatmap.osz', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in filenames:
            archive.write(osu if name == map_name else destination/name, name)
    with zipfile.ZipFile(destination/'beatmap.osz') as archive:
        if archive.testzip() or set(archive.namelist()) != set(filenames):
            raise ValueError('Invalid osu archive')
        for name in filenames:
            if hashlib.sha256(archive.read(name)).hexdigest() != sha256_file(osu if name == map_name else destination/name):
                raise ValueError('Archive file differs')
    result = dict(actual_stars=stars, target_stars=request['stars'], keys=request['keys'],
                  taps=report['note_count'], holds=report['ln_count'],
                  ln_fraction=report['ln_count']/max(1, report['ln_count']+report['note_count']),
                  duration_s=report['audio_duration_s'], bpm=report['timing']['bpm'],
                  background_file=background_name, video_file=video_name, metadata=request['metadata'],
                  techniques=request['techniques'], backend_version=frozen_manifest['version'],
                  validated=True, archive_osu_file=map_name, export_id=export_id,
                  technique_analysis=report.get('technique_analysis'),
                  local_repair=report.get('local_repair'),
                  inference_policy=report.get('inference_policy'),
                  ln_plan=next((c.get('ln_plan') for c in report['candidates'] if c['candidate']==report['selected_candidate']),None),
                  note='段位偏好與目標星數僅供生成參考，仍需實際試玩確認。')
    (destination/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
