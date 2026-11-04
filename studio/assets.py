from __future__ import annotations
import math
from pathlib import Path
import uuid
import warnings

import soundfile as sf
from PIL import Image, ImageOps
from mutagen import File as AudioTags
from .domain import ID, read_json, write_json


class AssetStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, asset_id, expected_kind=None):
        if not isinstance(asset_id, str) or not ID.fullmatch(asset_id):
            raise ValueError('找不到上傳檔案，請重新上傳。')
        folder = self.root/asset_id
        try:
            record = read_json(folder/'asset.json')
        except (OSError, ValueError):
            raise ValueError('找不到上傳檔案，請重新上傳。') from None
        if expected_kind and record['kind'] != expected_kind:
            raise ValueError('上傳檔案類型不符。')
        path = (folder/record['file']).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file():
            raise ValueError('找不到上傳檔案。')
        return record, path

    def upload(self, storage, kind):
        if kind not in ('audio', 'background'):
            raise ValueError('不支援的上傳類型。')
        original = storage.filename or ''
        suffix = Path(original).suffix.lower()
        allowed = {'.mp3', '.wav', '.ogg', '.flac'} if kind == 'audio' else {'.jpg', '.jpeg', '.png', '.webp'}
        if suffix not in allowed:
            raise ValueError('音檔支援 MP3、WAV、OGG、FLAC；圖片支援 JPG、PNG、WebP。')
        asset_id = uuid.uuid4().hex
        folder = self.root/asset_id
        folder.mkdir()
        path = folder/('source'+suffix)
        limit = (200 if kind == 'audio' else 20)*1024*1024
        size = 0
        with path.open('wb') as output:
            for chunk in iter(lambda: storage.stream.read(1024*1024), b''):
                size += len(chunk)
                if size > limit:
                    raise ValueError('音檔上限為 200 MB，背景圖上限為 20 MB。')
                output.write(chunk)
        if not size:
            raise ValueError('檔案是空的。')
        record = dict(id=asset_id, kind=kind, original_name=original, file=path.name, bytes=size)
        if kind == 'audio':
            try:
                info = sf.info(path)
                duration = info.frames/info.samplerate
                if not math.isfinite(duration) or duration < 1 or info.channels < 1:
                    raise ValueError()
            except Exception:
                raise ValueError('無法讀取音檔，請確認檔案有效且至少有 1 秒音訊。') from None
            title, artist = Path(original).stem, ''
            try:
                tags = AudioTags(path, easy=True)
                if tags:
                    title = str(tags.get('title', [title])[0])
                    artist = str(tags.get('artist', [''])[0])
            except Exception:
                pass
            record.update(duration_s=duration, sample_rate=info.samplerate, channels=info.channels,
                          title=title[:250], artist=artist[:250])
        else:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('error', Image.DecompressionBombWarning)
                    with Image.open(path) as raw:
                        if raw.format not in ('JPEG', 'PNG', 'WEBP') or raw.width*raw.height > 40_000_000:
                            raise ValueError()
                        raw.load()
                        image = ImageOps.exif_transpose(raw)
                        # Export a standard osu-compatible image, without EXIF
                        # orientation surprises or external resources.
                        export = folder/('background.jpg' if raw.format == 'JPEG' else 'background.png')
                        if raw.format == 'JPEG':
                            image.convert('RGB').save(export, quality=95)
                        else:
                            image.save(export, format='PNG')
                        record.update(file=export.name, width=image.width, height=image.height)
            except Exception:
                raise ValueError('無法讀取圖片，請使用有效的 JPG、PNG 或 WebP（最多 4,000 萬像素）。') from None
        record['url'] = f'/api/uploads/{asset_id}/file'
        write_json(folder/'asset.json', record)
        return record
