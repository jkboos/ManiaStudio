"""Opt-in real-network smoke check: run manually, never as a unit test."""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright, expect

APP=Path(__file__).resolve().parents[1]
QA=APP/'workspace/qa'
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1100})
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto('http://localhost:8765')
    expect(page.locator('#connection-text')).to_have_text('本機已連線')
    expect(page.locator('#youtube-download')).to_be_enabled()
    page.locator('#youtube-url').fill('https://youtu.be/YE7VzlLtp-4')
    with page.expect_response(lambda r:r.url.endswith('/api/audio-imports') and r.request.method=='POST') as submitted:
        page.locator('#youtube-download').click()
    item=submitted.value.json()
    expect(page.locator('#youtube-status')).to_have_text('音訊已加入，可以試聽或生成譜面。',timeout=120000)
    expect(page.locator('#title')).to_have_value('Big Buck Bunny')
    expect(page.locator('#artist')).to_have_value('Blender')
    expect(page.locator('#generate-button')).to_be_enabled()
    page.locator('#audio-player').evaluate('(audio)=>audio.play()')
    page.wait_for_timeout(600)
    assert page.locator('#audio-player').evaluate('(audio)=>audio.currentTime>0 && !audio.error')
    page.locator('#audio-player').evaluate('(audio)=>audio.pause()')
    result=page.request.get('http://localhost:8765/api/audio-imports/'+item['id']).json()
    assert result['asset']['duration_s']>590
    (QA/'youtube-live-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    page.evaluate('scrollTo(0,0)');page.screenshot(path=str(QA/'youtube-live-desktop.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(QA/'youtube-live-mobile.png'),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not errors,errors
    print(json.dumps({'status':result['status'],'title':result['asset']['title'],'duration_s':result['asset']['duration_s'],'playback':'passed','browser_errors':errors}),flush=True)
    browser.close()
