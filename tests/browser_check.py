"""Local browser QA and a real model generation, with user audio as a fixture."""
from pathlib import Path
import json
import sys
from PIL import Image
from playwright.sync_api import sync_playwright

APP=Path(__file__).resolve().parents[1]
QA=APP/'workspace/qa'
QA.mkdir(exist_ok=True)

def main():
    audio=next(APP.parent.glob('*DEMON*mp3'))
    image=Image.new('RGB',(960,540))
    image.putdata([(int(40+60*x/960),int(25+35*y/540),int(70+50*x/960)) for y in range(540) for x in range(960)])
    image.save(QA/'cover.png')
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
        context=browser.new_context(viewport={'width':1440,'height':1100},device_scale_factor=1)
        page=context.new_page();errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://localhost:8765');page.wait_for_function("document.querySelector('#connection-text').textContent.includes('已連線')")
        page.screenshot(path=str(QA/'desktop-empty.png'),full_page=True)
        page.locator('#audio-file').set_input_files(str(audio))
        page.locator('#audio-loaded').wait_for(state='visible',timeout=30000)
        page.locator('#background-file').set_input_files(str(QA/'cover.png'))
        page.locator('#background-loaded').wait_for(state='visible')
        page.locator('#title').fill('DEMON’S SHOT · 介面測試')
        page.locator('#title-romanized').fill("DEMON'S SHOT")
        page.locator('#artist').fill('Aiobahn +81 feat. DEMONDICE')
        page.locator('#creator').fill('Mania Studio')
        page.locator('#source').fill('')
        page.locator('#tags').fill('')
        page.locator('[data-tech="jack"]').click()
        assert not page.evaluate('() => settings().reduce_jacks')
        page.locator('[data-tech="jack"]').click()
        assert page.locator('[data-tech="jack"]').get_attribute('aria-pressed')=='false'
        page.locator('input[name="keys"][value="7"]').check(force=True)
        assert page.locator('#preview-key').inner_text()=='7K'
        page.locator('input[name="keys"][value="4"]').check(force=True)
        page.screenshot(path=str(QA/'desktop-filled.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(QA/'mobile-filled.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.set_viewport_size({'width':1440,'height':1100})
        with page.expect_response(lambda response:response.url.endswith('/api/jobs') and response.request.method=='POST') as pending:
            page.locator('#generate-button').click()
        response=pending.value
        assert response.status==202,response.text()
        job=response.json()
        (QA/'browser-job.json').write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding='utf-8')
        assert not errors,errors
        print(json.dumps({'job_id':job['id'],'browser_errors':errors,'screenshots':str(QA)}),flush=True)
        browser.close()

if __name__=='__main__':main()
