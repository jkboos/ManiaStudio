from __future__ import annotations
import json
import math
import re
import os
import tempfile
import time
from pathlib import Path

AXES = ('speed', 'stamina', 'tech', 'jack', 'stream', 'LN')
ID = re.compile(r'^[a-f0-9]{32}$')
FIELDS = {'title': 250, 'artist': 250, 'title_romanized': 250,
          'artist_romanized': 250, 'creator': 100, 'version': 150,
          'source': 250, 'tags': 600}


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Close a unique same-directory file before replacing the destination.
    # Windows readers/scanners can briefly deny replacement even with valid ACLs.
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,
                                         prefix=path.name+'.',suffix='.tmp',delete=False) as stream:
            temp = Path(stream.name)
            stream.write(payload)
        for delay in (.02,.04,.08,.16,.25,.4,.5,.5,None):
            try:
                os.replace(temp,path)
                break
            except PermissionError:
                if delay is None:
                    raise
                time.sleep(delay)
    finally:
        if temp is not None:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass # Preserve the original failure; never delete the destination.


def validate_request(data):
    if not isinstance(data, dict):
        raise ValueError('請提供有效的生成設定。')
    for name in ('audio_id', 'background_id', 'video_id'):
        value = data.get(name)
        if name in ('background_id', 'video_id') and not value:
            continue
        if not isinstance(value, str) or not ID.fullmatch(value):
            raise ValueError('請先上傳音檔與有效的背景圖片。')
    keys = data.get('keys')
    if type(keys) is not int or keys not in (4, 7):
        raise ValueError('按鍵數必須是 4K 或 7K。')
    stars = data.get('stars')
    if isinstance(stars, bool) or not isinstance(stars, (int, float)) or not math.isfinite(stars) or not .5 <= stars <= 15:
        raise ValueError('目標星數請輸入 0.5 到 15 之間的數值。')
    techniques = data.get('techniques', [])
    if not isinstance(techniques, list) or any(not isinstance(t, str) or t not in AXES for t in techniques):
        raise ValueError('有無法辨識的段位偏好選項。')
    techniques = [a for a in AXES if a in techniques]
    # The Jack chip is the sole control. Ignore obsolete saved/API toggles.
    reduce_jacks = 'jack' not in techniques
    metadata = data.get('metadata', {})
    if not isinstance(metadata, dict):
        raise ValueError('譜面資訊格式不正確。')
    clean = {}
    for key, limit in FIELDS.items():
        text = metadata.get(key, '')
        if not isinstance(text, str) or len(text) > limit or any(ord(c) < 32 or ord(c) == 127 for c in text):
            raise ValueError('譜面資訊不可包含換行或控制字元，內容也不可過長。')
        clean[key] = text.strip()
    defaults = {'title': 'Untitled', 'artist': 'Unknown', 'creator': 'ManiaModel',
                'version': f'{keys}K - {stars:.1f} stars'}
    for key, default in defaults.items():
        clean[key] = clean[key] or default
    clean['tags'] = ' '.join(clean['tags'].split())
    return dict(audio_id=data['audio_id'], background_id=data.get('background_id') or None, video_id=data.get('video_id') or None,
                keys=keys, stars=float(stars), techniques=techniques, reduce_jacks=reduce_jacks,
                metadata=clean)


def profile_string(request):
    terms = [f'{axis}=high' for axis in request['techniques']]
    if 'jack' not in request['techniques']:
        terms.append('jack=low')
    return ','.join(terms)
