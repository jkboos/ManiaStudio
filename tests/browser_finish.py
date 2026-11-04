from pathlib import Path
import json
import zipfile
from playwright.sync_api import sync_playwright, expect

APP=Path(__file__).resolve().parents[1]
QA=APP/'workspace/qa'
job=json.loads((QA/'browser-job.json').read_text(encoding='utf-8'))
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1100});errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto('http://localhost:8765');page.wait_for_function("document.querySelector('#connection-text').textContent.includes('已連線')")
    page.get_by_role('button',name='查看結果').first.click()
    page.locator('#download-osz').wait_for(state='visible')
    with page.expect_download() as pending:
        page.locator('#download-osz').click()
    pending.value.save_as(QA/'downloaded.osz')
    with zipfile.ZipFile(QA/'downloaded.osz') as archive:
        text=archive.read('beatmap.osu').decode('utf-8').replace('\r\n','\n')
        assert 'TitleUnicode:DEMON’S SHOT · 介面測試' in text
        assert 'Source:\nTags:\n' in text
        assert '0,0,"background.png",0,0' in text
        assert 'background.png' in archive.namelist()
    # Fill no metadata and select no techniques: defaults must be applied by UI.
    audio=next(APP.parent.glob('Star-t*.mp3'))
    page.locator('#audio-file').set_input_files(str(audio))
    page.locator('#audio-loaded').wait_for(state='visible')
    for name in ['title','artist','creator','version']:
        page.locator('#'+name).fill('')
    for chip in page.locator('[data-tech]').all():
        if chip.get_attribute('aria-pressed')=='true':chip.click()
    sent=[]
    def capture(route):
        if route.request.method=='POST':
            sent.append(route.request.post_data_json)
            route.fulfill(status=400,content_type='application/json',body=json.dumps({'error':'QA: settings captured'}))
        else:route.continue_()
    page.route('**/api/jobs',capture)
    page.locator('#generate-button').click()
    expect(page.locator('#toast')).to_have_text('QA: settings captured')
    assert sent[0]['metadata']['title'] and sent[0]['metadata']['artist']=='Unknown'
    assert sent[0]['metadata']['creator']=='ManiaModel' and sent[0]['metadata']['version']
    assert sent[0]['techniques']==[] and sent[0]['reduce_jacks']
    page.unroute('**/api/jobs',capture)
    # A clean landing view is what the user's own browser sees.
    page.evaluate('localStorage.clear()');page.reload();page.wait_for_timeout(500)
    page.evaluate('scrollTo(0,0)');page.screenshot(path=str(QA/'desktop-final.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(QA/'mobile-final.png'),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not errors,errors
    browser.close()
print('PASS: real download, background, Unicode, optional metadata, no techniques, desktop/mobile, no browser errors')
