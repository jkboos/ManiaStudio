from __future__ import annotations
import atexit
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import uuid

from .domain import ID, read_json, write_json


def now():
    return datetime.now(timezone.utc).isoformat()


class Jobs:
    def __init__(self, app_root, workspace, assets, run_worker=True):
        self.app_root, self.root, self.assets = Path(app_root), Path(workspace)/'jobs', assets
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.items, self.processes = {}, {}
        self.inflight = set()
        self.pending = queue.Queue()
        self.stopping = threading.Event()
        for path in self.root.glob('*/job.json'):
            try:
                item = read_json(path)
                if item['status'] in ('queued', 'running'):
                    item.update(status='failed', stage='failed', error='上次服務已中斷，請重新生成。', finished_at=now())
                    write_json(path, item)
                self.items[item['id']] = item
            except (OSError, ValueError, KeyError):
                continue
        if run_worker:
            threading.Thread(target=self.worker, daemon=True, name='mania-generator').start()
            atexit.register(self.close)

    def update(self, job_id, **fields):
        with self.lock:
            self.items[job_id].update(fields)
            write_json(self.root/job_id/'job.json', self.items[job_id])

    def get(self, job_id):
        with self.lock:
            if not isinstance(job_id, str) or not ID.fullmatch(job_id) or job_id not in self.items:
                raise KeyError(job_id)
            return json.loads(json.dumps(self.items[job_id]))

    def list(self):
        with self.lock:
            return [self.get(i['id']) for i in sorted(self.items.values(), key=lambda x: x['created_at'], reverse=True)[:40]]

    def submit(self, request):
        audio, audio_path = self.assets.get(request['audio_id'], 'audio')
        background_path = None
        if request['background_id']:
            _, background_path = self.assets.get(request['background_id'], 'background')
        video_path = None
        if request.get('video_id'):
            video, video_path = self.assets.get(request['video_id'], 'video')
            if video.get('audio_id') != audio['id'] or (video.get('origin')!='upload' and video.get('source_url') != audio.get('source_url')):
                raise ValueError('背景影片與目前音檔不是同一次下載，請重新選擇含影片下載。')
            if not background_path:
                raise ValueError('含影片的譜面仍需背景圖片，請保留封面或上傳背景圖。')
        with self.lock:
            if sum(x['status'] in ('queued', 'running') for x in self.items.values()) >= 4:
                raise ValueError('佇列目前已滿，請等候正在生成的譜面完成。')
            job_id = uuid.uuid4().hex
            folder = self.root/job_id
            folder.mkdir()
            write_json(folder/'request.json', dict(request=request, audio_path=str(audio_path),
                                                 background_path=str(background_path) if background_path else None,
                                                 video_path=str(video_path) if video_path else None))
            item = dict(id=job_id, status='queued', stage='queued', created_at=now(), request=request,
                        duration_s=audio['duration_s'], error=None, result=None)
            self.items[job_id] = item
            write_json(folder/'job.json', item)
            self.pending.put(job_id)
            return self.get(job_id)

    def cancel(self, job_id):
        with self.lock:
            item = self.get(job_id)
            if item['status'] not in ('queued', 'running'):
                return item
            self.update(job_id, status='cancelled', stage='cancelled', finished_at=now())
            proc = self.processes.get(job_id)
            if proc and proc.poll() is None:
                proc.terminate()
            return self.get(job_id)

    def worker(self):
        while not self.stopping.is_set():
            try:
                job_id = self.pending.get(timeout=.5)
            except queue.Empty:
                continue
            try:
                if self.get(job_id)['status'] != 'queued':
                    continue
                self.run(job_id)
            except KeyError:
                # A cancelled queued item can have been cleared from history.
                continue
            finally:
                self.pending.task_done()

    def run(self, job_id):
        folder = self.root/job_id
        with self.lock:
            if self.items.get(job_id, {}).get('status') != 'queued':
                return
            self.inflight.add(job_id)
            self.update(job_id, status='running', stage='preparing', started_at=now())
        env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8', OMP_NUM_THREADS='4')
        env['PATH'] = str(self.app_root/'bin') + os.pathsep + env.get('PATH', '')
        try:
            with (folder/'worker.log').open('w', encoding='utf-8') as log:
                with self.lock:
                    if self.items[job_id]['status'] == 'cancelled':
                        return
                    proc = subprocess.Popen([sys.executable, '-u', str(self.app_root/'runtime/portable_generate.py'), str(folder)],
                        cwd=self.app_root/'runtime', env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    self.processes[job_id] = proc
                for line in proc.stdout:
                    log.write(line); log.flush()
                    if self.get(job_id)['status'] == 'cancelled':
                        continue
                    try:
                        message = json.loads(line)
                        stage = message.get('studio_stage')
                        try:
                            if stage and stage != 'complete':
                                self.update(job_id, stage=stage)
                            elif message.get('status') == 'decoding':
                                self.update(job_id, stage='generating')
                        except OSError as exc:
                            log.write(f'Progress snapshot deferred: {exc}\n');log.flush()
                    except (ValueError, AttributeError):
                        pass
                code = proc.wait()
            if self.get(job_id)['status'] == 'cancelled':
                return
            if code:
                raise RuntimeError('生成程式未能完成，請查看錯誤詳情後再試。')
            result = read_json(folder/'export/result.json')
            self.update(job_id, status='completed', stage='completed', result=result, finished_at=now())
        except Exception as exc:
            if self.get(job_id)['status'] != 'cancelled':
                details = (folder/'worker.log').read_text(encoding='utf-8')[-5000:] if (folder/'worker.log').exists() else str(exc)
                self.update(job_id, status='failed', stage='failed', error=str(exc), error_details=details, finished_at=now())
        finally:
            with self.lock:
                self.processes.pop(job_id, None)
                self.inflight.discard(job_id)

    def close(self):
        self.stopping.set()
        for job in self.list():
            if job['status'] in ('queued', 'running'):
                self.cancel(job['id'])
