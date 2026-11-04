'use strict';
const $ = id => document.getElementById(id);
const form = $('map-form');
const chips = [...document.querySelectorAll('[data-tech]')];
const state = {audio:null, background:null, video:null, videoBusy:false, job:null, busy:0, versionEdited:false, online:false, importing:false, importId:null, appliedImportId:null, clearing:false};
const active = job => job && ['queued','running'].includes(job.status);
const duration = seconds => `${Math.floor(seconds/60)}:${String(Math.floor(seconds%60)).padStart(2,'0')}`;
let toastTimer, pollTimer, importTimer, historyEpoch=0;
function toast(message) { $('toast').textContent=message; $('toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').hidden=true,6500); }
async function api(url, options={}) {
  const response=await fetch(url, options);
  const data=await response.json();
  if (!response.ok) throw new Error(data.error || '請求未完成，請再試一次。');
  return data;
}
function settings() {
  return {audio_id:state.audio?.id,background_id:state.background?.id||null,video_id:state.video?.id||null,
    keys:Number(form.elements.keys.value),stars:Number($('stars').value),
    techniques:chips.filter(c=>c.getAttribute('aria-pressed')==='true').map(c=>c.dataset.tech),
    reduce_jacks:!chips.some(c=>c.dataset.tech==='jack'&&c.getAttribute('aria-pressed')==='true'),
    metadata:Object.fromEntries(['title','artist','title_romanized','artist_romanized','creator','version','source','tags'].map(key=>[key,form.elements[key].value.trim()]))};
}
function saveDraft() { try {localStorage.setItem('mania-studio-draft',JSON.stringify({...settings(),versionEdited:state.versionEdited}));} catch {} }
function render() {
  const s=settings();
  if(!state.versionEdited) $('version').value=`${s.keys}K - ${Number.isFinite(s.stars)?s.stars.toFixed(1):'4.0'} stars`;
  $('preview-title').textContent=s.metadata.title||'你的下一首音樂';
  $('preview-artist').textContent=s.metadata.artist||'Unknown';
  $('preview-creator').textContent=s.metadata.creator||'ManiaModel';
  $('preview-version').textContent=$('version').value||`${s.keys}K`;
  $('preview-key').textContent=`${s.keys}K`;
  $('preview-stars').textContent=`★ ${s.stars.toFixed(1)}`;
  $('summary-difficulty').textContent=`${s.keys}K · ${s.stars.toFixed(1)} ★`;
  $('summary-duration').textContent=state.audio?duration(state.audio.duration_s):'—';
  $('summary-background').textContent=state.background?'已加入':'未選擇（選填）';
  $('preview-image').hidden=!state.background;
  $('default-art').hidden=!!state.background;
  if(state.background) $('preview-image').src=state.background.url;
  $('preview-tags').replaceChildren(...s.techniques.map(t=>{const tag=document.createElement('span');tag.className='preview-tag';tag.style.setProperty('--color',`var(--${t.toLowerCase()})`);tag.textContent=t==='tech'?'Tech':t==='LN'?'LN':t[0].toUpperCase()+t.slice(1);return tag;}));
  $('generate-button').disabled=!state.audio||state.busy>0||state.importing||active(state.job)||!state.online||!!(state.video&&!state.background);
  $('youtube-download').disabled=!state.online||state.importing||state.clearing||state.videoBusy||!$('audio-busy').hidden;
  $('youtube-download-video').disabled=$('youtube-download').disabled;
  $('youtube-url').disabled=state.importing;
  $('video-attachment').hidden=!state.video;
  $('video-loaded').hidden=!state.video;$('video-empty').hidden=!!state.video;
  $('video-busy').hidden=!state.videoBusy;
  $('remove-video').disabled=state.importing||state.clearing||state.videoBusy;
  for(const id of ['choose-video','video-file'])$(id).disabled=!state.audio||!state.online||state.importing||state.clearing||state.videoBusy||!$('audio-busy').hidden;
  $('choose-video').textContent=state.video?'更換影片':'上傳影片';
  if(state.video){
    $('video-name').textContent=state.video.original_name;
    $('video-detail').textContent=`${state.video.width} × ${state.video.height} · ${duration(state.video.duration_s)} · ${(state.video.bytes/1048576).toFixed(1)} MB · 無音訊`;
    $('video-preview').href=state.video.url;
    if($('video-player').getAttribute('src')!==state.video.url)$('video-player').src=state.video.url;
    if(state.background)$('video-player').poster=state.background.url;else $('video-player').removeAttribute('poster');
  }else if($('video-player').getAttribute('src')){
    $('video-player').pause();$('video-player').removeAttribute('src');$('video-player').removeAttribute('poster');$('video-player').load();
  }
  $('clear-history').disabled=!state.online||state.busy>0||state.importing||active(state.job);
  for(const id of ['audio-file','choose-audio','replace-audio','remove-audio']) $(id).disabled=state.importing||state.clearing||state.videoBusy;
  for(const id of ['background-file','choose-background','replace-background','remove-background'])$(id).disabled=state.clearing;
  $('audio-zone').classList.toggle('importing',state.importing);
  $('generate-label').textContent=active(state.job)?'正在生成…':'生成譜面';
  $('generate-help').textContent=state.importing?'下載完成後即可生成。':active(state.job)?'完成後可下載包含音樂與背景的 .osz。':state.video&&!state.background?'含影片仍需背景圖片，請加入背景圖。':state.video?'輸出包含音樂、背景圖與影片的 .osz。':state.audio?'輸出 .osz 譜面包與 .osu 檔案。':'上傳音檔或貼上 YouTube 網址加入音樂。';
  saveDraft();
}
function showAsset(kind, asset) {
  state[kind]=asset;
  $(`${kind}-empty`).hidden=!!asset; $(`${kind}-loaded`).hidden=!asset;
  if(kind==='audio') {
    if(state.video?.audio_id!==asset?.id)state.video=null;
    if(asset) { $('audio-name').textContent=asset.original_name;$('audio-detail').textContent=`${duration(asset.duration_s)} · ${(asset.bytes/1048576).toFixed(1)} MB`;$('audio-player').src=asset.url; }
    else {$('audio-player').pause();$('audio-player').removeAttribute('src');$('audio-player').load();}
  } else if(asset) {$('background-thumb').src=asset.url;$('background-detail').textContent=`${asset.width} × ${asset.height}`;}
  render();
}
async function upload(kind,file) {
  if(!file || state.clearing || !$(`${kind}-busy`).hidden || (kind==='audio' && (state.importing||state.videoBusy))) return;
  const limit=kind==='audio'?200:20;
  if(file.size>limit*1048576) return toast(`檔案大小不可超過 ${limit} MB。`);
  state.busy++;$(`${kind}-busy`).hidden=false;render();
  try {
    const body=new FormData();body.append('kind',kind);body.append('file',file);
    const asset=await api('/api/uploads',{method:'POST',body});
    if(kind==='audio') fillAudioMetadata(asset);
    showAsset(kind,asset);
  } catch(error) {toast(error.message);} finally {state.busy--;$(`${kind}-busy`).hidden=true;render();}
}
async function uploadVideo(file){
  if(!file||state.importing||state.videoBusy||state.clearing)return;
  if(!state.audio)return toast('請先加入音樂，再上傳對應的背景影片。');
  if(!$('audio-busy').hidden)return;
  if(file.size>2048*1048576)return toast('背景影片上限為 2 GB。');
  state.videoBusy=true;state.busy++;render();
  try{
    const body=new FormData();body.append('kind','video');body.append('audio_id',state.audio.id);body.append('file',file);
    state.video=await api('/api/uploads',{method:'POST',body});
  }catch(error){toast(error.message);}finally{state.videoBusy=false;state.busy--;render();}
}
$('choose-video').onclick=()=>$('video-file').click();
$('video-file').onchange=event=>{uploadVideo(event.target.files[0]);event.target.value='';};
$('video-zone').ondragover=event=>{event.preventDefault();$('video-zone').classList.add('dragover');};
$('video-zone').ondragleave=()=>$('video-zone').classList.remove('dragover');
$('video-zone').ondrop=event=>{event.preventDefault();$('video-zone').classList.remove('dragover');uploadVideo(event.dataTransfer.files[0]);};
function fillAudioMetadata(asset, replaceSong=false) {
  if(replaceSong || !$('title').value || $('title').value===state.audio?.title) $('title').value=asset.title;
  if(replaceSong || !$('artist').value || $('artist').value==='Unknown' || $('artist').value===state.audio?.artist) $('artist').value=asset.artist||'Unknown';
  if(replaceSong)for(const name of ['title_romanized','artist_romanized','source','tags'])form.elements[name].value='';
}
function rememberImport(id) {try{if(id)localStorage.setItem('mania-studio-import',id);else localStorage.removeItem('mania-studio-import');}catch{}}
function importStatus(item) {
  state.importId=item.id;state.importing=active(item);
  $('youtube-feedback').hidden=false;$('youtube-feedback').classList.toggle('failed',item.status==='failed');
  $('youtube-cancel').hidden=!state.importing;
  const labels={fetching:'正在取得影片資訊…',downloading:'正在下載音訊…',converting:'正在轉換成 MP3…',registering:'正在檢查音檔…',background:'正在下載影片封面…',video_downloading:'正在下載高畫質無音訊影片…',video_packaging:'正在封裝 MP4，不重新編碼…',video_converting:'來源影片需轉成相容格式，正在轉檔…',completed:item.video?'音樂、背景圖片與影片已加入。':'音訊已加入，可以試聽或生成譜面。',failed:'下載未完成',cancelled:'已取消下載，原本的音檔保留。'};
  const hasProgress=['downloading','video_downloading'].includes(item.stage)&&Number.isFinite(item.progress);
  $('youtube-status').textContent=(labels[item.stage]||labels.fetching)+(hasProgress?` ${item.progress.toFixed(0)}%`:'');
  $('youtube-error').hidden=!(item.error||item.warning);$('youtube-error').textContent=item.error||item.warning||'';
  $('youtube-progress').hidden=!state.importing;
  if(hasProgress)$('youtube-progress').value=item.progress;else $('youtube-progress').removeAttribute('value');
  if(item.status==='completed'&&item.asset&&state.appliedImportId!==item.id){
    state.appliedImportId=item.id;
    fillAudioMetadata(item.asset,true);showAsset('audio',item.asset);
    if(item.background&&(!state.background||state.background.source_url))showAsset('background',item.background);
    else if(!item.background&&state.background?.source_url)showAsset('background',null);
    state.video=item.video||null;
  }
  if(!state.importing)rememberImport(null);
  render();
}
async function watchImport(id) {
  clearTimeout(importTimer);
  const epoch=historyEpoch;
  try {
    const item=await api(`/api/audio-imports/${id}`);if(epoch!==historyEpoch)return;importStatus(item);
    if(active(item))importTimer=setTimeout(()=>watchImport(id),800);
  } catch(error) {
    if(epoch!==historyEpoch)return;
    $('youtube-feedback').hidden=false;$('youtube-status').textContent='正在重新連線以確認下載狀態…';
    importTimer=setTimeout(()=>watchImport(id),3000);
  }
}
async function startImport(includeVideo){
  if(state.importing || state.videoBusy || !$('audio-busy').hidden)return;
  const url=$('youtube-url').value.trim();
  if(!url){$('youtube-url').focus();return toast('請先貼上 YouTube 影片網址。');}
  state.importing=true;state.appliedImportId=null;render();
  try {
    const item=await api('/api/audio-imports',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url,include_video:includeVideo})});
    rememberImport(item.id);importStatus(item);watchImport(item.id);
  } catch(error){state.importing=false;toast(error.message);render();}
}
$('youtube-download').onclick=()=>startImport(false);
$('youtube-download-video').onclick=()=>startImport(true);
$('remove-video').onclick=()=>{state.video=null;render();};
$('youtube-url').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();$('youtube-download').click();}};
$('youtube-cancel').onclick=async()=>{
  if(!state.importId)return;
  try {clearTimeout(importTimer);importStatus(await api(`/api/audio-imports/${state.importId}/cancel`,{method:'POST'}));}
  catch(error){toast(error.message);watchImport(state.importId);}
};
for(const kind of ['audio','background']) {
  for(const action of ['choose','replace']) $(`${action}-${kind}`).onclick=()=>$(`${kind}-file`).click();
  $(`${kind}-file`).onchange=event=>{upload(kind,event.target.files[0]);event.target.value='';};
  $(`remove-${kind}`).onclick=()=>showAsset(kind,null);
  const zone=$(`${kind}-zone`);
  zone.ondragover=event=>{event.preventDefault();zone.classList.add('dragover');};
  zone.ondragleave=()=>zone.classList.remove('dragover');
  zone.ondrop=event=>{event.preventDefault();zone.classList.remove('dragover');upload(kind,event.dataTransfer.files[0]);};
}
for(const chip of chips) chip.onclick=()=>{
  const on=chip.getAttribute('aria-pressed')!=='true';chip.setAttribute('aria-pressed',String(on));
  render();
};
$('reset-techniques').onclick=()=>{chips.forEach(c=>c.setAttribute('aria-pressed','false'));render();};
$('version').oninput=()=>state.versionEdited=true;
$('stars').oninput=()=>{if($('stars').validity.valid) $('stars-range').value=$('stars').value;};
$('stars-range').oninput=()=>{$('stars').value=$('stars-range').value;render();};
form.addEventListener('input',render);
const stageText={queued:['等待生成','已加入本機佇列。'],preparing:['載入模型','正在準備固定版本的模型。'],analyzing:['分析音樂','讀取音樂節奏與特徵，長音檔需要較多時間。'],generating:['編排音符','依按鍵數、星數與段位偏好生成譜面。'],validating:['檢查譜面','檢查音符與長條，計算實際星數。'],packaging:['打包結果','寫入譜面資料、音樂與背景圖。'],completed:['譜面已完成',''],failed:['生成未完成',''],cancelled:['已取消','可以調整設定後重新生成。']};
function displayJob(job) {
  state.job=job;$('job-panel').hidden=false;$('job-panel').className=`job-panel ${job.status}`;
  const [title,description]=stageText[job.stage]||stageText.preparing;
  $('job-title').textContent=title;
  $('job-description').textContent=job.status==='completed'?`實際 ${job.result.actual_stars.toFixed(2)} ★ / 目標 ${job.result.target_stars.toFixed(1)} ★\n${job.result.taps} 個單鍵 · ${job.result.holds} 個 LN\n實際編排與難度仍以試玩感受為準。`:job.error||description;
  const elapsed=(new Date(job.finished_at||Date.now())-new Date(job.started_at||job.created_at))/1000;
  $('job-elapsed').textContent=duration(Math.max(0,elapsed));
  $('cancel-job').hidden=!active(job);$('result-actions').hidden=job.status!=='completed';
  $('job-error-details').hidden=!job.error_details;$('job-error-text').textContent=job.error_details||'';
  for(const kind of ['osu','osz']) $(`download-${kind}`).href=`/api/jobs/${job.id}/download/${kind}`;
  if(job.status==='completed')$('download-osz').firstChild.textContent=job.result.video_file?'下載含影片 .osz 譜面包 ':'下載 .osz 譜面包 ';
  const step={queued:0,preparing:0,analyzing:0,generating:1,validating:2,packaging:3,completed:4}[job.stage]??0;
  [...$('job-steps').children].forEach((el,i)=>el.className=i<step?'done':i===step&&active(job)?'current':'');
  render();
}
async function watchJob(id) {
  clearTimeout(pollTimer);
  const epoch=historyEpoch;
  try {
    const job=await api(`/api/jobs/${id}`);if(epoch!==historyEpoch)return;displayJob(job);
    if(active(job)) pollTimer=setTimeout(()=>watchJob(id),1200); else await refreshHistory();
  } catch(error) {if(epoch!==historyEpoch)return;toast(error.message);pollTimer=setTimeout(()=>watchJob(id),4000);}
}
form.onsubmit=async event=>{
  event.preventDefault();if(!state.audio||state.busy||state.importing||active(state.job)) return;
  // Metadata defaults keep optional fields convenient while producing valid osu metadata.
  if(!$('title').value.trim()) $('title').value=state.audio.title||'Untitled';
  if(!$('artist').value.trim()) $('artist').value='Unknown';
  if(!$('creator').value.trim()) $('creator').value='ManiaModel';
  if(!$('version').value.trim()) $('version').value=`${form.elements.keys.value}K - ${Number($('stars').value).toFixed(1)} stars`;
  if(!form.reportValidity()) return;
  state.busy++;render();
  try {const job=await api('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(settings())});displayJob(job);watchJob(job.id);refreshHistory();}
  catch(error){toast(error.message);}finally{state.busy--;render();}
};
$('cancel-job').onclick=async()=>{if(!state.job)return;try{displayJob(await api(`/api/jobs/${state.job.id}/cancel`,{method:'POST'}));await refreshHistory();}catch(error){toast(error.message);}};
function node(tag,className,text) {const el=document.createElement(tag);el.className=className;if(text!==undefined)el.textContent=text;return el;}
const emptyHistory=$('history-list').firstElementChild.cloneNode(true);
$('clear-history').onclick=async()=>{
  state.busy++;state.clearing=true;render();
  try {
    const info=await api('/api/history/cleanup');
    if(!info.can_clear)return toast('仍有生成或下載作業，請完成或取消後再清除。');
    if(!info.files)return toast('目前沒有需要清除的紀錄或檔案。');
    const size=info.bytes>=1073741824?`${(info.bytes/1073741824).toFixed(2)} GB`:`${(info.bytes/1048576).toFixed(1)} MB`;
    if(!confirm(`清除 ${info.jobs} 筆生成紀錄、${info.imports} 筆下載紀錄及 ${info.assets} 份音樂／背景資產？\n\n會永久刪除程式內的譜面、音樂、圖片、影片與暫存檔，約可釋放 ${size}，目前選取的音樂與背景也會清空。\n\n不包含瀏覽器另存的檔案或已匯入 osu! 的譜面。`))return;
    // Release the media stream before deleting its underlying file on Windows.
    $('audio-player').pause();$('audio-player').removeAttribute('src');$('audio-player').load();
    $('video-player').pause();$('video-player').removeAttribute('src');$('video-player').load();
    await api('/api/history',{method:'DELETE'});
    historyEpoch++;
    clearTimeout(pollTimer);clearTimeout(importTimer);
    state.job=null;state.importId=null;state.appliedImportId=null;state.importing=false;state.video=null;
    $('title').value='';$('artist').value='Unknown';
    for(const name of ['title_romanized','artist_romanized','source','tags'])form.elements[name].value='';
    showAsset('audio',null);showAsset('background',null);
    $('job-panel').hidden=true;$('youtube-feedback').hidden=true;$('youtube-url').value='';
    rememberImport(null);await refreshHistory();toast(`已清除紀錄與檔案，釋放約 ${size}。`);
  } catch(error){toast(error.message);if(state.audio)$('audio-player').src=state.audio.url;await refreshHistory().catch(()=>{});}
  finally{state.busy--;state.clearing=false;render();}
};
async function refreshHistory() {
  const {jobs}=await api('/api/jobs');$('history-count').textContent=jobs.length;
  if(!jobs.length)$('history-list').replaceChildren(emptyHistory.cloneNode(true));
  if(jobs.length) $('history-list').replaceChildren(...jobs.map(job=>{
    const card=node('article','history-card'),cover=node('div','history-cover',`${job.request.keys}K`),info=node('div','history-info');
    if(job.request.background_id) cover.style.backgroundImage=`linear-gradient(#17161d44,#17161d99),url('/api/uploads/${job.request.background_id}/file')`;
    info.append(node('h3','',job.request.metadata.title),node('p','',`${job.request.metadata.artist} · ${new Date(job.created_at).toLocaleString('zh-TW',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})}`));
    info.append(node('p',`history-status ${job.status}`,job.result?`${job.request.keys}K · ${job.result.actual_stars.toFixed(2)} ★ · ${job.request.techniques.join(' + ')||'未指定段位偏好'}`:(stageText[job.stage]||stageText.preparing)[0]));
    const links=node('div','history-links');
    if(job.status==='completed') {const download=node('a','text-button','下載 .osz');download.href=`/api/jobs/${job.id}/download/osz`;links.append(download);}
    const detail=node('button','text-button','查看結果');detail.type='button';detail.onclick=()=>{if(active(state.job)&&state.job.id!==job.id)return toast('目前仍在生成，請完成後再查看其他結果。');displayJob(job);if(active(job))watchJob(job.id);$('job-panel').scrollIntoView({behavior:'smooth',block:'center'});};
    links.append(detail);info.append(links);card.append(cover,info);return card;
  }));
  return jobs;
}
async function init() {
  try {
    await api('/api/health');state.online=true;$('connection-text').textContent='本機已連線';
    let draft;try{draft=JSON.parse(localStorage.getItem('mania-studio-draft'));}catch{}
    if(draft) {
      for(const [key,value] of Object.entries(draft.metadata||{})) if(form.elements[key])form.elements[key].value=value;
      if([4,7].includes(draft.keys))form.elements.keys.value=String(draft.keys);
      if(draft.stars>=.5&&draft.stars<=15)$('stars').value=$('stars-range').value=draft.stars;
      if(Array.isArray(draft.techniques))chips.forEach(c=>c.setAttribute('aria-pressed',String(draft.techniques.includes(c.dataset.tech))));
      state.versionEdited=!!draft.versionEdited;
      await Promise.all(['audio','background'].map(async kind=>{if(draft[`${kind}_id`])try{showAsset(kind,await api(`/api/uploads/${draft[`${kind}_id`]}`));}catch{}}));
      if(draft.video_id)try{const video=await api(`/api/uploads/${draft.video_id}`);if(video.kind==='video'&&video.audio_id===state.audio?.id)state.video=video;}catch{}
    }
    const jobs=await refreshHistory(), running=jobs.find(active);
    if(running)watchJob(running.id);
    const current=await api('/api/audio-imports/current');
    let pending;try{pending=localStorage.getItem('mania-studio-import');}catch{}
    if(current.item){$('youtube-url').value=current.item.url;rememberImport(current.item.id);importStatus(current.item);watchImport(current.item.id);}
    else if(pending){try{const item=await api(`/api/audio-imports/${pending}`);$('youtube-url').value=item.url;importStatus(item);if(active(item))watchImport(item.id);}catch{rememberImport(null);}}
  } catch(error) {state.online=false;$('connection').classList.add('offline');$('connection-text').textContent='連線失敗';toast(error.message);}
  render();
}
init();
