const $ = id => document.getElementById(id);
const keyName = 'image-provenance-poc-key';
let currentKey = localStorage.getItem(keyName), processFiles = [], compareFiles = [], outputs = [];
const screens = ['setup','dashboard','process','compare','database','settings'];
function show(name) { if (!currentKey && name !== 'setup') name = 'setup'; screens.forEach(s => $('screen-'+s).hidden = s !== name); $('settings-shortcut').hidden = !currentKey; $('back').hidden = !currentKey || name === 'dashboard'; if (name === 'database') loadDatabase(); window.scrollTo(0,0); }
// Files are sent as raw bytes; processed files come back as binary with the JSON result in a header.
const uploadHeaders = file => ({'Content-Type':'application/octet-stream','X-Media-Key':currentKey||'','X-File-Name':encodeURIComponent(file.name||'upload')});
async function request(path,file) {const r=await fetch('/api/'+path,{method:'POST',headers:uploadHeaders(file),body:file});const result=await r.json().catch(()=>({}));if(!r.ok)throw new Error(result.error||`Request failed (${r.status}).`);return result;}
// XHR rather than fetch so upload progress can be shown.
function upload(path,file,onProgress) {return new Promise((resolve,reject)=>{const x=new XMLHttpRequest();x.open('POST','/api/'+path);for(const [k,v] of Object.entries(uploadHeaders(file)))x.setRequestHeader(k,v);x.upload.onprogress=e=>e.lengthComputable&&onProgress(e.loaded,e.total);x.onload=()=>{let r={};try{r=JSON.parse(x.responseText);}catch{}x.status<300?resolve(r):reject(new Error(r.error||`Upload failed (${x.status}).`));};x.onerror=()=>reject(new Error('Upload failed. Check the file size and try again.'));x.send(file);});}
const sleep = ms => new Promise(r=>setTimeout(r,ms));
async function derive(value) {const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value));return btoa(String.fromCharCode(...new Uint8Array(bytes)));}
$('save-key').onclick=async()=>{const value=$('setup-key').value;if(!value.trim()){ $('setup-error').textContent='Enter a secret key to continue.';return;}currentKey=await derive(value);localStorage.setItem(keyName,currentKey);$('setup-key').value='';show('dashboard');};
$('change-key').onclick=async()=>{const value=$('new-key').value;if(!value.trim()){$('settings-result').textContent='Enter a new secret key.';return;}currentKey=await derive(value);localStorage.setItem(keyName,currentKey);$('new-key').value='';$('settings-result').textContent='Secret key updated.';};
$('home').onclick=()=>show('dashboard');$('back').onclick=()=>show('dashboard');$('settings-shortcut').onclick=()=>show('settings');document.querySelectorAll('[data-screen]').forEach(b=>b.onclick=()=>show(b.dataset.screen));
const previewUrls = {process: [], compare: []};
const isVideo = f => f.type.startsWith('video/')||/\.(mp4|m4v|mov|webm|mkv|avi)$/i.test(f.name), maxMB = 50;
fetch('/api/config').then(r=>r.json()).then(c=>{maxMB=c.max_upload_mb;}).catch(()=>{});
const plural = (n, word) => `${n} ${word}${n===1?'':'s'}`;
function selection(kind, files) {const media=Array.from(files).filter(f=>isVideo(f)||f.type.startsWith('image/')||/\.(png|jpe?g|webp|gif|bmp|tiff?)$/i.test(f.name));if(kind==='process'){processFiles=media;outputs=[];$('process-progress').hidden=true;fileProgress(null);$('process-go').disabled=false;$('downloads').hidden=true;$('download-all').hidden=true;$('process-result').replaceChildren();}else{compareFiles=media;$('compare-progress').hidden=true;fileProgress(null,'',0,0,undefined,'compare');}$(kind+'-selection').textContent=`${plural(media.length,'file')} selected.`;
 previewUrls[kind].forEach(URL.revokeObjectURL);previewUrls[kind]=[];const container=$(kind+'-previews');container.replaceChildren();
 for(const file of media.slice(0,24)){const url=URL.createObjectURL(file);previewUrls[kind].push(url);const item=document.createElement('div');item.className='preview-item';let thumb;if(isVideo(file)){thumb=document.createElement('video');thumb.muted=true;thumb.preload='metadata';thumb.src=url+'#t=0.1';item.classList.add('video');}else{thumb=document.createElement('img');thumb.src=url;thumb.alt=file.name;thumb.loading='lazy';}const label=document.createElement('span');label.textContent=file.name;label.title=file.name;item.append(thumb,label);container.append(item);}
 if(media.length>24){const more=document.createElement('div');more.className='preview-more';more.textContent=`+${media.length-24} more`;container.append(more);}
}
for(const kind of ['process','compare']) for(const type of ['files','folder']) $(kind+'-'+type).addEventListener('change',e=>selection(kind,e.target.files));
async function droppedFiles(items, onProgress) {
 const files=[];
 async function visit(entry) {
  if(entry.isFile) await new Promise((resolve,reject)=>entry.file(file=>{files.push(file);onProgress(files.length);resolve();},reject));
  else if(entry.isDirectory) { const reader=entry.createReader(); while(true) { const entries=await new Promise((resolve,reject)=>reader.readEntries(resolve,reject)); if(!entries.length)break; for(const child of entries)await visit(child); } }
 }
 for(const item of items) { const entry=item.webkitGetAsEntry?.(); if(entry) await visit(entry); else {const file=item.getAsFile();if(file){files.push(file);onProgress(files.length);}} }
 return files;
}
for(const kind of ['process','compare']) {
 const zone=$(kind+'-drop');
 for(const event of ['dragenter','dragover']) zone.addEventListener(event,e=>{e.preventDefault();zone.classList.add('dragging');});
 zone.addEventListener('dragleave',e=>{if(!zone.contains(e.relatedTarget))zone.classList.remove('dragging');});
 zone.addEventListener('drop',async e=>{e.preventDefault();zone.classList.remove('dragging');try{$(kind+'-selection').textContent='Reading dropped files…';selection(kind,await droppedFiles(e.dataTransfer.items, count => $(kind+'-selection').textContent=`Reading folder… ${count} file${count===1?'':'s'} found.`));}catch(error){$(kind+'-selection').textContent='Could not read the dropped files. Please use a picker.';}});
}
function row(container,title,detail,failed=false){const div=document.createElement('div');div.className='result-row'+(failed?' failed':'');const strong=document.createElement('strong');strong.textContent=title;const p=document.createElement('p');p.textContent=detail;div.append(strong,p);container.append(div);}
function modal(message){return new Promise(resolve=>{$('rejected-message').textContent=message;const dialog=$('rejected-dialog');dialog.addEventListener('close',resolve,{once:true});dialog.showModal();});}
$('close-dialog').onclick=()=>$('rejected-dialog').close();
const mb = n => (n/1048576).toFixed(1)+' MB';
// Only the file currently being processed is shown; total=null shows an indeterminate bar.
function fileProgress(name, stage, done, total, detail, kind='process') { const p=kind+'-file-progress', panel=$(p), appearing=panel.hidden&&!!name; panel.hidden=!name; if(!name) return; if(appearing) panel.scrollIntoView({block:'nearest'}); $(p+'-name').textContent=name; $(p+'-stage').textContent=stage; const bar=$(p+'-bar'); if(total){const pct=Math.min(100,Math.round(done/total*100));bar.value=pct;$(p+'-detail').textContent=detail??`${pct}%`;}else{bar.removeAttribute('value');$(p+'-detail').textContent=detail??'';} }
async function processFile(file) {
 fileProgress(file.name,'Uploading',0,file.size);
 const {job_id}=await upload('jobs',file,(sent,total)=>fileProgress(file.name,'Uploading',sent,total,`${mb(sent)} of ${mb(total)}`));
 let status;
 while(true){ await sleep(400); const r=await fetch('/api/jobs/'+job_id); status=await r.json(); if(!r.ok) throw new Error(status.error||'Lost track of this file.');
  if(status.state==='error') throw new Error(status.error);
  const frames=/frames|Verifying/.test(status.stage)&&status.total?`frame ${Math.min(status.done,status.total)} of ${status.total}`:undefined;
  fileProgress(file.name,status.stage,status.done,status.total,frames);
  if(status.state==='done') break; }
 fileProgress(file.name,'Downloading result',0,null);
 const r=await fetch(`/api/jobs/${job_id}/file`); if(!r.ok) throw new Error('Could not download the processed file.');
 return {...status.result,bytes:new Uint8Array(await r.arrayBuffer())};
}
function progress(label, done, total, kind='process') { $(kind+'-progress').hidden=false; $(kind+'-progress-label').textContent=label; $(kind+'-progress-count').textContent=`${done} / ${total}`; $(kind+'-progress-bar').value=total ? Math.round(done / total * 100) : 0; }
// Images are inspected server-side; videos are validated when processed.
async function screenFiles(files, kind, onChecked) {const valid=[];let small=0,unreadable=0,large=0,checked=0;for(const file of files){$(kind+'-selection').textContent=`Checking files: ${checked+1} of ${files.length}…`;try{if(file.size>maxMB*1024*1024)large++;else if(isVideo(file))valid.push({file});else{const info=await request('inspect',file);if(info.pixels<768)small++;else valid.push({file});}}catch(e){unreadable++;}onChecked(++checked);}
 if(small||unreadable||large){const skipped=[small&&`${plural(small,'image')} had fewer than 768 pixels`,large&&`${plural(large,'file')} exceeded ${maxMB} MB`,unreadable&&`${plural(unreadable,'file')} could not be read`].filter(Boolean).join('; ');await modal(`${skipped}. ${plural(valid.length,'file')} ready to ${kind}.`);}
 return valid;}
$('process-go').onclick=async()=>{const button=$('process-go'),result=$('process-result');result.replaceChildren();$('downloads').hidden=true;$('download-all').hidden=true;outputs=[];if(!processFiles.length){row(result,'Choose images or videos first.','',true);return;}button.disabled=true;progress('Checking files',0,processFiles.length);try{const valid=await screenFiles(processFiles,'process',n=>progress('Checking files',n,processFiles.length));let completed=0;progress('Fingerprinting and watermarking',0,valid.length);for(const item of valid){$('process-selection').textContent=`Processing ${isVideo(item.file)?'video':'image'} ${completed+1} of ${valid.length}…`;try{const r=await processFile(item.file);const ext=r.kind==='video'?'.mp4':'.png';const base=item.file.name.replace(/\.[^.]+$/,'')+'-watermarked';let name=base+ext,suffix=2;while(outputs.some(output=>output.name===name))name=`${base}-${suffix++}${ext}`;outputs.push({name,data:r.bytes,date:Date.now()});}catch(e){row(result,item.file.name,e.message,true);}progress('Fingerprinting and watermarking',++completed,valid.length);}if(outputs.length){$('downloads').hidden=false;$('download-all').hidden=false;const summary=document.createElement('p');summary.textContent=`${outputs.length} of ${plural(processFiles.length,'file')} fingerprinted and watermarked.`;result.prepend(summary);}else if(!valid.length)row(result,'Nothing to process.',`Select images with at least 768 pixels or files under ${maxMB} MB.`,true);}finally{fileProgress(null);button.disabled=outputs.length>0;$('process-files').value='';$('process-folder').value='';progress('Processing complete',outputs.length,processFiles.length);$('process-selection').textContent=`${outputs.length} of ${plural(processFiles.length,'file')} processed.`;}};
$('compare-go').onclick=async()=>{const button=$('compare-go'),result=$('compare-result');result.replaceChildren();if(!compareFiles.length){row(result,'Choose images or videos first.','',true);return;}button.disabled=true;let completed=0,valid=[];progress('Checking files',0,compareFiles.length,'compare');try{valid=await screenFiles(compareFiles,'compare',n=>progress('Checking files',n,compareFiles.length,'compare'));progress('Comparing files',0,valid.length,'compare');for(const {file} of valid){$('compare-selection').textContent=`Comparing files: ${completed+1} of ${valid.length}…`;fileProgress(file.name,'Uploading',0,file.size,undefined,'compare');try{const r=await upload('compare',file,(sent,total)=>sent<total?fileProgress(file.name,'Uploading',sent,total,`${mb(sent)} of ${mb(total)}`,'compare'):fileProgress(file.name,'Checking fingerprint and watermark',0,null,undefined,'compare'));result.append(compareCard(file.name,r));}catch(e){row(result,file.name,e.message,true);}progress('Comparing files',++completed,valid.length,'compare');}}finally{fileProgress(null,'',0,0,undefined,'compare');button.disabled=false;progress('Comparison complete',completed,valid.length,'compare');$('compare-selection').textContent='Comparison complete.';}};
const el = (tag, cls, text) => {const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e;};
const when = t => new Date(t*1000).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});
function details(rows){const d=el('details'),list=el('dl');d.append(el('summary',null,'Technical details'));for(const [label,value] of rows){const line=el('div');line.append(el('dt',null,label),el('dd',null,value));list.append(line);}d.append(list);return d;}
// One card per compared file: an overall verdict, what it matched, and the two checks in plain language.
function compareCard(name, r) {
 const fp=r.status==='CONTENT_MATCH_ONLY', wm=r.watermark||{}, marked=!!wm.authenticated, f=r.fingerprint;
 const [tone,verdict]=fp&&marked?['ok','Verified match']:marked?['ok','Watermark verified']:fp?['warn','Visual match only']:['none','No match'];
 const card=el('article','match-card '+tone), head=el('div','match-head'), info=el('div');
 info.append(el('h2',null,name));
 const target=wm.registered_as||(fp?r.creator:null), at=wm.registered_at||r.registered_at;
 info.append(el('p','match-sub',target?`Matches ${target}${at?' · registered '+when(at):''}`:marked?'Watermark made with your key, but the file is not in this database':'Not found in your database'));
 head.append(info,el('span','verdict '+tone,verdict));
 const checks=el('ul','checks');
 const check=(ok,label,text)=>{const li=el('li',ok?'ok':'');li.append(el('span','check-icon',ok?'✓':'–'),el('span','check-label',label),el('span','check-text',text));checks.append(li);};
 check(fp,'Visual fingerprint',fp?(f.distance===0?'Identical to the registered file':'Very similar to the registered file'):f?'No similar file registered':'Could not be fingerprinted');
 check(marked,'Watermark',marked?(wm.registered_as?'Verified with your key':'Verified, but not recorded in this database'):'Not found with your key');
 const rows=[['Media type',r.kind==='video'?'Video':'Image']];
 if(f)rows.push(['Fingerprint distance',`${f.distance} (match threshold ${r.threshold}, uncalibrated)`]);
 if(f&&f.next_distance!=null)rows.push(['Next closest distance',String(f.next_distance)]);
 if(marked)rows.push(['Watermark identifier',wm.watermark_id]);
 if(wm.frames_sampled)rows.push(['Frames checked',String(wm.frames_sampled)]);
 if(wm.bits_corrected)rows.push(['Bits corrected',String(wm.bits_corrected)]);
 card.append(head,checks,details(rows)); return card;
}
async function loadDatabase(){
 const box=$('database-list'); box.textContent='Loading…';
 try {
  const response=await fetch('/api/database'); if(!response.ok)throw new Error('Could not load database.');
  const data=await response.json(); box.replaceChildren();
  if(!data.items.length){box.textContent='Nothing registered yet. Process images or videos to add them here.';box.className='database-list empty';return;}
  box.className='database-list';
  for(const item of data.items){
   const card=document.createElement('article');card.className='db-card';
   const head=document.createElement('div');head.className='db-card-head';
   const info=document.createElement('div'),title=document.createElement('h2'),date=document.createElement('p');title.textContent=item.filename||item.name;date.textContent='Registered '+new Date(item.created*1000).toLocaleString();info.append(title,date);
   const status=document.createElement('span');status.className='db-badge'+(item.watermark_id?'':' muted');status.textContent=item.watermark_id?'Fingerprinted & watermarked':'Legacy: watermark not recorded';const type=document.createElement('span');type.className='db-badge muted';type.textContent=item.kind==='video'?'Video':'Image';const badges=document.createElement('div');badges.className='db-badges';badges.append(type,status);head.append(info,badges);
   const details=document.createElement('details'),toggle=document.createElement('summary');toggle.textContent='Technical details';details.append(toggle);
   const list=document.createElement('dl');for(const [label,value] of [['Media type',item.kind==='video'?'Video':'Image'],[item.kind==='video'?'Perceptual fingerprints (sampled frames)':'Perceptual fingerprint',item.phash],['SHA-256',item.sha256],['Watermark identifier',item.watermark_id||'Not recorded'],['Asset ID',item.asset_id],['Registry label',item.name]]){const line=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=value;line.append(dt,dd);list.append(line);}details.append(list);card.append(head,details);box.append(card);
  }
 }catch(e){box.textContent=e.message;}
}
// Each file is its own download; the pause keeps browsers from dropping rapid back-to-back downloads.
$('download-all').onclick=async()=>{for(const output of outputs){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([output.data],{type:output.name.endsWith('.mp4')?'video/mp4':'image/png'}));a.download=output.name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),60000);await new Promise(r=>setTimeout(r,400));}};
show(currentKey?'dashboard':'setup');
