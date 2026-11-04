"""Exercise YouTube UI states, recovery and cancellation with deterministic API responses."""
from pathlib import Path
import json
import wave
from playwright.sync_api import sync_playwright, expect
from PIL import Image
import io

APP=Path(__file__).resolve().parents[1]
QA=APP/'workspace/qa'
with wave.open(str(QA/'youtube-ui.wav'),'wb') as f:
    f.setnchannels(1);f.setsampwidth(2);f.setframerate(22050);f.writeframes(b'\0\0'*44100)

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1100})
    page=context.new_page();errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    response=context.request.post('http://localhost:8765/api/uploads',multipart={'kind':'audio','file':{'name':'youtube-ui.wav','mimeType':'audio/wav','buffer':(QA/'youtube-ui.wav').read_bytes()}})
    assert response.status==201
    asset=response.json();asset.update(title='YouTube 測試音樂',artist='測試演出者',original_name='YouTube 測試音樂.mp3')
    cover=io.BytesIO();Image.new('RGB',(640,360),(60,70,100)).save(cover,format='PNG')
    background=context.request.post('http://localhost:8765/api/uploads',multipart={'kind':'background','file':{'name':'cover.png','mimeType':'image/png','buffer':cover.getvalue()}}).json()
    background['source_url']='https://www.youtube.com/watch?v=YE7VzlLtp-4'
    item=dict(id='f'*32,url='https://www.youtube.com/watch?v=YE7VzlLtp-4',status='running',stage='downloading',progress=42,asset=None,error=None)
    def handler(route):
        url=route.request.url
        if url.endswith('/current'):data={'item':None}
        elif url.endswith('/cancel'):
            item.update(status='cancelled',stage='cancelled');data=item.copy()
        else:data=item.copy()
        route.fulfill(status=202 if route.request.method=='POST' and not url.endswith('/cancel') else 200,content_type='application/json',body=json.dumps(data))
    page.route('**/api/audio-imports',handler);page.route('**/api/audio-imports/**',handler)
    page.goto('http://localhost:8765');expect(page.locator('#connection-text')).to_have_text('本機已連線')
    page.locator('#youtube-url').fill('https://youtu.be/YE7VzlLtp-4')
    page.locator('#youtube-url').press('Enter')
    expect(page.locator('#youtube-status')).to_contain_text('42%')
    expect(page.locator('#generate-button')).to_be_disabled()
    expect(page.locator('#choose-audio')).to_be_disabled()
    page.reload();expect(page.locator('#youtube-status')).to_contain_text('42%')
    item.update(status='running',stage='converting',progress=None)
    expect(page.locator('#youtube-status')).to_contain_text('轉換成 MP3')
    item.update(status='completed',stage='completed',progress=100,asset=asset,background=background)
    expect(page.locator('#audio-loaded')).to_be_visible(timeout=10000)
    expect(page.locator('#title')).to_have_value(asset['title'])
    expect(page.locator('#artist')).to_have_value(asset['artist'])
    expect(page.locator('#preview-image')).to_be_visible()
    expect(page.locator('#generate-button')).to_be_enabled()
    assert page.locator('#audio-player').get_attribute('src')==asset['url']
    page.evaluate('scrollTo(0,0)');page.screenshot(path=str(QA/'youtube-desktop.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(QA/'youtube-mobile.png'),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.set_viewport_size({'width':1440,'height':1100})
    page.locator('#title').fill('保留我的手動標題')
    item.update(status='running',stage='fetching',progress=None,asset=None)
    page.locator('#youtube-download').click()
    page.locator('#youtube-cancel').click()
    expect(page.locator('#youtube-status')).to_contain_text('已取消')
    expect(page.locator('#audio-name')).to_have_text(asset['original_name'])
    expect(page.locator('#generate-button')).to_be_enabled()
    item.update(status='running',stage='fetching')
    page.locator('#youtube-download').click()
    item.update(status='failed',stage='failed',error='影片無法存取：測試錯誤')
    expect(page.locator('#youtube-error')).to_have_text('影片無法存取：測試錯誤')
    expect(page.locator('#title')).to_have_value('保留我的手動標題')
    expect(page.locator('#audio-name')).to_have_text(asset['original_name'])
    item.update(status='running',stage='fetching',error=None)
    page.locator('#youtube-download').click()
    item.update(status='completed',stage='completed',asset=asset)
    expect(page.locator('#youtube-status')).to_contain_text('音訊已加入')
    expect(page.locator('#title')).to_have_value(asset['title'])
    assert not errors,errors
    browser.close()
print('PASS: download progress, reload recovery, conversion, metadata, preview, cancellation, retry, failure retention, mobile')
