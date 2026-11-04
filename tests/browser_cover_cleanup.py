"""Real cover import and destructive UI checks, in a disposable workspace only."""
from pathlib import Path
import io
import json
import sys
import tempfile
import threading
from PIL import Image
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from server import create_app

QA=APP/'workspace/qa'
with tempfile.TemporaryDirectory(prefix='cover-cleanup-',dir=QA) as temporary:
    root=Path(temporary)
    application=create_app(root,run_worker=False)
    application.extensions['studio_imports'].run_worker=True
    service=make_server('127.0.0.1',8786,application,threaded=True)
    threading.Thread(target=service.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
            context=browser.new_context(base_url='http://127.0.0.1:8786',viewport={'width':1440,'height':1100})
            page=context.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto('/');expect(page.locator('#connection-text')).to_have_text('本機已連線')
            for field,value in [('title','舊歌曲'),('artist','舊歌手'),('title-romanized','Old title'),('artist-romanized','Old artist'),('source','Old source'),('tags','old tags'),('creator','Keep Creator'),('version','Keep Difficulty')]:
                page.locator('#'+field).fill(value)
            page.locator('#stars').fill('3')
            page.locator('#youtube-url').fill('https://youtu.be/YE7VzlLtp-4')
            page.locator('#youtube-download').click()
            expect(page.locator('#clear-history')).to_be_disabled()
            expect(page.locator('#youtube-status')).to_have_text('音訊已加入，可以試聽或生成譜面。',timeout=120000)
            expect(page.locator('#title')).to_have_value('Big Buck Bunny')
            expect(page.locator('#artist')).to_have_value('Blender')
            for field in ['title-romanized','artist-romanized','source','tags']:expect(page.locator('#'+field)).to_have_value('')
            expect(page.locator('#creator')).to_have_value('Keep Creator')
            expect(page.locator('#version')).to_have_value('Keep Difficulty')
            expect(page.locator('#stars')).to_have_value('3')
            expect(page.locator('#background-loaded')).to_be_visible()
            expect(page.locator('#preview-image')).to_be_visible()
            cover_url=page.locator('#preview-image').get_attribute('src')
            cover=context.request.get(cover_url)
            img=Image.open(io.BytesIO(cover.body()));assert img.width>=320 and img.format in ('JPEG','PNG')
            page.evaluate('scrollTo(0,0)');page.screenshot(path=str(QA/'cover-cleanup-desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(QA/'cover-cleanup-mobile.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.set_viewport_size({'width':1440,'height':1100})
            # Manual background must survive another import, and cover failures
            # must not discard the successfully downloaded song.
            custom=io.BytesIO();Image.new('RGB',(800,450),(50,20,80)).save(custom,format='PNG')
            page.locator('#background-file').set_input_files({'name':'custom.png','mimeType':'image/png','buffer':custom.getvalue()})
            expect(page.locator('#background-detail')).to_have_text('800 × 450')
            custom_url=page.locator('#preview-image').get_attribute('src')
            asset_path=next((root/'uploads').glob('*/source.mp3')).parent/'asset.json'
            asset=json.loads(asset_path.read_text(encoding='utf-8'))
            item=dict(id='f'*32,status='completed',stage='completed',asset=asset,background={'id':'e'*32,'url':cover_url,'source_url':'https://youtu.be/YE7VzlLtp-4'},progress=100,error=None,warning=None)
            def mock(route):route.fulfill(status=200,content_type='application/json',body=json.dumps(item))
            page.route('**/api/audio-imports',mock);page.route('**/api/audio-imports/'+item['id'],mock)
            page.locator('#youtube-download').click();expect(page.locator('#youtube-status')).to_contain_text('音訊已加入')
            expect(page.locator('#preview-image')).to_have_attribute('src',custom_url)
            item.update(background=None,warning='封面無法下載，但音訊已加入。')
            page.locator('#youtube-download').click();expect(page.locator('#youtube-error')).to_have_text(item['warning'])
            expect(page.locator('#audio-loaded')).to_be_visible()
            page.unroute('**/api/audio-imports',mock);page.unroute('**/api/audio-imports/'+item['id'],mock)
            with page.expect_response(lambda r:r.url.endswith('/api/jobs') and r.request.method=='POST') as pending:
                page.locator('#generate-button').click()
            job=pending.value.json()
            assert job['request']['background_id']==custom_url.split('/')[3]
            expect(page.locator('#clear-history')).to_be_disabled()
            page.locator('#cancel-job').click();expect(page.locator('#clear-history')).to_be_enabled()
            # Seed a completed export-sized file; no real user history is present.
            (root/'jobs'/job['id']/'test.osz').write_bytes(b'fixture beatmap')
            stats=context.request.get('/api/history/cleanup').json();assert stats['bytes']>0
            page.once('dialog',lambda dialog:dialog.dismiss())
            page.locator('#clear-history').click()
            expect(page.locator('#clear-history')).to_be_enabled()
            assert (root/'jobs'/job['id']).exists()
            dialogs=[]
            def accept(dialog):dialogs.append(dialog.message);dialog.accept()
            page.once('dialog',accept);page.locator('#clear-history').click()
            expect(page.locator('#history-count')).to_have_text('0')
            expect(page.locator('#audio-empty')).to_be_visible()
            expect(page.locator('#background-empty')).to_be_visible()
            expect(page.locator('#generate-button')).to_be_disabled()
            assert dialogs and '永久刪除' in dialogs[0]
            for name in ('jobs','uploads','imports'):assert not list((root/name).iterdir())
            page.reload();expect(page.locator('#history-count')).to_have_text('0')
            assert context.request.get('/api/history/cleanup').json()['bytes']==0
            assert not errors,errors
            browser.close()
            print('PASS: real YouTube cover, metadata reset, custom background retained, cover failure fallback, generation background ID, cleanup confirmation and files, mobile',flush=True)
    finally:
        application.extensions['studio_imports'].close()
        service.shutdown();service.server_close()
