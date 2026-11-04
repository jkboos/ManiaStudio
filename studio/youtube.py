"""Persistent, cancellable YouTube audio imports, separate from GPU generation."""
from __future__ import annotations
import atexit
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from urllib.parse import parse_qs, urlsplit
import uuid

from .domain import ID, read_json, write_json
from .jobs import now

ACTIVE = ('queued', 'running')


def youtube_url(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ValueError('請貼上 YouTube 單支影片的網址。')
    value = value.strip()
    if '://' not in value:
        value = 'https://' + value
    parsed = urlsplit(value)
    if parsed.scheme not in ('https', 'http') or parsed.username or parsed.password or parsed.port:
        raise ValueError('請使用有效的 YouTube 影片網址。')
    host = (parsed.hostname or '').lower()
    parts = parsed.path.strip('/').split('/')
    video_id = None
    if host in ('youtu.be', 'www.youtu.be') and len(parts) == 1:
        video_id = parts[0]
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'www.youtube-nocookie.com'):
        if parsed.path == '/watch':
            video_id = parse_qs(parsed.query).get('v', [''])[0]
        elif len(parts) == 2 and parts[0] in ('shorts', 'embed', 'live'):
            video_id = parts[1]
    if not video_id or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
        raise ValueError('請貼上單支 YouTube 影片網址，不支援播放清單或頻道網址。')
    # Strip playlist, tracking, and timestamp parameters: import the full song.
    return f'https://www.youtube.com/watch?v={video_id}'


def terminate_tree(process):
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        process.terminate()


class AudioImports:
    def __init__(self, app_root, workspace, run_worker=True):
        self.app_root = Path(app_root)
        self.root = Path(workspace)/'imports'
        self.root.mkdir(parents=True, exist_ok=True)
        self.workspace = Path(workspace)
        self.lock = threading.RLock()
        self.items, self.processes = {}, {}
        self.inflight = set()
        self.run_worker = run_worker
        for path in self.root.glob('*/import.json'):
            try:
                item = read_json(path)
                if item['status'] in ACTIVE:
                    item.update(status='failed', stage='failed', error='下載因服務重啟而中斷，請重新下載。', finished_at=now())
                    write_json(path, item)
                self.items[item['id']] = item
            except (OSError, ValueError, KeyError):
                continue
        if run_worker:
            atexit.register(self.close)

    def get(self, import_id):
        with self.lock:
            if not isinstance(import_id, str) or not ID.fullmatch(import_id) or import_id not in self.items:
                raise KeyError(import_id)
            return json.loads(json.dumps(self.items[import_id]))

    def current(self):
        with self.lock:
            return next((self.get(k) for k, v in self.items.items() if v['status'] in ACTIVE), None)

    def update(self, import_id, **fields):
        with self.lock:
            self.items[import_id].update(fields)
            write_json(self.root/import_id/'import.json', self.items[import_id])

    def submit(self, value, include_video=False):
        if type(include_video) is not bool:
            raise ValueError('影片下載選項格式不正確。')
        url = youtube_url(value)
        with self.lock:
            if self.current():
                raise ValueError('已有音訊正在下載，請完成或取消後再加入。')
            import_id = uuid.uuid4().hex
            folder = self.root/import_id
            folder.mkdir()
            item = dict(id=import_id, url=url, status='queued', stage='fetching',
                        created_at=now(), progress=None, asset=None, background=None, video=None,
                        include_video=include_video, warning=None, error=None)
            self.items[import_id] = item
            write_json(folder/'import.json', item)
            write_json(folder/'request.json', dict(url=url, workspace=str(self.workspace), include_video=include_video))
            if self.run_worker:
                threading.Thread(target=self.run, args=(import_id,), daemon=True, name='youtube-import').start()
            return self.get(import_id)

    def cancel(self, import_id):
        with self.lock:
            item = self.get(import_id)
            if item['status'] in ACTIVE:
                self.update(import_id, status='cancelled', stage='cancelled', finished_at=now())
                process = self.processes.get(import_id)
                if process:
                    terminate_tree(process)
            return self.get(import_id)

    def run(self, import_id):
        folder = self.root/import_id
        env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        with self.lock:
            if self.items.get(import_id, {}).get('status') != 'queued':
                return
            self.inflight.add(import_id)
            self.update(import_id, status='running', started_at=now())
        try:
            with (folder/'worker.log').open('w', encoding='utf-8') as log:
                with self.lock:
                    if self.items[import_id]['status'] != 'running':
                        return
                    process = subprocess.Popen([sys.executable, '-u', '-m', 'studio.youtube_worker', str(folder)],
                        cwd=self.app_root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    self.processes[import_id] = process
                for line in process.stdout:
                    log.write(line); log.flush()
                    try:
                        message = json.loads(line)
                        if message.get('import_stage') in ('fetching', 'downloading', 'converting', 'registering', 'background', 'video_downloading', 'video_converting', 'video_packaging'):
                            with self.lock:
                                if self.items[import_id]['status'] in ACTIVE:
                                    try:
                                        self.update(import_id, stage=message['import_stage'], progress=message.get('progress'))
                                    except OSError as exc:
                                        # Keep draining the worker pipe. A failed progress
                                        # snapshot must not break the media download.
                                        log.write(f'Progress snapshot deferred: {exc}\n');log.flush()
                    except (ValueError, AttributeError):
                        pass
                code = process.wait()
            with self.lock:
                if self.items[import_id]['status'] == 'cancelled':
                    return
                result = read_json(folder/'result.json') if (folder/'result.json').exists() else {}
                if code or 'asset' not in result:
                    raise RuntimeError(result.get('error') or '無法完成下載，請稍後再試或改用音檔上傳。')
                self.update(import_id, status='completed', stage='completed', asset=result['asset'],
                            background=result.get('background'), video=result.get('video'), warning=result.get('warning'),
                            progress=100, finished_at=now())
        except Exception as exc:
            with self.lock:
                if self.items[import_id]['status'] != 'cancelled':
                    self.update(import_id, status='failed', stage='failed', error=str(exc), finished_at=now())
        finally:
            with self.lock:
                self.processes.pop(import_id, None)
                self.inflight.discard(import_id)

    def close(self):
        with self.lock:
            for import_id in list(self.items):
                if self.items[import_id]['status'] in ACTIVE:
                    self.cancel(import_id)
