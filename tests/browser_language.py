"""Exercise language switching in a browser without touching user history."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Thread
import json
from playwright.sync_api import sync_playwright

APP=Path(__file__).resolve().parents[1]
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(APP/'web'),**kwargs)
    def do_GET(self):
        if self.path.startswith('/assets/'):self.path=self.path[len('/assets'):]
        super().do_GET()
    def log_message(self,*args):pass

def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    Thread(target=server.serve_forever,daemon=True).start()
    qa=APP/'workspace/qa/languages';qa.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1100})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        def api(route):
            path=route.request.url.split('/api/')[1]
            data={'jobs':[]} if path=='jobs' else {'item':None} if path=='audio-imports/current' else {}
            route.fulfill(json=data)
        page.route('**/api/**',api)
        page.goto(f'http://127.0.0.1:{server.server_port}')
        page.wait_for_function("document.querySelector('#connection-text').textContent==='本機已連線'")
        page.locator('#title').fill('我的音樂 — 請勿翻譯')
        page.locator('#version').fill('Custom difficulty')
        page.locator('#stars').fill('3.5')
        page.locator('[data-tech=jack]').click()
        original=page.evaluate('settings()')
        page.locator('#language-toggle').click()
        page.screenshot(path=str(qa/'menu-zh.png'))
        page.locator('[data-language=en]').click()
        assert page.locator('html').get_attribute('lang')=='en'
        assert page.locator('.technique-heading h3').inner_text()=='Dan preferences Select multiple'
        assert page.locator('#connection-text').inner_text()=='Connected'
        assert page.locator('#title').input_value()==original['metadata']['title']
        assert page.evaluate('settings()')==original
        assert page.locator('#title').get_attribute('placeholder')=='Leave blank to use the audio title'
        assert page.locator('#history-list').inner_text().find('Your first beatmap')>=0
        assert page.evaluate("t('檔案大小不可超過 20 MB。')")=='File size must not exceed 20 MB.'
        page.evaluate("toast('請使用有效的 YouTube 影片網址。')")
        assert page.locator('#toast').inner_text()=='Enter a valid YouTube video URL.'
        page.evaluate("document.querySelector('#toast').hidden=true")
        # Completed results and user-provided metadata survive changing languages.
        page.evaluate("""displayJob({id:'fixture',status:'completed',stage:'completed',created_at:new Date().toISOString(),result:{actual_stars:3.48,target_stars:3.5,taps:123,holds:45,video_file:'video.mp4'}})""")
        assert 'Actual 3.48' in page.locator('#job-description').inner_text()
        assert '123 taps' in page.locator('#job-description').inner_text()
        assert page.locator('#download-osz').inner_text().startswith('Download .osz with video')
        page.evaluate("importStatus({id:'import-fixture',status:'running',stage:'video_packaging'})")
        assert page.locator('#youtube-status').inner_text()=='Packaging MP4 without re-encoding…'
        page.evaluate("importStatus({id:'import-fixture',status:'failed',stage:'failed',error:'請使用有效的 YouTube 影片網址。'})")
        assert page.locator('#youtube-error').inner_text()=='Enter a valid YouTube video URL.'
        page.locator('#language-toggle').click();page.screenshot(path=str(qa/'menu-en.png'))
        page.keyboard.press('Escape')
        assert page.locator('#language-menu').is_hidden()
        assert page.locator('#language-toggle').evaluate('(el)=>el===document.activeElement')
        page.locator('#language-toggle').press('ArrowDown');page.keyboard.press('Home');page.keyboard.press('Enter')
        assert page.locator('html').get_attribute('lang')=='zh-Hant-TW'
        assert '實際 3.48' in page.locator('#job-description').inner_text()
        assert page.locator('#youtube-status').inner_text()=='下載未完成'
        assert page.evaluate('settings()')==original
        page.locator('#language-toggle').click();page.locator('[data-language=en]').click()
        page.reload();page.wait_for_function("document.querySelector('#connection-text').textContent==='Connected'")
        assert page.evaluate('settings()')==original
        assert page.locator('#version').input_value()=='Custom difficulty'
        # No Chinese UI remains in English, excluding native language names and user text.
        leftover=page.evaluate("""()=>{const out=[],w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);while(w.nextNode()){const n=w.currentNode;if(n.parentElement.closest('[data-language-menu]'))continue;if(/[\\u4e00-\\u9fff]/.test(n.textContent)&&n.parentElement.checkVisibility()&&n.parentElement.id!=='preview-title')out.push(n.textContent)}return out}""")
        assert not leftover,leftover
        for width in [390,320]:
            page.set_viewport_size({'width':width,'height':844})
            page.locator('#language-toggle').click()
            overflow=page.evaluate("[...document.querySelectorAll('body *')].filter(e=>e.checkVisibility()&&e.getBoundingClientRect().right>innerWidth+1).map(e=>({tag:e.tagName,id:e.id,cls:e.className,right:e.getBoundingClientRect().right}))")
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,overflow)
            box=page.locator('#language-menu').bounding_box();assert box['x']>=0 and box['x']+box['width']<=width
            page.screenshot(path=str(qa/f'mobile-{width}.png'))
            page.locator('#language-toggle').click()
        assert not errors,errors
        browser.close()
    server.shutdown()
    print(json.dumps({'language_switch':'passed','persistence':'passed','mobile_widths':[390,320],'browser_errors':errors}))

if __name__=='__main__':main()
