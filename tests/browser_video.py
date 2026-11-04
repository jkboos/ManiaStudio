"""Browser interaction and a real control generation using the live-download fixture."""
from pathlib import Path
import json
import re
import sys
import threading
import time
import zipfile
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from server import create_app


def main():
    qa=APP/'workspace/qa/video_import'
    media=json.loads((qa/'live_short/result.json').read_text(encoding='utf-8'))
    workspace=qa/'live_short/workspace'
    app=create_app(workspace)
    http=make_server('127.0.0.1',8766,app,threaded=True)
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1100})
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            # Mock only repeat network downloads; assets and generation endpoints
            # use the real API and the already downloaded, probed media files.
            choices=[];imports={}
            def imported(route):
                if route.request.method!='POST':return route.continue_()
                payload=route.request.post_data_json;choices.append(payload['include_video'])
                id_=f'{len(choices):032x}'
                item=dict(id=id_,url=media['asset']['source_url'],status='completed',stage='completed',
                          progress=100,asset=media['asset'],background=media['background'],
                          video=media['video'] if payload['include_video'] else None,warning=None,error=None)
                imports[id_]=item
                route.fulfill(status=202,json=item)
            page.route('**/api/audio-imports',imported)
            page.route(re.compile(r'/api/audio-imports/[a-f0-9]{32}$'),lambda route:route.fulfill(json=imports[route.request.url.rsplit('/',1)[1]]))
            page.goto('http://localhost:8766')
            expect(page.locator('#youtube-download-video')).to_be_enabled()
            expect(page.locator('#result-actions')).to_be_hidden()
            page.locator('#youtube-url').fill(media['asset']['source_url'])
            page.screenshot(path=str(qa/'download_choices_desktop.png'),full_page=True)
            page.locator('#youtube-download-video').click()
            expect(page.locator('#video-attachment')).to_be_visible()
            expect(page.locator('#background-loaded')).to_be_visible()
            expect(page.locator('#generate-button')).to_be_enabled()
            page.wait_for_function("() => document.querySelector('#video-player').readyState>=1")
            assert page.locator('#video-player').evaluate('(v)=>v.videoWidth>0 && v.muted')
            local_movie=workspace/'uploads'/media['video']['id']/media['video']['file']
            with page.expect_response(lambda r:r.url.endswith('/api/uploads') and r.request.method=='POST') as upload:
                page.locator('#video-file').set_input_files(str(local_movie))
            local_video=upload.value.json()
            assert local_video['origin']=='upload'
            expect(page.locator('#video-player')).to_have_attribute('src',local_video['url'])
            page.wait_for_function("() => document.querySelector('#video-player').readyState>=1")
            page.reload()
            expect(page.locator('#video-attachment')).to_be_visible()
            expect(page.locator('#video-player')).to_have_attribute('src',local_video['url'])
            page.locator('#remove-background').click()
            expect(page.locator('#generate-button')).to_be_disabled()
            page.locator('#youtube-url').fill(media['asset']['source_url'])
            page.locator('#youtube-download').click()
            expect(page.locator('#video-attachment')).to_be_hidden()
            expect(page.locator('#background-loaded')).to_be_visible()
            page.locator('#youtube-download-video').click()
            expect(page.locator('#video-attachment')).to_be_visible()
            page.locator('#stars').fill('1')
            page.locator('#stars').dispatch_event('input')
            with page.expect_response(lambda r:r.url.endswith('/api/jobs') and r.request.method=='POST') as submitted:
                page.locator('#generate-button').click()
            job=submitted.value.json();assert job['request']['video_id']==media['video']['id']
            print(json.dumps(dict(stage='generating',job=job['id'])),flush=True)
            deadline=time.monotonic()+240
            while time.monotonic()<deadline:
                job=page.request.get('http://localhost:8766/api/jobs/'+job['id']).json()
                if job['status'] in ('completed','failed','cancelled'):break
                page.wait_for_timeout(1000)
            assert job['status']=='completed',job
            expect(page.locator('#download-osz')).to_be_visible(timeout=10000)
            assert job['result']['video_file']=='video.mp4'
            archive=workspace/'jobs'/job['id']/'export/beatmap.osz'
            with zipfile.ZipFile(archive) as z:
                names=z.namelist();text=z.read('beatmap.osu').decode('utf-8')
                assert 'video.mp4' in names and job['result']['background_file'] in names
                assert 'Video,0,"video.mp4",0,0' in text
            page.screenshot(path=str(qa/'video_completed_desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(qa/'video_mobile.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert choices==[True,False,True] and not errors,(choices,errors)
            report=dict(choices=choices,video_restored_after_reload=True,image_required_with_video=True,
                        youtube_video_preview=True,local_video_upload_preview=True,
                        full_generation_completed=True,job_id=job['id'],actual_stars=job['result']['actual_stars'],
                        package_files=names,javascript_errors=errors,mobile_no_overflow=True)
            (qa/'browser_validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report),flush=True)
            browser.close()
    finally:
        http.shutdown();app.extensions['studio_jobs'].close();app.extensions['studio_imports'].close()


if __name__=='__main__':main()
