"""Mania Studio: loopback-only UI and an isolated, frozen generation worker."""
from __future__ import annotations
import argparse
import threading
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException

from studio.assets import AssetStore
from studio.domain import validate_request, read_json
from studio.jobs import Jobs
from studio.youtube import AudioImports
from studio.history import History

ROOT = Path(__file__).resolve().parent


def create_app(workspace=None, run_worker=True):
    app = Flask(__name__, static_folder=None)
    app.config['MAX_CONTENT_LENGTH'] = (2048+10)*1024*1024
    app.json.ensure_ascii = False
    workspace = Path(workspace or ROOT/'workspace').resolve()
    assets = AssetStore(workspace/'uploads')
    jobs = Jobs(ROOT, workspace, assets, run_worker=run_worker)
    imports = AudioImports(ROOT, workspace, run_worker=run_worker)
    history = History(workspace, jobs, imports)
    storage_lock = threading.RLock()
    app.extensions['studio_jobs'] = jobs
    app.extensions['studio_assets'] = assets
    app.extensions['studio_imports'] = imports

    @app.before_request
    def local_only():
        host = request.host.split(':')[0].lower()
        if host not in ('localhost', '127.0.0.1'):
            return jsonify(error='僅接受 localhost 的連線。'), 403
        origin = request.headers.get('Origin')
        if origin and urlsplit(origin).netloc != request.host:
            return jsonify(error='請從本機介面送出請求。'), 403

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(Exception)
    def errors(error):
        if isinstance(error, ValueError):
            return jsonify(error=str(error)), 400
        if isinstance(error, KeyError):
            return jsonify(error='找不到這個生成項目。'), 404
        if isinstance(error, HTTPException):
            message = '檔案過大，音檔上限為 200 MB，背景圖上限為 20 MB，影片上限為 2 GB。' if error.code == 413 else error.description
            return jsonify(error=message), error.code
        app.logger.exception('Studio request failed')
        return jsonify(error='處理請求時發生錯誤，請再試一次。'), 500

    @app.get('/')
    def index():
        return send_from_directory(ROOT/'web', 'index.html')

    @app.get('/assets/<path:name>')
    def static(name):
        return send_from_directory(ROOT/'web', name)

    @app.get('/api/health')
    def health():
        return jsonify(app='mania-studio', status='ok', version='1.0')

    @app.get('/api/config')
    def config():
        policy=read_json(ROOT/'runtime_policy.json')
        version=policy['version'] if policy['decoder']!='legacy' else read_json(ROOT/'frozen_backend.json')['version']
        return jsonify(version='1.0', backend_version=version,
                       default_techniques=['tech', 'stream', 'LN'], default_keys=4, default_stars=4,
                       audio_limit_mb=200, image_limit_mb=20, video_limit_mb=2048, local_only=True)

    @app.post('/api/uploads')
    def upload():
        if 'file' not in request.files:
            raise ValueError('請選擇檔案。')
        with storage_lock:
            if request.form.get('kind') == 'video':
                from studio.video import upload_video
                return jsonify(upload_video(request.files['file'], assets, ROOT, request.form.get('audio_id'))), 201
            return jsonify(assets.upload(request.files['file'], request.form.get('kind'))), 201

    @app.get('/api/uploads/<asset_id>')
    def asset_info(asset_id):
        record, _ = assets.get(asset_id)
        return jsonify(record)

    @app.post('/api/audio-imports')
    def import_audio():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError('請貼上 YouTube 影片網址。')
        with storage_lock:
            return jsonify(imports.submit(data.get('url'), data.get('include_video', False))), 202

    @app.get('/api/audio-imports/current')
    def current_import():
        return jsonify(item=imports.current())

    @app.get('/api/audio-imports/<import_id>')
    def get_import(import_id):
        return jsonify(imports.get(import_id))

    @app.post('/api/audio-imports/<import_id>/cancel')
    def cancel_import(import_id):
        return jsonify(imports.cancel(import_id))

    @app.get('/api/uploads/<asset_id>/file')
    def asset_file(asset_id):
        record, path = assets.get(asset_id)
        return send_file(path, conditional=True)

    @app.get('/api/jobs')
    def list_jobs():
        return jsonify(jobs=jobs.list())

    @app.post('/api/jobs')
    def submit_job():
        with storage_lock:
            return jsonify(jobs.submit(validate_request(request.get_json()))), 202

    @app.get('/api/history/cleanup')
    def cleanup_preview():
        with storage_lock:
            return jsonify(history.stats())

    @app.delete('/api/history')
    def cleanup_history():
        with storage_lock:
            return jsonify(history.clear())

    @app.get('/api/jobs/<job_id>')
    def job(job_id):
        return jsonify(jobs.get(job_id))

    @app.post('/api/jobs/<job_id>/cancel')
    def cancel(job_id):
        return jsonify(jobs.cancel(job_id))

    @app.get('/api/jobs/<job_id>/download/<kind>')
    def download(job_id, kind):
        job = jobs.get(job_id)
        if job['status'] != 'completed':
            raise ValueError('譜面尚未完成。')
        names = {'osz': 'beatmap.osz', 'osu': 'beatmap.osu', 'report': 'result.json'}
        if kind not in names:
            raise KeyError(kind)
        return send_file(jobs.root/job_id/'export'/names[kind], as_attachment=True, download_name=names[kind])

    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--workspace', type=Path)
    args = parser.parse_args()
    application = create_app(args.workspace)
    try:
        application.run(host='127.0.0.1', port=args.port, debug=False, threaded=True, use_reloader=False)
    finally:
        application.extensions['studio_jobs'].close()
        application.extensions['studio_imports'].close()
