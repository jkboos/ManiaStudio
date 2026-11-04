'use strict';
// UI copy only. Song metadata and filenames are never translated.
window.I18N = (() => {
  const en = {
    'Mania Studio · 本機譜面工作台':'Mania Studio · Local beatmap workspace',
    'Mania Studio 首頁':'Mania Studio home','主要導覽':'Main navigation',
    '建立譜面':'Create beatmap','生成紀錄':'History','連線中':'Connecting',
    '本機已連線':'Connected','連線失敗':'Connection failed',
    '音檔與背景':'Audio & background','從 YouTube 加入音樂':'Add music from YouTube',
    '或使用下方音檔上傳':'or upload audio below','貼上 YouTube 或 youtu.be 影片網址':'Paste a YouTube or youtu.be video URL',
    '下載含影片':'Download with video','下載不含影片':'Download without video','下載':'Download',
    '含影片':'with video','不含影片':'without video','取消下載':'Cancel download','音訊下載進度':'Audio download progress',
    '上傳音檔':'Upload audio','拖曳音樂到這裡':'Drop your music here','或':'or','選擇音檔':'Choose audio',
    'MP3 · WAV · OGG · FLAC，最高 200 MB':'MP3 · WAV · OGG · FLAC, up to 200 MB',
    '移除音檔':'Remove audio','試聽上傳音檔':'Preview uploaded audio','更換音檔':'Replace audio','正在讀取音檔…':'Reading audio…',
    '上傳背景圖':'Upload background image','加上背景圖片':'Add a background image','選填':'Optional',
    '拖曳圖片或':'Drop an image or','選擇圖片':'Choose image','JPG · PNG · WebP，最高 20 MB':'JPG · PNG · WebP, up to 20 MB',
    '上傳的背景預覽':'Uploaded background preview','移除背景圖片':'Remove background image','更換背景':'Replace background',
    '正在讀取圖片…':'Reading image…','上傳背景影片':'Upload background video','背景影片':'Background video',
    '上傳影片':'Upload video','更換影片':'Replace video',
    '拖曳影片到這裡，或上傳本機影片。MP4 · MKV · WebM · AVI · MOV，最高 2 GB。':'Drop a video here or upload a local file. MP4 · MKV · WebM · AVI · MOV, up to 2 GB.',
    '請先加入音樂；影片會移除音軌，從歌曲開頭播放，背景圖片仍需保留。':'Add audio first. Video plays from the start with its audio removed. A background image is still required.',
    '背景影片預覽':'Background video preview','背景影片已加入':'Background video added','另開預覽':'Open preview','移除影片':'Remove video',
    '正在上傳與處理影片，保留原解析度並移除音軌…':'Uploading and preparing video, preserving resolution and removing audio…',
    '譜面資訊':'Beatmap information','顯示在 osu! 歌曲選單中；留白時使用音檔資訊或預設值。':'Shown in the osu! song menu. Leave blank to use audio metadata or defaults.',
    '歌曲標題':'Title','留白時使用音檔標題':'Leave blank to use the audio title','演出者':'Artist','留白時使用 Unknown':'Leave blank to use Unknown',
    '羅馬拼音標題':'Romanised title','與原文相同可留白':'Leave blank if the same as the original','羅馬拼音演出者':'Romanised artist',
    '製譜者':'Beatmap creator','留白時使用 ManiaModel':'Leave blank to use ManiaModel','難度名稱':'Difficulty name',
    '留白時依按鍵數與星數命名':'Leave blank to name by key count and stars','遊戲中的名稱，與下方的目標星數分開設定。':'The in-game name, separate from the target star rating below.',
    '作品來源':'Source','動畫、遊戲或專輯名稱':'Anime, game or album name','搜尋標籤':'Tags','以空格分隔，例如 vocal original':'Separate with spaces, e.g. vocal original',
    '難度設定':'Difficulty settings','決定鍵數、段位組合與目標難度。':'Choose keys, Dan preferences and target difficulty.',
    '按鍵數':'Key count','段位偏好':'Dan preferences','可複選':'Select multiple','重設偏好':'Clear preferences',
    '目標星數':'Target stars','調整目標星數':'Adjust target stars','以此星數為目標，實際生成結果可能略有差異。':'The generated star rating may differ slightly from this target.',
    '譜面預覽':'Beatmap preview','譜面背景預覽':'Beatmap background preview','你的下一首歌':'Your next song','你的下一首音樂':'Your next song',
    '目標難度':'Target difficulty','音樂長度':'Audio length','背景圖片':'Background image','未選擇':'Not selected',
    '已加入':'Added','未選擇（選填）':'None (optional)','生成譜面':'Generate beatmap','正在生成':'Generating','正在生成…':'Generating…',
    '先上傳音檔，即可開始生成。':'Upload audio to start generating.','取消生成':'Cancel generation',
    '下載 .osz 譜面包':'Download .osz package','下載含影片 .osz 譜面包':'Download .osz with video',
    '單獨下載 .osu':'Download .osu only','錯誤詳情':'Error details','清除紀錄與檔案':'Clear history & files',
    '第一張譜面，從這裡開始。':'Your first beatmap starts here.','完成後可以在這裡重新下載。':'Completed beatmaps will be available here.',
    '實際編排與難度，請以試玩感受為準。':'Playtest to judge the patterns and difficulty.',
    '下載完成後即可生成。':'You can generate once the download finishes.',
    '完成後可下載包含音樂與背景的 .osz。':'Download an .osz with audio and background when ready.',
    '含影片仍需背景圖片，請加入背景圖。':'Video beatmaps still need a background image. Please add one.',
    '輸出包含音樂、背景圖與影片的 .osz。':'Export an .osz with audio, background image and video.',
    '輸出 .osz 譜面包與 .osu 檔案。':'Export an .osz package and an .osu file.',
    '上傳音檔或貼上 YouTube 網址加入音樂。':'Upload audio or paste a YouTube URL to add music.',
    '請先加入音樂，再上傳對應的背景影片。':'Add audio before uploading its background video.',
    '背景影片上限為 2 GB。':'Background video must be 2 GB or smaller.',
    '請先貼上 YouTube 影片網址。':'Paste a YouTube video URL first.',
    '正在取得影片資訊…':'Fetching video information…','正在下載音訊…':'Downloading audio…',
    '正在轉換成 MP3…':'Converting to MP3…','正在檢查音檔…':'Checking audio…','正在下載影片封面…':'Downloading cover image…',
    '正在下載高畫質無音訊影片…':'Downloading high-quality silent video…','正在封裝 MP4，不重新編碼…':'Packaging MP4 without re-encoding…',
    '來源影片需轉成相容格式，正在轉檔…':'Converting video to a compatible format…','音樂、背景圖片與影片已加入。':'Audio, background image and video added.',
    '音訊已加入，可以試聽或生成譜面。':'Audio added. Preview it or generate a beatmap.','下載未完成':'Download failed',
    '已取消下載，原本的音檔保留。':'Download cancelled. Your previous audio is kept.','正在重新連線以確認下載狀態…':'Reconnecting to check download status…',
    '等待生成':'Queued','已加入本機佇列。':'Added to the local queue.','載入模型':'Loading model','正在準備固定版本的模型。':'Preparing the model.',
    '分析音樂':'Analyzing audio','讀取音樂節奏與特徵，長音檔需要較多時間。':'Reading rhythm and audio features. Longer songs take more time.',
    '編排音符':'Arranging notes','依按鍵數、星數與段位偏好生成譜面。':'Generating a beatmap using your keys, stars and Dan preferences.',
    '檢查譜面':'Checking beatmap','檢查音符與長條，計算實際星數。':'Checking notes and holds, and calculating the star rating.',
    '打包結果':'Packaging results','寫入譜面資料、音樂與背景圖。':'Writing beatmap metadata, audio and background.',
    '譜面已完成':'Beatmap ready','生成未完成':'Generation failed','已取消':'Cancelled','可以調整設定後重新生成。':'Adjust your settings and generate again.',
    '仍有生成或下載作業，請完成或取消後再清除。':'Wait for generation or downloads to finish, or cancel them before clearing.',
    '目前沒有需要清除的紀錄或檔案。':'There is no history or files to clear.','未指定段位偏好':'No Dan preferences',
    '下載 .osz':'Download .osz','查看結果':'View result','目前仍在生成，請完成後再查看其他結果。':'Wait for the current generation to finish before viewing other results.',
    '請求未完成，請再試一次。':'The request failed. Please try again.',
    '請提供有效的生成設定。':'Please provide valid generation settings.','請先上傳音檔與有效的背景圖片。':'Upload audio and a valid background image first.',
    '按鍵數必須是 4K 或 7K。':'Key count must be 4K or 7K.','目標星數請輸入 0.5 到 15 之間的數值。':'Target stars must be between 0.5 and 15.',
    '有無法辨識的段位偏好選項。':'An unrecognized Dan preference was selected.','譜面資訊格式不正確。':'Invalid beatmap metadata format.',
    '譜面資訊不可包含換行或控制字元，內容也不可過長。':'Metadata must not contain line breaks or control characters, or exceed the length limit.',
    '請貼上 YouTube 單支影片的網址。':'Paste a URL for a single YouTube video.','請使用有效的 YouTube 影片網址。':'Enter a valid YouTube video URL.',
    '請貼上單支 YouTube 影片網址，不支援播放清單或頻道網址。':'Paste a single YouTube video URL. Playlists and channels are not supported.',
    '下載因服務重啟而中斷，請重新下載。':'The download was interrupted by a restart. Please download again.',
    '影片下載選項格式不正確。':'Invalid video download option.','已有音訊正在下載，請完成或取消後再加入。':'Another download is running. Wait or cancel it before adding more audio.',
    '無法完成下載，請稍後再試或改用音檔上傳。':'Download failed. Try again later or upload audio instead.',
    '找不到上傳檔案，請重新上傳。':'Uploaded file not found. Please upload it again.','上傳檔案類型不符。':'The uploaded file type does not match.',
    '找不到上傳檔案。':'Uploaded file not found.','不支援的上傳類型。':'Unsupported upload type.',
    '音檔支援 MP3、WAV、OGG、FLAC；圖片支援 JPG、PNG、WebP。':'Supported audio: MP3, WAV, OGG, FLAC. Supported images: JPG, PNG, WebP.',
    '音檔上限為 200 MB，背景圖上限為 20 MB。':'Audio must be up to 200 MB; background images up to 20 MB.','檔案是空的。':'The file is empty.',
    '無法讀取音檔，請確認檔案有效且至少有 1 秒音訊。':'Cannot read audio. Use a valid file with at least one second of audio.',
    '無法讀取圖片，請使用有效的 JPG、PNG 或 WebP（最多 4,000 萬像素）。':'Cannot read image. Use a valid JPG, PNG or WebP (up to 40 megapixels).',
    '僅接受 localhost 的連線。':'Only localhost connections are accepted.','請從本機介面送出請求。':'Send requests from the local interface.',
    '找不到這個生成項目。':'Generation not found.','檔案過大，音檔上限為 200 MB，背景圖上限為 20 MB，影片上限為 2 GB。':'File too large. Limits: audio 200 MB, image 20 MB, video 2 GB.',
    '處理請求時發生錯誤，請再試一次。':'An error occurred. Please try again.','請選擇檔案。':'Please choose a file.',
    '請貼上 YouTube 影片網址。':'Paste a YouTube video URL.','譜面尚未完成。':'The beatmap is not ready yet.',
    '檔案不含可播放的影片軌。':'The file has no playable video track.','影片支援 MP4、MKV、WebM、AVI、MOV。':'Supported video formats: MP4, MKV, WebM, AVI and MOV.',
    '影片檔案是空的。':'The video file is empty.','無法讀取或轉換影片，請確認檔案有效。':'Cannot read or convert video. Check that the file is valid.',
    '背景影片必須只有一個視訊軌且沒有音軌。':'Background video must have one video track and no audio track.',
    '無法讀取相容的背景影片。':'Cannot read a compatible background video.','背景影片檔案為空或超過 2 GB。':'The background video is empty or exceeds 2 GB.',
    '上次服務已中斷，請重新生成。':'The previous session was interrupted. Please generate again.',
    '背景影片與目前音檔不是同一次下載，請重新選擇含影片下載。':'The video does not belong to this audio. Download again with video included.',
    '含影片的譜面仍需背景圖片，請保留封面或上傳背景圖。':'Video beatmaps still need an image. Keep the cover or upload a background image.',
    '佇列目前已滿，請等候正在生成的譜面完成。':'The queue is full. Wait for the current beatmap to finish.',
    '生成程式未能完成，請查看錯誤詳情後再試。':'Generation failed. Check the error details before trying again.',
    '資料目錄指向其他位置，已停止清除。':'Cleanup stopped because the data directory points elsewhere.',
    '仍有生成或下載作業，請等候完成或取消後再清除。':'Wait for generation or downloads to finish, or cancel them before clearing.',
    '發現目錄外的檔案連結，已停止清除。':'Cleanup stopped because a file link points outside the data directory.',
    '含影片的譜面仍需背景圖片。':'Video beatmaps still need a background image.',
    '音訊已下載，但無法取得影片封面；可以自行上傳背景圖。':'Audio downloaded, but the cover could not be retrieved. You can upload a background image.',
    '背景影片超過 2 GB，已停止下載。':'Download stopped: background video exceeds 2 GB.',
    '不支援直播中或尚未開始的影片。':'Live and upcoming videos are not supported.',
    '無法取得純影片串流。':'Cannot retrieve a video-only stream.',
    '未取得影片檔案，可能超過 2 GB 或來源無法存取。':'No video was retrieved. It may exceed 2 GB or be inaccessible.',
    '來源不是純影片串流。':'The source is not a video-only stream.',
    '音訊超過 200 MB，已停止下載。':'Download stopped: audio exceeds 200 MB.',
    '請使用已發布的影片；不支援直播中或尚未開始的影片。':'Use a published video. Live and upcoming videos are not supported.',
    '未取得可用的音訊，影片可能無法存取或檔案超過 200 MB。':'No usable audio was retrieved. The video may be inaccessible or the file may exceed 200 MB.',
    '無法取得 YouTube 封面，已使用影片畫面作為背景圖片。':'The YouTube cover could not be retrieved. A video frame is used as the background image.'
  };
  // Dynamic messages keep values separate from translated wording.
  const templates = [
    ['缺少 {0}，請確認 bin 資料夾完整。','Missing {0}. Check that the bin folder is complete.'],
    ['下載未完成。影片可能無法存取、需要登入，或連線暫時失敗。可重試或改用音檔上傳。\n{0}','Download failed. The video may be inaccessible, require login, or have a temporary connection issue. Retry or upload audio instead.\n{0}'],
    ['檔案大小不可超過 {0} MB。','File size must not exceed {0} MB.'],
    ['{0} × {1} · {2} · {3} MB · 無音訊','{0} × {1} · {2} · {3} MB · No audio'],
    ['實際 {0} ★ / 目標 {1} ★\n{2} 個單鍵 · {3} 個 LN\n實際編排與難度仍以試玩感受為準。','Actual {0} ★ / Target {1} ★\n{2} taps · {3} LN\nPlaytest to judge the patterns and difficulty.'],
    ['清除 {0} 筆生成紀錄、{1} 筆下載紀錄及 {2} 份音樂／背景資產？\n\n會永久刪除程式內的譜面、音樂、圖片、影片與暫存檔，約可釋放 {3}，目前選取的音樂與背景也會清空。\n\n不包含瀏覽器另存的檔案或已匯入 osu! 的譜面。','Clear {0} generations, {1} downloads and {2} audio/background assets?\n\nThis permanently deletes the app’s beatmaps, audio, images, videos and temporary files, freeing about {3}. Your selected audio and background will also be cleared.\n\nFiles saved by your browser or already imported into osu! are not affected.'],
    ['已清除紀錄與檔案，釋放約 {0}。','History and files cleared, freeing about {0}.']
  ].map(([source,target]) => [new RegExp('^'+source.split(/\{\d+\}/).map(s=>s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('([\\s\\S]*?)')+'$'),target]);
  let language = 'zh-TW';
  try { if(localStorage.getItem('mania-studio-language')==='en') language='en'; } catch {}
  function t(value) {
    if(language!=='en'||typeof value!=='string')return value;
    const key=value.trim();
    if(Object.hasOwn(en,key))return value.replace(key,en[key]);
    for(const [pattern,target] of templates){const match=pattern.exec(value);if(match)return target.replace(/\{(\d+)\}/g,(_,i)=>match[Number(i)+1]);}
    return value;
  }
  const bindings=[];
  // Capture static UI once, before the app writes any user data into the DOM.
  const walker=document.createTreeWalker(document.documentElement,NodeFilter.SHOW_TEXT);
  while(walker.nextNode()){
    const node=walker.currentNode;
    if(node.parentElement.closest('script,style,[data-language-menu]'))continue;
    if(Object.hasOwn(en,node.textContent.trim()))bindings.push(()=>{node.textContent=t(node._source);});
    node._source=node.textContent;
  }
  document.querySelectorAll('[placeholder],[aria-label],[alt]').forEach(el=>{
    for(const attr of ['placeholder','aria-label','alt']){const source=el.getAttribute(attr);if(source&&Object.hasOwn(en,source))bindings.push(()=>el.setAttribute(attr,t(source)));}
  });
  const trigger=document.getElementById('language-toggle'),menu=document.getElementById('language-menu');
  const options=[...menu.querySelectorAll('[data-language]')];
  function close(focus=false){menu.hidden=true;trigger.setAttribute('aria-expanded','false');if(focus)trigger.focus();}
  function apply(){
    document.documentElement.lang=language==='en'?'en':'zh-Hant-TW';
    bindings.forEach(update=>update());
    document.getElementById('language-name').textContent=language==='en'?'English':'繁體中文（台灣）';
    document.getElementById('language-flag').src='/assets/flags/'+(language==='en'?'gb':'tw')+'.svg';
    trigger.setAttribute('aria-label',language==='en'?'Language: English':'語言：繁體中文（台灣）');
    menu.setAttribute('aria-label',language==='en'?'Choose language':'選擇語言');
    options.forEach(option=>option.setAttribute('aria-checked',String(option.dataset.language===language)));
  }
  function setLanguage(value){
    if(!['zh-TW','en'].includes(value))return;
    language=value;try{localStorage.setItem('mania-studio-language',value);}catch{}
    apply();close(true);window.dispatchEvent(new Event('studio-language-change'));
  }
  function open(){menu.hidden=false;trigger.setAttribute('aria-expanded','true');options.find(o=>o.dataset.language===language).focus();}
  trigger.addEventListener('click',()=>menu.hidden?open():close());
  trigger.addEventListener('keydown',event=>{if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();open();}});
  options.forEach(option=>option.addEventListener('click',()=>setLanguage(option.dataset.language)));
  menu.addEventListener('keydown',event=>{
    const index=options.indexOf(document.activeElement);
    if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();options[event.key==='Home'?0:event.key==='End'?options.length-1:(index+(event.key==='ArrowDown'?1:options.length-1))%options.length].focus();}
  });
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!menu.hidden){event.preventDefault();close(true);}});
  document.addEventListener('click',event=>{if(!event.target.closest('[data-language-menu]'))close();});
  document.addEventListener('focusin',event=>{if(!event.target.closest('[data-language-menu]'))close();});
  apply();
  return {t,get language(){return language;},setLanguage};
})();
